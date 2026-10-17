from typing import Any, Dict, List, Optional
import pytest
from pydantic import ValidationError

from core_engine.schemas.api_models import LlmRpcRequest
from core_engine.schemas.llm_io import ActionType, Command, StructuredCommand
from core_engine.state.db_manager import StateManager
from core_engine.vm.interpreter import VMInterpreter
from core_engine.vm.lrse_enforcer import LlmRpcSchemaEnforcer


# =====================================================================
# 1. LlmRpcRequest 스키마 검증기(Validator) 경계값 테스트
# =====================================================================
@pytest.mark.parametrize(
    "schema_name,dynamic_schema,should_succeed",
    [
        ("StructuredCommand", None, True),
        (None, {"type": "object", "properties": {"id": {"type": "string"}}}, True),
        ("StructuredCommand", {"type": "object"}, True),
        (None, None, False),
        ("", None, False),
        (None, {}, False),
    ],
)
def test_llm_rpc_request_schema_target_validation(
    schema_name: Optional[str],
    dynamic_schema: Optional[Dict[str, Any]],
    should_succeed: bool,
) -> None:
    """schema_name과 dynamic_schema_definition 조합에 따른 요청 유효성 검증"""
    if should_succeed:
        req = LlmRpcRequest(
            context_payload="Test payload",
            schema_name=schema_name,
            dynamic_schema_definition=dynamic_schema,
        )
        assert req.context_payload == "Test payload"
    else:
        with pytest.raises(ValidationError):
            LlmRpcRequest(
                context_payload="Invalid payload",
                schema_name=schema_name,
                dynamic_schema_definition=dynamic_schema,
            )


# =====================================================================
# 2. Gemini SDK 호환용 재귀 스키마 정제(_sanitize_schema_for_gemini) 검증
# =====================================================================
def test_deeply_nested_schema_sanitization() -> None:
    """다중 중첩된 JSON Schema 내부의 $schema 및 additionalProperties 키가 완벽히 제거되는지 검증"""
    raw_nested_schema: Dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "metadata": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "items": {
                        "type": "array",
                        "items": [
                            {
                                "type": "object",
                                "$schema": "nested_meta",
                                "additionalProperties": True,
                                "properties": {"key": {"type": "string"}},
                            }
                        ],
                    }
                },
            }
        },
    }

    sanitized = LlmRpcSchemaEnforcer._sanitize_schema_for_gemini(raw_nested_schema)

    # 원본 딕셔너리는 변경되지 않았는지(Deepcopy 무결성) 확인
    assert "$schema" in raw_nested_schema
    assert "additionalProperties" in raw_nested_schema

    # 정제된 딕셔너리 트리 전체에서 금지 키가 제거되었는지 확인
    serialized = str(sanitized)
    assert "$schema" not in serialized
    assert "additionalProperties" not in serialized
    assert sanitized["properties"]["metadata"]["properties"]["items"]["items"][0]["properties"]["key"]["type"] == "string"


# =====================================================================
# 3. VMInterpreter 예외 방어 및 부분 실패(Partial Failure) 격리 검증
# =====================================================================
@pytest.mark.parametrize(
    "invalid_command,expected_error_substring",
    [
        (
            Command(action=ActionType.SPAWN_ENTITY, target_id=None, value={"type": "node"}),
            "SPAWN_ENTITY requires a target_id",
        ),
        (
            Command(action=ActionType.SPAWN_ENTITY, target_id="worker_node_a", value={"type": "node"}),
            "EntityAlreadyExists",
        ),
        (
            Command(action=ActionType.UPDATE_ATTRIBUTE, target_id="ghost_node_999", key="cpu", value=10),
            "EntityNotFound",
        ),
        (
            Command(action=ActionType.ROUTE_EVENT, target_id="worker_node_a", key="evt", value="trigger"),
            "Unsupported or Unknown ActionType",
        ),
    ],
)
def test_vm_interpreter_graceful_command_failure_handling(
    seeded_state_manager: StateManager,
    invalid_command: Command,
    expected_error_substring: str,
) -> None:
    """잘못된 개별 명령어가 들어와도 전체 트랜잭션이 중단되지 않고 report에 failed로 기록되는지 검증"""
    interpreter = VMInterpreter(seeded_state_manager)
    batch = StructuredCommand(
        commands=[
            invalid_command,
            Command(action=ActionType.ADD_TAG, target_id="worker_node_a", value="recovered_after_error"),
        ]
    )

    report, modified_entities = interpreter.execute("default_seeded_session", batch)

    assert len(report) == 2
    assert report[0]["status"] == "failed"
    assert expected_error_substring in report[0]["message"]

    # 첫 번째 명령어가 실패했더라도 두 번째 정상 명령어는 정상 수행되어야 함
    assert report[1]["status"] == "success"
    assert len(modified_entities) == 1
    assert "recovered_after_error" in modified_entities[0].tags