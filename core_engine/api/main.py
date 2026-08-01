import logging
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core_engine.schemas.api_models import LlmRpcRequest, LlmRpcResponse
from core_engine.vm.lrse_enforcer import LlmRpcSchemaEnforcer, RpcEnforcementError
from core_engine.schemas.llm_io import StructuredCommand
from core_engine.state.db_manager import StateManager
from core_engine.vm.interpreter import VMInterpreter

logger = logging.getLogger("LRSE_Gateway")
logger.setLevel(logging.INFO)

# =====================================================================
# [LRSE System Initialization]
# =====================================================================
state_manager = StateManager()
vm_interpreter = VMInterpreter(state_manager)

app = FastAPI(
    title="LRSE Core API (LLM RPC Schema Enforcer)", 
    version="1.0.0", 
    description="LLM 호출을 스키마 기반의 백엔드 RPC로 강제하는 미들웨어"
)

app.add_middleware(
    CORSMiddleware, 
    # 주의: 프로덕션 배포 시에는 프론트엔드 도메인으로 제한하는 것을 권장합니다.
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# =====================================================================
# 💡 [Dependency Injection] Auth & BYOK Enforcer
# =====================================================================

def get_llm_enforcer(
    x_gemini_api_key: str = Header(..., description="사용자 개인 발급 Gemini API Key")
) -> LlmRpcSchemaEnforcer:
    """
    클라이언트가 헤더로 보낸 API 키를 사용하여 요청마다 Enforcer를 동적으로 생성합니다.
    서버는 사용자의 API 키를 보관하지 않습니다.
    """
    try:
        return LlmRpcSchemaEnforcer(api_key=x_gemini_api_key)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"유효하지 않은 API 키입니다: {str(e)}")

def verify_session_access(
    session_id: str, 
    x_session_secret: str = Header(..., description="해당 세션의 소유자 인증 비밀번호")
) -> str:
    """
    DB를 조회하여 session_id와 x_session_secret 일치 여부를 검증합니다.
    """
    is_valid = state_manager.verify_or_create_session(session_id, x_session_secret)
    if not is_valid:
        raise HTTPException(status_code=401, detail="세션 인증에 실패했습니다. (비밀번호 불일치)")
    return session_id

# =====================================================================
# 💡 [LRSE Schema Registry]
# =====================================================================
SCHEMA_REGISTRY = {
    "StructuredCommand": StructuredCommand, 
}

# =====================================================================
# [API Endpoints]
# =====================================================================

@app.post("/api/v1/rpc/call", response_model=LlmRpcResponse)
async def call_llm_rpc_endpoint(
    request: LlmRpcRequest, 
    enforcer: LlmRpcSchemaEnforcer = Depends(get_llm_enforcer)
):
    """
    [Read-Only] 상태를 변경하지 않는 순수 데이터 조회/생성용 RPC 호출.
    대사 생성, 시나리오 분석 등 영속화(DB Commit)가 필요 없는 작업에 사용됩니다.
    """
    try:
        if request.schema_name not in SCHEMA_REGISTRY:
            raise ValueError(f"요청한 스키마 '{request.schema_name}'가 레지스트리에 없습니다.")
            
        target_schema_class = SCHEMA_REGISTRY[request.schema_name]
        
        validated_obj = enforcer.call_rpc(
            context_payload=request.context_payload,
            response_schema=target_schema_class,
            system_instruction=request.system_instruction,
            max_retries=3
        )
        
        return LlmRpcResponse(
            status="success",
            validated_data=validated_obj.model_dump(),
            message="스키마 강제화 및 데이터 검증 완료."
        )
        
    except ValueError as val_err:
        logger.warning(f"RPC Bad Request: {str(val_err)}")
        raise HTTPException(status_code=400, detail=str(val_err))
        
    except RpcEnforcementError as rpc_err:
        logger.error(f"RPC Enforcement Failed: {str(rpc_err)}")
        raise HTTPException(status_code=422, detail=f"스키마 강제화 최종 실패: {str(rpc_err)}")
        
    except Exception as e:
        logger.error(f"RPC Endpoint Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서버 내부 오류: {str(e)}")


@app.post("/api/v1/rpc/execute", response_model=LlmRpcResponse)
async def execute_stateful_rpc(
    request: LlmRpcRequest, 
    # 의존성 주입을 통해 세션 검증과 API 키 기반 Enforcer 객체를 주입받습니다.
    verified_session_id: str = Depends(verify_session_access),
    enforcer: LlmRpcSchemaEnforcer = Depends(get_llm_enforcer)
):
    """
    [Stateful] LLM의 추론 결과를 기반으로 시스템 상태(Entity)를 변이하고 DB에 영속화합니다.
    """
    try:
        command_batch = enforcer.call_rpc(
            context_payload=request.context_payload,
            response_schema=StructuredCommand,
            system_instruction=request.system_instruction,
            max_retries=3
        )

        execution_report, modified_entities = vm_interpreter.execute(
            session_id=verified_session_id,
            structured_command=command_batch
        )

        new_snapshot_id = state_manager.commit_turn(
            session_id=verified_session_id,
            active_entities=modified_entities
        )

        return LlmRpcResponse(
            status="success",
            validated_data={
                "snapshot_id": new_snapshot_id,
                "report": execution_report,
                "modified_entities": [ent.model_dump() for ent in modified_entities]
            },
            message="상태 변이 및 영속화가 완료되었습니다."
        )

    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except RpcEnforcementError as rpc_err:
        raise HTTPException(status_code=422, detail=f"명령어 생성 실패: {str(rpc_err)}")
    except Exception as e:
        logger.error(f"Stateful RPC Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"상태 영속화 중 오류 발생: {str(e)}")