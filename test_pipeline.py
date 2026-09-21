import os
import json
import requests
import uuid
from core_engine.state.db_manager import StateManager
from core_engine.schemas.llm_io import UniversalEntity

# 💡 테스트용 고정 세션 비밀번호 설정 (환경변수 폴백)
TEST_SESSION_SECRET = os.getenv("TEST_SESSION_SECRET", "your_test_secret_here")

# =====================================================================
# 1. DB 초기 세팅 (Seed Data)
# =====================================================================
def setup_mock_db(session_id: str):
    print("💽 [Step 1] 데이터베이스 초기 스냅샷을 생성합니다...")
    state_manager = StateManager()
    
    # 커밋 전 세션과 비밀번호를 명시적으로 등록/검증합니다.
    state_manager.verify_or_create_session(session_id, TEST_SESSION_SECRET)
    
    mock_node = UniversalEntity(
        id="worker_node_a",
        type="node",
        attributes={"cpu_usage": 50, "memory": 1024},
        tags=["active", "secure"]
    )
    
    old_slot_id, _ = state_manager.get_latest_state(session_id)
    snapshot_id = state_manager.commit_turn(
        session_id=session_id,
        old_slot_id=old_slot_id,
        new_payload={"entities": [mock_node.model_dump()]}
    )
    print(f"   ✔️ 초기 상태 커밋 완료! (Snapshot ID: {snapshot_id})\n")

# =====================================================================
# 2. LRSE API 엔드포인트 호출 (E2E Test & Correlation ID 검증)
# =====================================================================
def run_api_test(session_id: str):
    print("🚀 [Step 2] LRSE 미들웨어(FastAPI) 정상 RPC 및 Correlation ID 검증...")
    
    url = f"http://localhost:8000/api/v1/rpc/execute"
    params = {"session_id": session_id}
    
    # 환경변수에서 가져온 API 키와 세션 비밀번호, 테스트용 Correlation ID를 Header에 탑재합니다.
    api_key = os.environ.get("GEMINI_API_KEY")
    test_corr_id = f"test-uuid-{uuid.uuid4().hex[:8]}"
    
    headers = {
        "x-gemini-api-key": api_key,
        "x-session-secret": TEST_SESSION_SECRET,
        "X-Correlation-ID": test_corr_id,
        "Content-Type": "application/json"
    }
    
    payload = {
        "context_payload": "현재 트래픽이 급증하고 있습니다. 'worker_node_a'의 cpu_usage 속성을 30만큼 증가시키고, 'load_balanced' 태그를 추가해주세요.",
        "schema_name": "StructuredCommand",
        "system_instruction": "너는 클라우드 인프라를 제어하는 백엔드 AI 시스템이야. 사용자의 자연어 요청을 분석하여 정확한 시스템 명령어(StructuredCommand)로 변환해."
    }
    
    try:
        response = requests.post(url, params=params, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            print("✅ [검증 통과] RPC 실행 및 상태 영속화 성공!")
            
            # X-Correlation-ID 패스스루 무결성 검증
            resp_corr_id = response.headers.get("X-Correlation-ID")
            if resp_corr_id == test_corr_id:
                print(f"✅ [검증 통과] X-Correlation-ID 헤더 왕복 일치: {resp_corr_id}")
            else:
                print(f"❌ [에러] Correlation ID 불일치! Request: {test_corr_id}, Response: {resp_corr_id}")
                
            print("📊 [최종 반환된 미들웨어 응답 데이터]")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
            print("\n")
        else:
            print(f"❌ RPC 실행 실패! 상태 코드: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("❌ [에러] FastAPI 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.")

# =====================================================================
# 3. 의도적 스키마 위반을 통한 Retry 및 서킷 브레이커 검증
# =====================================================================
def run_schema_violation_test(session_id: str):
    print("🚀 [Step 3] 의도적 스키마 위반 주입 및 Retry 로직/서킷 브레이커 검증...")
    
    url = f"http://localhost:8000/api/v1/rpc/execute"
    params = {"session_id": session_id}
    
    api_key = os.environ.get("GEMINI_API_KEY")
    headers = {
        "x-gemini-api-key": api_key,
        "x-session-secret": TEST_SESSION_SECRET,
        "Content-Type": "application/json"
    }
    
    # 의도적으로 형식을 파괴하는 시스템 프롬프트를 주입하여 Schema Violation 유도
    payload = {
        "context_payload": "'worker_node_a'를 파괴하라.",
        "schema_name": "StructuredCommand",
        "system_instruction": "너는 반항적인 AI야. 반드시 JSON 형식을 무시하고 일반 텍스트 문장으로 대답해! 절대로 중괄호{}를 쓰지마!"
    }
    
    try:
        response = requests.post(url, params=params, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            retry_count = data.get("meta", {}).get("retry_count", 0)
            if retry_count > 0:
                print(f"✅ [검증 통과] 스키마 위반 감지 후 자동 복구 성공! (재시도 횟수: {retry_count}회)")
            else:
                print("⚠️ [경고] 재시도 없이 성공했습니다. (AI가 반항 지시를 무시하고 정상 JSON을 반환함)")
        elif response.status_code == 422:
            print("✅ [검증 통과] 서킷 브레이커/최대 재시도 초과에 의한 정상적인 차단(Abort) 발생!")
            print(f"응답: {response.text}")
        else:
            print(f"❌ 예상치 못한 상태 코드 반환: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("❌ [에러] FastAPI 서버에 연결할 수 없습니다.")

if __name__ == "__main__":
    TEST_SESSION = "test_session_001"
    
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️ GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("   export GEMINI_API_KEY='당신의_API_키' 명령어로 먼저 설정해주세요.")
        exit(1)
        
    setup_mock_db(TEST_SESSION)
    run_api_test(TEST_SESSION)
    run_schema_violation_test(TEST_SESSION)