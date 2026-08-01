import sqlite3
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict
from core_engine.schemas.llm_io import UniversalEntity

class StateManager:
    def __init__(self, db_path: str = "core_state.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        query = """
        -- 1. 포인터 스왑 메타데이터 테이블 (세션 기반 워크스페이스 관리 및 보안 추가)
        CREATE TABLE IF NOT EXISTS session_metadata (
            session_id TEXT PRIMARY KEY,
            session_secret TEXT NOT NULL,
            current_physical_slot_id TEXT,
            updated_at TIMESTAMP
        );

        -- 2. 불변의 엔티티 데이터 테이블 (Append-Only)
        CREATE TABLE IF NOT EXISTS universal_entities (
            physical_slot_id TEXT NOT NULL,
            id TEXT NOT NULL,
            type TEXT NOT NULL,
            attributes TEXT NOT NULL,
            tags TEXT NOT NULL,
            PRIMARY KEY (physical_slot_id, id)
        );
        """
        with self._get_connection() as conn:
            conn.executescript(query)

    def verify_or_create_session(self, session_id: str, session_secret: str) -> bool:
        """
        세션이 존재하면 비밀번호를 검증하고, 존재하지 않으면 새 세션을 생성합니다.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT session_secret FROM session_metadata WHERE session_id = ?', (session_id,))
            row = cursor.fetchone()
            
            if row:
                # 기존 세션인 경우 비밀번호 일치 여부 반환
                return row['session_secret'] == session_secret
            else:
                # 새 세션 생성
                now = datetime.now()
                cursor.execute('''
                    INSERT INTO session_metadata (session_id, session_secret, updated_at)
                    VALUES (?, ?, ?)
                ''', (session_id, session_secret, now))
                conn.commit()
                return True

    def get_entity(self, session_id: str, entity_id: str) -> Optional[UniversalEntity]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT current_physical_slot_id 
                FROM session_metadata 
                WHERE session_id = ?
            ''', (session_id,))
            row = cursor.fetchone()
            
            if not row or not row['current_physical_slot_id']:
                return None
                
            physical_slot_id = row['current_physical_slot_id']
            
            cursor.execute('''
                SELECT id, type, attributes, tags 
                FROM universal_entities 
                WHERE physical_slot_id = ? AND id = ?
            ''', (physical_slot_id, entity_id))
            
            ent_row = cursor.fetchone()
            if ent_row:
                return UniversalEntity(
                    id=ent_row['id'],
                    type=ent_row['type'],
                    attributes=json.loads(ent_row['attributes']),
                    tags=json.loads(ent_row['tags'])
                )
            return None
        finally:
            conn.close()

    def commit_turn(self, session_id: str, active_entities: List[UniversalEntity]) -> str:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # 1. 이전 스냅샷(Slot)의 ID 가져오기
            cursor.execute('''
                SELECT current_physical_slot_id 
                FROM session_metadata 
                WHERE session_id = ?
            ''', (session_id,))
            row = cursor.fetchone()
            
            if not row:
                raise ValueError(f"세션 {session_id}가 존재하지 않습니다. 인증을 먼저 진행하세요.")
                
            old_slot_id = row['current_physical_slot_id']

            # 2. 이전 스냅샷의 전체 엔티티를 불러와 딕셔너리로 구성 (베이스라인)
            current_state: Dict[str, UniversalEntity] = {}
            if old_slot_id:
                cursor.execute('''
                    SELECT id, type, attributes, tags 
                    FROM universal_entities 
                    WHERE physical_slot_id = ?
                ''', (old_slot_id,))
                for ent_row in cursor.fetchall():
                    current_state[ent_row['id']] = UniversalEntity(
                        id=ent_row['id'],
                        type=ent_row['type'],
                        attributes=json.loads(ent_row['attributes']),
                        tags=json.loads(ent_row['tags'])
                    )

            # 3. 이번 턴에 변경/생성된 엔티티(active_entities)를 베이스라인에 덮어쓰기(Merge)
            for modified_ent in active_entities:
                current_state[modified_ent.id] = modified_ent

            # 4. 병합된 전체 상태를 새로운 물리 슬롯에 Append-Only로 INSERT
            new_physical_id = str(uuid.uuid4())
            now = datetime.now()
            
            for ent in current_state.values():
                conn.execute('''
                    INSERT INTO universal_entities (physical_slot_id, id, type, attributes, tags)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    new_physical_id, ent.id, ent.type,
                    json.dumps(ent.attributes), json.dumps(ent.tags)
                ))
            
            # 5. 세션의 포인터를 새 슬롯으로 이동 (이미 존재하는 세션이므로 UPDATE 수행)
            conn.execute('''
                UPDATE session_metadata 
                SET current_physical_slot_id = ?, updated_at = ?
                WHERE session_id = ?
            ''', (new_physical_id, now, session_id))
            
            conn.commit()
            return new_physical_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()