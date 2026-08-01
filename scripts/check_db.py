import json
import sys
import os
import argparse
import getpass

# 현재 스크립트의 부모 디렉토리(프로젝트 루트)를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core_engine.state.db_manager import StateManager

def main():
    parser = argparse.ArgumentParser(description="LRSE 데이터베이스 엔티티 조회 도구")
    parser.add_argument("-s", "--session", required=True, help="조회할 세션 ID")
    parser.add_argument("-t", "--target", required=True, help="조회할 대상 엔티티 ID")
    parser.add_argument("-p", "--secret", help="세션 비밀번호 (생략 시 프롬프트에서 안전하게 입력)")
    
    args = parser.parse_args()
    
    session_id = args.session
    target_entity_id = args.target
    
    # 💡 비밀번호 결정 로직: 1. 파라미터 -> 2. 환경변수 -> 3. 대화형 입력(getpass)
    secret = args.secret or os.environ.get("LRSE_SESSION_SECRET")
    if not secret:
        # 터미널에 타이핑하는 비밀번호가 노출되지 않도록 처리
        secret = getpass.getpass(prompt=f"🔑 [{session_id}] 세션 비밀번호를 입력하세요: ")

    state_manager = StateManager()
    
    print(f"\n🔐 [{session_id}] 세션 인증 및 데이터 조회를 시작합니다...")
    
    # 세션 인증 (session_metadata에서 secret 검증)
    is_authenticated = state_manager.verify_or_create_session(session_id, secret) 
    
    if not is_authenticated:
        print("❌ 인증 실패: 세션 ID 또는 패스워드가 일치하지 않습니다.")
        sys.exit(1)

    print("✅ 인증 성공! 데이터를 불러옵니다...\n")
    
    # 데이터 조회
    entity = state_manager.get_entity(session_id, target_entity_id)
    
    if entity:
        print(json.dumps(entity.model_dump(), indent=2, ensure_ascii=False))
    else:
        print(f"❌ 해당 세션에서 '{target_entity_id}' 데이터를 찾을 수 없습니다.")

if __name__ == "__main__":
    main()