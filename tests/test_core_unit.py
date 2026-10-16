import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from core_engine.schemas.llm_io import ActionType, Command, StructuredCommand, UniversalEntity
from core_engine.state.db_manager import ConcurrencyConflictError, StateManager
from core_engine.vm.interpreter import VMInterpreter
from core_engine.vm.lrse_enforcer import LlmRpcSchemaEnforcer, RpcEnforcementError


@pytest.fixture
def isolated_state_manager(tmp_path: Path) -> StateManager:
    """임시 SQLite DB 파일을 사용하는 격리된 StateManager 픽스처"""
    db_file = tmp_path / "unit_test_state.db"
    return StateManager(db_path=str(db_file))


# =====================================================================
# 1. StateManager (MVCC & 낙관적 락) 기존 기능 검증
# =====================================================================
def test_session_auth_and_entity_lookup(isolated_state_manager: StateManager) -> None:
    session_id = "session_alpha"
    secret = "correct_secret_123"

    # 최초 세션 생성 및 인증 성공 검증
    assert isolated_state_manager.verify_or_create_session(session_id, secret) is True
    # 동일 비밀번호 재인증 성공 및 오타 비밀번호 차단 검증
    assert isolated_state_manager.verify_or_create_session(session_id, secret) is True
    assert isolated_state_manager.verify_or_create_session(session_id, "wrong_secret") is False

    # 초기 상태 커밋 및 단일 엔티티 조회(get_entity) 검증
    node = UniversalEntity(
        id="worker_node_a",
        type="node",
        attributes={"cpu_usage": 40, "memory": 1024},
        tags=["active"]
    )
    old_slot, _ = isolated_state_manager.get_latest_state(session_id)
    assert old_slot is None

    new_slot = isolated_state_manager.commit_turn(
        session_id=session_id,
        old_slot_id=old_slot,
        new_payload={"entities": [node.model_dump()]}
    )
    assert new_slot.startswith("slot_")

    fetched = isolated_state_manager.get_entity(session_id, "worker_node_a")
    assert fetched is not None
    assert fetched.id == "worker_node_a"
    assert fetched.attributes["cpu_usage"] == 40
    assert isolated_state_manager.get_entity(session_id, "non_existent") is None


def test_optimistic_lock_concurrency_conflict(isolated_state_manager: StateManager) -> None:
    session_id = "session_race"
    isolated_state_manager.verify_or_create_session(session_id, "secret")

    slot_1 = isolated_state_manager.commit_turn(session_id, None, {"entities": []})
    slot_2 = isolated_state_manager.commit_turn(session_id, slot_1, {"entities": [{"id": "n1"}]})
    assert slot_1 != slot_2

    # 이미 구버전이 된 slot_1을 기반으로 재커밋 시도 시 ConcurrencyConflictError 발생 검증
    with pytest.raises(ConcurrencyConflictError):
        isolated_state_manager.commit_turn(session_id, slot_1, {"entities": [{"id": "n2"}]})


# =====================================================================
# 2. VMInterpreter (SPAWN / UPDATE / TAG) 기존 기능 검증
# =====================================================================
def test_vm_interpreter_entity_mutations(isolated_state_manager: StateManager) -> None:
    session_id = "session_vm"
    isolated_state_manager.verify_or_create_session(session_id, "secret")

    seed_entity = UniversalEntity(
        id="worker_node_a",
        type="node",
        attributes={"cpu_usage": 50},
        tags=["active", "legacy"]
    )
    isolated_state_manager.commit_turn(
        session_id=session_id,
        old_slot_id=None,
        new_payload={"entities": [seed_entity.model_dump()]}
    )

    interpreter = VMInterpreter(isolated_state_manager)
    command_batch = StructuredCommand(
        commands=[
            Command(action=ActionType.UPDATE_ATTRIBUTE, target_id="worker_node_a", key="cpu_usage", value=30),
            Command(action=ActionType.ADD_TAG, target_id="worker_node_a", value="load_balanced"),
            Command(action=ActionType.REMOVE_TAG, target_id="worker_node_a", value="legacy"),
            Command(
                action=ActionType.SPAWN_ENTITY,
                target_id="worker_node_b",
                value={"type": "node", "attributes": {"cpu_usage": 10}, "tags": ["spawned"]}
            ),
        ]
    )

    report, modified = interpreter.execute(session_id, command_batch)
    assert len(report) == 4
    assert all(entry["status"] == "success" for entry in report)

    mod_map = {ent.id: ent for ent in modified}
    assert mod_map["worker_node_a"].attributes["cpu_usage"] == 80
    assert "load_balanced" in mod_map["worker_node_a"].tags
    assert "legacy" not in mod_map["worker_node_a"].tags
    assert mod_map["worker_node_b"].attributes["cpu_usage"] == 10


# =====================================================================
# 3. LlmRpcSchemaEnforcer (자가 교정 루프 및 서킷 브레이커) 검증
# =====================================================================
@patch("core_engine.vm.lrse_enforcer.genai.Client")
def test_enforcer_self_correction_and_dynamic_schema(mock_client_cls: MagicMock) -> None:
    mock_client = mock_client_cls.return_value

    # 1차 시도: 잘못된 JSON 반환 -> 2차 시도: 정상 JSON 반환 (자가 교정 재시도 검증)
    invalid_resp = MagicMock()
    invalid_resp.text = "not_a_valid_json_response"
    invalid_resp.usage_metadata = MagicMock(prompt_token_count=40, candidates_token_count=10)

    valid_resp = MagicMock()
    valid_resp.text = json.dumps({
        "extracted_name": "Alpha Team",
        "sentiment": "POSITIVE",
        "confidence_score": 0.95
    })
    valid_resp.usage_metadata = MagicMock(prompt_token_count=60, candidates_token_count=25)

    mock_client.models.generate_content.side_effect = [invalid_resp, valid_resp]

    dynamic_schema: Dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "extracted_name": {"type": "string"},
            "sentiment": {"type": "string", "enum": ["POSITIVE", "NEGATIVE", "NEUTRAL"]},
            "confidence_score": {"type": "number"}
        },
        "required": ["extracted_name", "sentiment", "confidence_score"],
        "additionalProperties": False
    }

    enforcer = LlmRpcSchemaEnforcer(api_key="mock_api_key")
    with patch("time.sleep"):
        result, meta = enforcer.call_rpc(
            context_payload="Alpha Team negotiation succeeded.",
            response_schema=dynamic_schema,
            max_retries=3
        )

    assert isinstance(result, dict)
    assert result["extracted_name"] == "Alpha Team"
    assert meta.retry_count == 1
    assert meta.total_tokens == 135


@patch("core_engine.vm.lrse_enforcer.genai.Client")
def test_enforcer_circuit_breaker_token_limit(mock_client_cls: MagicMock) -> None:
    mock_client = mock_client_cls.return_value

    oversized_resp = MagicMock()
    oversized_resp.text = '{"commands": []}'
    oversized_resp.usage_metadata = MagicMock(prompt_token_count=15000, candidates_token_count=8000)
    mock_client.models.generate_content.return_value = oversized_resp

    enforcer = LlmRpcSchemaEnforcer(api_key="mock_api_key")
    with pytest.raises(RpcEnforcementError, match="Circuit Breaker Abort"):
        enforcer.call_rpc(
            context_payload="Trigger token limit",
            response_schema=StructuredCommand,
            max_cumulative_tokens=20000
        )