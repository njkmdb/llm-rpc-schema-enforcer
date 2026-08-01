import os
import json
import requests
from core_engine.state.db_manager import StateManager
from core_engine.schemas.llm_io import UniversalEntity

# 💡 테스트용 고정 세션 비밀번호 설정
TEST_SESSION_SECRET = "my_super_secret_password_123!"

# =====================================================================
# 1. DB 초기 세팅 (Seed Data)
# =====================================================================
def setup_mock_db(session_id: str):
    print("💽 [Step 1] 데이터베이스 초기 스냅샷을 생성합니다...")
    state_manager = StateManager()
    
    # 💡 [수정됨] 커밋 전 세션과 비밀번호를 명시적으로 등록/검증합니다.
    state_manager.verify_or_create_session(session_id, TEST_SESSION_SECRET)
    
    mock_node = UniversalEntity(
        id="worker_node_a",
        type="node",
        attributes={"cpu_usage": 50, "memory": 1024},
        tags=["active", "secure"]
    )
    
    snapshot_id = state_manager.commit_turn(
        session_id=session_id,
        active_entities=[mock_node]
    )
    print(f"   ✔️ 초기 상태 커밋 완료! (Snapshot ID: {snapshot_id})\n")

# =====================================================================
# 2. LRSE API 엔드포인트 호출 (E2E Test)
# =====================================================================
def run_api_test(session_id: str):
    print("🚀 [Step 2] LRSE 미들웨어(FastAPI)에 LLM RPC 요청을 전송합니다...")
    
    url = f"http://localhost:8000/api/v1/rpc/execute"
    params = {"session_id": session_id}
    
    # 💡 [수정됨] 환경변수에서 가져온 API 키와 세션 비밀번호를 Header에 탑재합니다.
    api_key = os.environ.get("GEMINI_API_KEY")
    headers = {
        "x-gemini-api-key": api_key,
        "x-session-secret": TEST_SESSION_SECRET,
        "Content-Type": "application/json"
    }
    
    payload = {
        "context_payload": "현재 트래픽이 급증하고 있습니다. 'worker_node_a'의 cpu_usage 속성을 30만큼 증가시키고, 'load_balanced' 태그를 추가해주세요.",
        "schema_name": "StructuredCommand",
        "system_instruction": "너는 클라우드 인프라를 제어하는 백엔드 AI 시스템이야. 사용자의 자연어 요청을 분석하여 정확한 시스템 명령어(StructuredCommand)로 변환해."
    }
    
    try:
        # headers 속성 추가
        response = requests.post(url, params=params, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            print("✅ [Step 3] RPC 실행 및 상태 영속화 성공!\n")
            print("📊 [최종 반환된 미들웨어 응답 데이터]")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print(f"❌ RPC 실행 실패! 상태 코드: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("❌ [에러] FastAPI 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.")

if __name__ == "__main__":
    TEST_SESSION = "test_session_001"
    
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️ GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("   export GEMINI_API_KEY='당신의_API_키' 명령어로 먼저 설정해주세요.")
        exit(1)
        
    setup_mock_db(TEST_SESSION)
    run_api_test(TEST_SESSION)