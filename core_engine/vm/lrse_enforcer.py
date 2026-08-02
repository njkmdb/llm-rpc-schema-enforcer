"""
[LRSE AI-Driven RPC Enforcer]
LLM을 단순 텍스트 생성기가 아닌 결정론적(Deterministic) RPC 서버로 취급하는 핵심 코어 모듈입니다.
Pydantic 스키마 검증과 자동 재시도(Retry) 메커니즘을 결합하여 환각 데이터를 원천 차단합니다.
"""

import logging
import time
import json
import jsonschema
import copy
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from typing import TypeVar, Type, Union, Dict, Any
from pydantic import BaseModel, ValidationError
from google import genai
from google.genai import types

logger = logging.getLogger("LRSE_Enforcer")
logger.setLevel(logging.INFO)

# 제네릭 타입 변수: 어떠한 Pydantic 스키마든 유연하게 수용
T = TypeVar('T', bound=BaseModel)

class RpcEnforcementError(Exception):
    """LRSE 스키마 강제화 실패 커스텀 예외"""
    pass

class LlmRpcSchemaEnforcer:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def call_rpc(self, context_payload: str, response_schema: Union[Type[T], Dict[str, Any]], system_instruction: str = "", max_retries: int = 3) -> Union[T, Dict[str, Any]]:
        """
        LLM에 RPC 요청을 보내고, 지정된 스키마로 100% 검증된 데이터 객체를 반환합니다.
        실패 시 에러 컨텍스트를 주입하여 자가 교정(Self-correction) 재시도를 수행합니다.
        """
        # 1. 스키마 추출 분기 (Pydantic 모델 vs 원시 JSON Schema 딕셔너리)
        if isinstance(response_schema, dict):
            schema_definition = response_schema
            is_dynamic_schema = True
        else:
            schema_definition = response_schema.model_json_schema()
            is_dynamic_schema = False
            
        # 💡 [핵심 패치] Gemini SDK가 거부하는 메타데이터 키 제거 (안전한 복사본 사용)
        gemini_safe_schema = copy.deepcopy(schema_definition)
        if "$schema" in gemini_safe_schema:
            del gemini_safe_schema["$schema"]
        
        strict_instruction = (
            f"{system_instruction}\n\n"
            "STRICT ENFORCEMENT RULES:\n"
            "1. You are a backend RPC handler. You MUST return ONLY a valid JSON object.\n"
            f"2. Your response MUST strictly adhere to the following JSON Schema:\n{schema_definition}\n"
            "3. Do not include markdown formatting or extra text."
        )

        last_error = None
        current_payload = context_payload

        # 2. 결함 허용(Fault Tolerance)을 위한 다중 재시도 루프
        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=current_payload,
                    config=types.GenerateContentConfig(
                        system_instruction=strict_instruction,
                        response_mime_type="application/json", 
                        temperature=0.0, # 환각 방어를 위한 온도 고정
                        # 💡 원본 대신 정제된 스키마 전달
                        response_schema=gemini_safe_schema 
                    )
                )
                
                # 💡 [핵심 방어선] 검증 방식 분기 처리 (검증 시에는 원본 스키마 사용)
                if is_dynamic_schema:
                    # 동적 스키마의 경우 jsonschema 패키지를 통한 완벽한 규격 검증
                    parsed_json = json.loads(response.text)
                    jsonschema.validate(instance=parsed_json, schema=schema_definition)
                    return parsed_json
                else:
                    return response_schema.model_validate_json(response.text)
                
            except (ValidationError, JsonSchemaValidationError, json.JSONDecodeError) as val_err:
                last_error = val_err
                logger.warning(f"[LRSE Security Block] 시도 {attempt}/{max_retries} - 스키마 규격 위반 감지: {val_err}")
                
                # 💡 [자가 치유 로직] LLM이 실수한 부분을 다시 프롬프트에 먹여서 구조 수정을 유도
                current_payload += f"\n\n[SYSTEM ERROR IN PREVIOUS ATTEMPT] You violated the schema. Error details: {val_err}. Fix the JSON structure."
                time.sleep(1)
                
            except Exception as e:
                last_error = e
                logger.warning(f"[LRSE Network Exception] 시도 {attempt}/{max_retries} - 통신 오류: {e}")
                time.sleep(2)
                
        logger.error(f"❌ [LRSE FATAL] {max_retries}회 재시도 실패. RPC 호출을 강제 종료합니다.")
        raise RpcEnforcementError(f"Failed to execute LLM RPC call after {max_retries} attempts.") from last_error