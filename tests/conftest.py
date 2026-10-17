from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core_engine.schemas.llm_io import UniversalEntity
from core_engine.state.db_manager import StateManager


@dataclass(frozen=True)
class SeedScenario:
    """테스트 시나리오용 불변(Immutable) 시드 데이터 컨테이너"""
    session_id: str
    session_secret: str
    entities: List[Dict[str, Any]]


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """각 테스트 함수마다 완벽히 격리된 임시 SQLite 파일 경로를 반환합니다."""
    return str(tmp_path / "isolated_lrse_test.db")


@pytest.fixture
def seeded_state_manager(temp_db_path: str) -> StateManager:
    """기본 인프라 노드(worker_node_a, worker_node_b)가 사전 적재된 StateManager 픽스처"""
    manager = StateManager(db_path=temp_db_path)
    session_id = "default_seeded_session"
    secret = "seeded_secret_key_999"

    manager.verify_or_create_session(session_id, secret)
    initial_entities = [
        UniversalEntity(
            id="worker_node_a",
            type="compute_node",
            attributes={"cpu_usage": 45, "memory_mb": 2048, "region": "ap-northeast-1"},
            tags=["active", "production"]
        ).model_dump(),
        UniversalEntity(
            id="worker_node_b",
            type="compute_node",
            attributes={"cpu_usage": 15, "memory_mb": 1024, "region": "ap-northeast-1"},
            tags=["standby"]
        ).model_dump(),
    ]
    manager.commit_turn(
        session_id=session_id,
        old_slot_id=None,
        new_payload={"entities": initial_entities}
    )
    return manager