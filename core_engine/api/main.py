import logging
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core_engine.schemas.api_models import LlmRpcRequest, LlmRpcResponse, LlmSessionInitRequest
from core_engine.vm.lrse_enforcer import LlmRpcSchemaEnforcer, RpcEnforcementError
from core_engine.schemas.llm_io import StructuredCommand, UniversalEntity
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
    x_gemini_api_key: str = Header(..., description="사용자 개인 발급 Gemini API Key"),
    x_model_name: str = Header(default="gemini-1.5-pro", description="클라이언트가 선택한 LLM 모델명")
) -> LlmRpcSchemaEnforcer:
    try:
        return LlmRpcSchemaEnforcer(api_key=x_gemini_api_key, model_name=x_model_name) 
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
    verified_session_id: str = Depends(verify_session_access),
    enforcer: LlmRpcSchemaEnforcer = Depends(get_llm_enforcer)
):
    """
    [Read-Only] 상태를 변경하지 않는 순수 데이터 조회/생성용 RPC 호출.
    DB에 저장된 동적 스키마(JSON Schema) 또는 내부 레지스트리를 활용합니다.
    """
    try:
        # 1. DB에서 최신 상태 스냅샷 전체 조회
        _, current_state = state_manager.get_latest_state(verified_session_id)
        
        # 2. 상태(페이로드) 내부의 entities 리스트에서 요청한 스키마 검색
        schema_entity_dict = None
        if current_state and "entities" in current_state:
            for ent in current_state["entities"]:
                if ent.get("id") == request.schema_name:
                    schema_entity_dict = ent
                    break
        
        # 3. 스키마 할당 (DB 동적 스키마 딕셔너리 최우선 -> 레지스트리 폴백)
        if schema_entity_dict and schema_entity_dict.get("type") == "schema":
            target_schema = schema_entity_dict.get("attributes") # 원시 JSON Schema 딕셔너리 할당
        elif request.schema_name in SCHEMA_REGISTRY:
            target_schema = SCHEMA_REGISTRY[request.schema_name] # 폴백: 코어 Pydantic 스키마
        else:
            raise ValueError(f"스키마 '{request.schema_name}'를 DB(세션) 또는 레지스트리에서 찾을 수 없습니다.")
            
        # 4. Enforcer 호출
        validated_obj_or_dict = enforcer.call_rpc(
            context_payload=request.context_payload,
            response_schema=target_schema,
            system_instruction=request.system_instruction,
            max_retries=3
        )
        
        # 반환값이 Pydantic 모델이면 dump, 딕셔너리(동적 스키마 결과)면 그대로 반환
        final_data = validated_obj_or_dict.model_dump() if hasattr(validated_obj_or_dict, "model_dump") else validated_obj_or_dict
        
        return LlmRpcResponse(
            status="success",
            validated_data=final_data,
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

        # 낙관적 락 검증을 위해 현재 최신 상태의 old_slot_id를 가져옴
        old_slot_id, _ = state_manager.get_latest_state(verified_session_id)
        
        # 새로운 시그니처(session_id, old_slot_id, new_payload)에 맞춰 커밋
        new_snapshot_id = state_manager.commit_turn(
            session_id=verified_session_id,
            old_slot_id=old_slot_id,
            new_payload={"entities": [ent.model_dump() for ent in modified_entities]}
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

@app.post("/api/v1/session/init")
async def init_session(request: LlmSessionInitRequest):
    """
    [Init] 원격 클라우드 환경을 위한 세션 초기화 및 동적 스키마(Seed) 주입 엔드포인트.
    CLI의 `init_db.py`와 완벽하게 동일한 역할을 HTTP 상에서 수행합니다.
    """
    is_valid = state_manager.verify_or_create_session(request.session_id, request.session_secret)
    if not is_valid:
        raise HTTPException(status_code=401, detail="세션 인증 실패 (비밀번호 불일치).")
        
    snapshot_id = None
    if request.custom_seed:
        try:
            entities = []
            for item in request.custom_seed:
                ent = UniversalEntity(
                    id=item.get("id", "unknown_id"),
                    type=item.get("type", "unknown_type"),
                    attributes=item.get("attributes", {}),
                    tags=item.get("tags", [])
                )
                entities.append(ent)
                
            # 💡 기존 세션 데이터가 있는지 확인하여 old_slot_id를 동적으로 할당 (재동기화 에러 방지)
            try:
                old_slot_id, _ = state_manager.get_latest_state(request.session_id)
            except Exception:
                old_slot_id = None
                
            snapshot_id = state_manager.commit_turn(
                session_id=request.session_id,
                old_slot_id=old_slot_id,
                new_payload={"entities": [ent.model_dump() for ent in entities]}
            )
        except Exception as e:
            logger.error(f"Seed Data Commit Error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"시드 데이터 커밋 실패: {str(e)}")
            
    return {
        "status": "success", 
        "message": "세션 초기화 및 시드 데이터 동기화 완료", 
        "snapshot_id": snapshot_id
    }