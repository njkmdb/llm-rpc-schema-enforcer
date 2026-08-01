from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

# =====================================================================
# [LRSE Middleware Schema Definitions]
# 클라이언트 앱과 LLM 간의 완벽한 RPC 인터페이스를 제공하는 스키마입니다.
# =====================================================================

class LlmRpcRequest(BaseModel):
    """LRSE 미들웨어에 LLM 추론을 요청하는 RPC(Remote Procedure Call) 페이로드"""
    
    context_payload: str = Field(
        ..., 
        description="LLM에 전달할 클라이언트의 컨텍스트 (예: JSON 로그, 사용자 요청, 원시 텍스트)"
    )
    schema_name: str = Field(
        ..., 
        description="LRSE 서버에 등록된 반환 Pydantic 스키마의 식별자명 (예: 'StructuredCommand')"
    )
    system_instruction: Optional[str] = Field(
        default="", 
        description="모델의 역할을 규정하고 행동을 구속하는 추가 시스템 지시어"
    )

class LlmRpcResponse(BaseModel):
    """LRSE 미들웨어를 통과하여 스키마 검증(Enforcement)이 100% 완료된 응답"""
    
    status: str = Field(
        ..., 
        description="RPC 호출 상태 (success, fallback, error)"
    )
    validated_data: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Pydantic 스키마 검증을 무사히 통과한 무결한 JSON 객체"
    )
    message: Optional[str] = Field(
        None, 
        description="성공 로그 또는 오류 발생 시의 상세 에러 메시지"
    )