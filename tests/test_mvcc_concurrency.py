from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3
import threading
from typing import List, Tuple

import pytest

from core_engine.state.db_manager import ConcurrencyConflictError, StateManager


def test_multithreaded_optimistic_lock_race_condition(seeded_state_manager: StateManager) -> None:
    """
    8개의 동시 스레드가 동일한 old_slot_id를 기반으로 동시에 commit_turn을 호출할 때,
    정확히 1개의 스레드만 커밋에 성공하고 나머지 7개는 ConcurrencyConflictError로 차단되는지 검증합니다.
    """
    session_id = "default_seeded_session"
    initial_slot_id, _ = seeded_state_manager.get_latest_state(session_id)
    assert initial_slot_id is not None

    num_workers = 8
    barrier = threading.Barrier(num_workers)

    def attempt_concurrent_commit(worker_idx: int) -> Tuple[int, str]:
        # 모든 워커 스레드가 준비될 때까지 대기했다가 동시에 커밋 시도 (극한의 Race Condition 유도)
        barrier.wait(timeout=5.0)
        new_slot = seeded_state_manager.commit_turn(
            session_id=session_id,
            old_slot_id=initial_slot_id,
            new_payload={"entities": [{"id": f"worker_winner_{worker_idx}", "type": "node"}]},
        )
        return worker_idx, new_slot

    success_results: List[Tuple[int, str]] = []
    conflict_errors: List[ConcurrencyConflictError] = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(attempt_concurrent_commit, i) for i in range(num_workers)]
        for future in as_completed(futures):
            try:
                res = future.result()
                success_results.append(res)
            except ConcurrencyConflictError as cce:
                conflict_errors.append(cce)

    # 낙관적 락에 의해 정확히 1건만 성공하고 나머지(7건)는 충돌 예외가 발생해야 함
    assert len(success_results) == 1
    assert len(conflict_errors) == num_workers - 1

    winning_worker, winning_slot_id = success_results[0]
    latest_slot_id, latest_state = seeded_state_manager.get_latest_state(session_id)
    assert latest_slot_id == winning_slot_id
    assert latest_state is not None
    assert latest_state["entities"][0]["id"] == f"worker_winner_{winning_worker}"


def test_append_only_mvcc_snapshot_history_preservation(seeded_state_manager: StateManager) -> None:
    """
    다중 턴(Turn)이 진행되더라도 기존 state_slots 레코드가 덮어써지지 않고
    Append-Only 형태로 모든 스냅샷 버전이 보존되는지 검증합니다.
    """
    session_id = "default_seeded_session"
    recorded_slots: List[str] = []

    current_slot, _ = seeded_state_manager.get_latest_state(session_id)
    assert current_slot is not None
    recorded_slots.append(current_slot)

    for turn_idx in range(1, 6):
        next_slot = seeded_state_manager.commit_turn(
            session_id=session_id,
            old_slot_id=current_slot,
            new_payload={"entities": [{"id": "worker_node_a", "turn": turn_idx}]},
        )
        recorded_slots.append(next_slot)
        current_slot = next_slot

    # 총 6개의 고유 슬롯 ID가 생성되었는지 확인
    assert len(set(recorded_slots)) == 6

    # SQLite state_slots 테이블에 6개의 과거 스냅샷이 모두 보존되어 있는지 검증
    with sqlite3.connect(seeded_state_manager.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM state_slots WHERE session_id = ?",
            (session_id,),
        )
        total_snapshots = cursor.fetchone()[0]

    assert total_snapshots == 6