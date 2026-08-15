"""
[LRSE State Manager]
SQLite 기반의 Append-only 상태 관리 및 낙관적 락(Optimistic Locking) 모듈입니다.
상태를 직접 덮어쓰지 않고 새로운 상태 슬롯(Slot)을 추가한 뒤, 
세션의 메타데이터 포인터를 원자적으로 이동시켜 동시성 충돌을 방어합니다.
"""

import sqlite3
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("LRSE_DB_Manager")
logger.setLevel(logging.INFO)

class ConcurrencyConflictError(Exception):
    """
    낙관적 락 충돌 예외.
    동일한 세션에 대해 동시 요청이 발생하여 상태 스냅샷이 이미 변경되었을 때 발생합니다.
    """
    pass

class StateManager:
    def __init__(self, db_path: str = "lrse_state.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        # 멀티스레드 환경(FastAPI)에서 안전하게 사용하기 위해 check_same_thread=False 설정
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """세션 메타데이터와 상태 슬롯 테이블을 초기화합니다."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # [수정됨] session_secret 컬럼 추가
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_metadata (
                    session_id TEXT PRIMARY KEY,
                    session_secret TEXT,
                    current_slot_id TEXT,
                    updated_at TIMESTAMP
                )
            """)
            # 실제 상태 데이터(페이로드)가 Append-only로 쌓이는 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS state_slots (
                    slot_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    payload TEXT,
                    created_at TIMESTAMP
                )
            """)
            conn.commit()

    def verify_or_create_session(self, session_id: str, session_secret: str) -> bool:
        """
        [수정됨] 세션을 검증하거나 새로 생성합니다. 
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT session_secret FROM session_metadata WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            
            if row:
                # 이미 존재하는 세션이면 시크릿 키 검증
                return row["session_secret"] == session_secret
            else:
                # 존재하지 않으면 신규 생성 (current_slot_id는 초기 상태이므로 비워둠)
                now = datetime.now().isoformat()
                cursor.execute(
                    "INSERT INTO session_metadata (session_id, session_secret, updated_at) VALUES (?, ?, ?)",
                    (session_id, session_secret, now)
                )
                conn.commit()
                return True

    def get_latest_state(self, session_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        특정 세션의 가장 최신 슬롯 ID와 상태 데이터를 반환합니다.
        세션이 없으면 (None, None)을 반환합니다.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_slot_id FROM session_metadata WHERE session_id = ?", 
                (session_id,)
            )
            row = cursor.fetchone()
            
            if not row or not row["current_slot_id"]:
                return None, None
                
            current_slot_id = row["current_slot_id"]
            
            cursor.execute(
                "SELECT payload FROM state_slots WHERE slot_id = ?", 
                (current_slot_id,)
            )
            slot_row = cursor.fetchone()
            
            if slot_row:
                return current_slot_id, json.loads(slot_row["payload"])
            return current_slot_id, None

    def get_entity(self, session_id: str, entity_id: str) -> Optional[Any]:
        """
        특정 세션의 최신 상태에서 단일 엔티티를 검색하여 반환하는 헬퍼 메서드입니다.
        데이터베이스 스키마 특성상 전체 페이로드를 가져온 뒤 메모리에서 필터링합니다.
        """
        from core_engine.schemas.llm_io import UniversalEntity
        
        _, current_state = self.get_latest_state(session_id)
        
        if not current_state or "entities" not in current_state:
            return None
            
        for ent_dict in current_state["entities"]:
            if ent_dict.get("id") == entity_id:
                return UniversalEntity(**ent_dict)
                
        return None

    def commit_turn(self, session_id: str, old_slot_id: Optional[str], new_payload: Dict[str, Any]) -> str:
        """
        새로운 상태를 Append하고 포인터를 업데이트합니다.
        낙관적 락(Optimistic Locking)을 적용하여 동시성 충돌(Race Condition)을 방어합니다.
        """
        new_slot_id = f"slot_{uuid.uuid4().hex}"
        now = datetime.now().isoformat()
        payload_str = json.dumps(new_payload, ensure_ascii=False)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 1. 새 슬롯은 충돌 없이 Append-only로 삽입
                cursor.execute(
                    "INSERT INTO state_slots (slot_id, session_id, payload, created_at) VALUES (?, ?, ?, ?)",
                    (new_slot_id, session_id, payload_str, now)
                )

                # 2. 포인터 업데이트 및 낙관적 락 검증
                if old_slot_id is None:
                    # [수정됨] 세션이 verify_or_create_session에서 먼저 생성되므로 INSERT가 아닌 UPDATE 처리
                    cursor.execute("""
                        UPDATE session_metadata 
                        SET current_slot_id = ?, updated_at = ? 
                        WHERE session_id = ? AND current_slot_id IS NULL
                    """, (new_slot_id, now, session_id))
                    
                    if cursor.rowcount == 0:
                        raise ConcurrencyConflictError(f"데이터 충돌! 세션 '{session_id}'에 이미 초기 상태가 존재하거나 세션이 없습니다.")
                else:
                    # [핵심 방어 로직] 기존 slot_id가 일치할 때만 업데이트 수행 (Optimistic Lock)
                    cursor.execute("""
                        UPDATE session_metadata 
                        SET current_slot_id = ?, updated_at = ? 
                        WHERE session_id = ? AND current_slot_id = ?
                    """, (new_slot_id, now, session_id, old_slot_id))
                    
                    if cursor.rowcount == 0:
                        # 0개의 row가 업데이트되었다면, 누군가 이미 current_slot_id를 변경했다는 뜻
                        raise ConcurrencyConflictError(
                            f"데이터 충돌(Race Condition) 감지! 세션 '{session_id}'의 상태가 다른 프로세스에 의해 이미 변경되었습니다. "
                            f"(Expected old_slot_id: {old_slot_id})"
                        )
                
                conn.commit()
                logger.info(f"✅ [DB Commit] 세션 '{session_id}' 상태 업데이트 완료 ({old_slot_id} -> {new_slot_id})")
                return new_slot_id
                
            except ConcurrencyConflictError as cce:
                # 충돌 발생 시 롤백 (방금 넣은 state_slots 데이터도 무효화)
                conn.rollback()
                logger.error(f"❌ [DB Concurrency Error] {cce}")
                raise
            except Exception as e:
                conn.rollback()
                logger.error(f"❌ [DB System Error] 상태 커밋 중 치명적 오류 발생: {e}")
                raise