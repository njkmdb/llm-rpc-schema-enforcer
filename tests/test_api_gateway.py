from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core_engine.api.main import app, get_llm_enforcer, state_manager
from core_engine.schemas.api_models import LlmRpcMetaData
from core_engine.schemas.llm_io import ActionType, Command, StructuredCommand


@pytest.fixture(autouse=True)
def isolate_gateway_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """모든 API 테스트마다 독립된 임시 SQLite DB를 사용하도록 격리"""
    test_db = tmp_path / "gateway_test.db"
    monkeypatch.setattr(state_manager, "db_path", str(test_db))
    state_manager._init_db()
    yield
    app.dependency_overrides.clear()


def test_session_init_and_correlation_id_passthrough() -> None:
    client = TestClient(app)
    custom_corr_id = "corr-trace-999"

    response = client.post(
        "/api/v1/session/init",
        headers={"X-Correlation-ID": custom_corr_id},
        json={
            "session_id": "gw_session_01",
            "session_secret": "gw_secret_01",
            "custom_seed": [
                {
                    "id": "worker_node_a",
                    "type": "node",
                    "attributes": {"cpu_usage": 50},
                    "tags": ["active"]
                }
            ]
        }
    )

    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == custom_corr_id
    body = response.json()
    assert body["status"] == "success"
    assert body["snapshot_id"].startswith("slot_")


def test_stateless_rpc_call_with_dynamic_schema() -> None:
    mock_enforcer = MagicMock()
    mock_enforcer.call_rpc.return_value = (
        {"extracted_name": "Alpha", "sentiment": "POSITIVE", "confidence_score": 0.99},
        LlmRpcMetaData(latency_ms=12, prompt_tokens=30, completion_tokens=15, total_tokens=45, retry_count=0)
    )
    app.dependency_overrides[get_llm_enforcer] = lambda: mock_enforcer

    client = TestClient(app)
    response = client.post(
        "/api/v1/rpc/call",
        params={"session_id": "stateless_session"},
        headers={
            "x-gemini-api-key": "dummy_key",
            "x-session-secret": "stateless_secret",
            "X-Correlation-ID": "stateless-corr-001"
        },
        json={
            "context_payload": "Alpha negotiation succeeded.",
            "schema_name": None,
            "dynamic_schema_definition": {
                "type": "object",
                "properties": {"extracted_name": {"type": "string"}},
                "required": ["extracted_name"]
            },
            "system_instruction": "Extract entity."
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["validated_data"]["extracted_name"] == "Alpha"
    assert data["meta"]["correlation_id"] == "stateless-corr-001"


def test_stateful_rpc_execute_merges_entities() -> None:
    mock_enforcer = MagicMock()
    mock_enforcer.call_rpc.return_value = (
        StructuredCommand(
            commands=[
                Command(action=ActionType.UPDATE_ATTRIBUTE, target_id="worker_node_a", key="cpu_usage", value=25),
                Command(action=ActionType.ADD_TAG, target_id="worker_node_a", value="scaled")
            ]
        ),
        LlmRpcMetaData(latency_ms=20, prompt_tokens=50, completion_tokens=20, total_tokens=70, retry_count=0)
    )
    app.dependency_overrides[get_llm_enforcer] = lambda: mock_enforcer

    client = TestClient(app)
    # 1. 초기 시드 주입 (worker_node_a + worker_node_b)
    client.post(
        "/api/v1/session/init",
        json={
            "session_id": "exec_session",
            "session_secret": "exec_secret",
            "custom_seed": [
                {"id": "worker_node_a", "type": "node", "attributes": {"cpu_usage": 50}, "tags": ["active"]},
                {"id": "worker_node_b", "type": "node", "attributes": {"cpu_usage": 10}, "tags": ["standby"]}
            ]
        }
    )

    # 2. Stateful RPC 실행 (worker_node_a만 변이 요청)
    response = client.post(
        "/api/v1/rpc/execute",
        params={"session_id": "exec_session"},
        headers={
            "x-gemini-api-key": "dummy_key",
            "x-session-secret": "exec_secret"
        },
        json={
            "context_payload": "Increase worker_node_a cpu_usage by 25",
            "schema_name": "StructuredCommand"
        }
    )

    assert response.status_code == 200
    result = response.json()["validated_data"]
    assert result["modified_entities"][0]["attributes"]["cpu_usage"] == 75
    assert "scaled" in result["modified_entities"][0]["tags"]

    # 3. 조작하지 않은 worker_node_b도 증발하지 않고 병합(Merge) 보존되었는지 검증
    preserved_b = state_manager.get_entity("exec_session", "worker_node_b")
    assert preserved_b is not None
    assert preserved_b.attributes["cpu_usage"] == 10