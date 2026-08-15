import argparse
import sys
import os
import json

# 현재 스크립트의 부모 디렉토리(프로젝트 루트)를 sys.path에 추가하여 core_engine 모듈을 인식시킵니다.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core_engine.state.db_manager import StateManager
from core_engine.schemas.llm_io import UniversalEntity

def main():
    parser = argparse.ArgumentParser(
        description="LRSE 미들웨어 초기화 CLI 도구: 새로운 세션을 생성하거나 시드 데이터를 주입합니다."
    )
    parser.add_argument("-s", "--session", required=True, help="초기화할 세션 ID")
    parser.add_argument("-p", "--secret", required=True, help="해당 세션의 비밀번호")
    parser.add_argument("--seed", action="store_true", help="초기 인프라 엔티티(worker_node_a)를 함께 DB에 커밋합니다.")
    parser.add_argument("--custom-seed", type=str, help="JSON 형식의 커스텀 초기 데이터 주입")

    args = parser.parse_args()

    print("💽 LRSE 상태 관리자 초기화 시작...")
    state_manager = StateManager()

    # 1. 세션 및 비밀번호 등록/검증
    print(f"🔐 세션 등록 진행 중... (Session ID: {args.session})")
    is_valid = state_manager.verify_or_create_session(args.session, args.secret)
    
    if not is_valid:
        print("❌ 오류: 이미 존재하는 세션이지만, 입력한 비밀번호가 일치하지 않습니다.")
        sys.exit(1)
        
    print("✅ 세션 및 비밀번호가 성공적으로 등록/검증되었습니다.")

    # 2. 시드 데이터 주입 (옵션)
    if args.seed:
        print("🌱 초기 시드 데이터 주입 중...")
        mock_node = UniversalEntity(
            id="worker_node_a",
            type="node",
            attributes={"cpu_usage": 50, "memory": 1024},
            tags=["active", "secure"]
        )
        
        try:
            old_slot_id, _ = state_manager.get_latest_state(args.session)
            snapshot_id = state_manager.commit_turn(
                session_id=args.session,
                old_slot_id=old_slot_id,
                new_payload={"entities": [mock_node.model_dump()]}
            )
            print(f"✅ 초기 상태 커밋 완료! (Snapshot ID: {snapshot_id})")
        except Exception as e:
            print(f"❌ 시드 데이터 커밋 실패: {e}")
            sys.exit(1)

    # 3. 커스텀 시드 데이터 주입 (옵션)
    if args.custom_seed:
        print("🌱 커스텀 시드 데이터 주입 중...")
        try:
            custom_data = json.loads(args.custom_seed)
            
            # 입력 데이터가 딕셔너리 단일 객체인 경우 리스트로 감싸서 유연하게 처리
            if isinstance(custom_data, dict):
                custom_data = [custom_data]
                
            custom_entities = []
            for item in custom_data:
                custom_entity = UniversalEntity(
                    id=item.get("entity_id", item.get("id", "unknown_id")),
                    type=item.get("entity_type", item.get("type", "unknown_type")),
                    attributes=item.get("attributes", {}),
                    tags=item.get("tags", [])
                )
                custom_entities.append(custom_entity)

            old_slot_id, _ = state_manager.get_latest_state(args.session)
            snapshot_id = state_manager.commit_turn(
                session_id=args.session,
                old_slot_id=old_slot_id,
                new_payload={"entities": [ent.model_dump() for ent in custom_entities]}
            )
            print(f"✅ 커스텀 상태 커밋 완료! (Snapshot ID: {snapshot_id})")
            
        except json.JSONDecodeError:
            print("❌ 오류: --custom-seed에 전달된 데이터가 올바른 JSON 형식이 아닙니다.")
            sys.exit(1)
        except Exception as e:
            print(f"❌ 커스텀 데이터 커밋 실패: {e}")
            sys.exit(1)

    print("\n🎉 준비 완료! 이제 FastAPI 서버를 띄우고 해당 세션으로 LRSE API를 호출할 수 있습니다.")

if __name__ == "__main__":
    main()