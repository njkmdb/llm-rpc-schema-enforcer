import os
import json
import requests

# 💡 테스트용 고정 세션 비밀번호 설정 (환경변수 폴백)
TEST_SESSION_SECRET = os.getenv("TEST_SESSION_SECRET", "your_test_secret_here")

# =====================================================================
# 1. LRSE API 엔드포인트 호출 (Dynamic Schema E2E Test)
# =====================================================================
def run_dynamic_api_test(session_id: str):
    print("🚀 [Step 1] LRSE 미들웨어(FastAPI)에 동적 스키마(Dynamic Schema) 기반 LLM RPC 요청을 전송합니다...")
    
    url = "http://localhost:8000/api/v1/rpc/call"
    params = {"session_id": session_id}
    
    # 환경변수에서 가져온 API 키와 세션 비밀번호를 Header에 탑재합니다.
    api_key = os.environ.get("GEMINI_API_KEY")
    headers = {
        "x-gemini-api-key": api_key,
        "x-session-secret": TEST_SESSION_SECRET,
        "Content-Type": "application/json"
    }
    
    # 💡 런타임에 동적으로 주입할 JSON Schema 구조체 (Dict)
    dynamic_schema = {
        "type": "object",
        "properties": {
            "extracted_name": {
                "type": "string",
                "description": "텍스트에서 추출된 주요 엔티티의 이름"
            },
            "sentiment": {
                "type": "string",
                "enum": ["POSITIVE", "NEGATIVE", "NEUTRAL"],
                "description": "텍스트의 전반적인 비즈니스 감정 상태"
            },
            "confidence_score": {
                "type": "number",
                "description": "AI 추론에 대한 확신도 (0.0 ~ 1.0)"
            }
        },
        "required": ["extracted_name", "sentiment", "confidence_score"],
        "additionalProperties": False
    }
    
    # DB 시드 주입(/init) 과정 없이 곧바로 rpc/call 엔드포인트에 동적 스키마를 얹어 호출합니다.
    payload = {
        "context_payload": "오늘 알파팀과의 협상은 매우 성공적이었다. 단가 조정도 우리의 요구사항대로 원활하게 이루어졌다.",
        "schema_name": None,  # 정적 레지스트리 스키마 이름은 사용하지 않음
        "dynamic_schema_definition": dynamic_schema,
        "system_instruction": "너는 비즈니스 로그를 분석하는 AI야. 텍스트에서 주요 엔티티 이름과 감정을 분석해서 지정된 JSON 스키마로 반환해."
    }
    
    try:
        response = requests.post(url, params=params, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            print("✅ [Step 2] 동적 스키마 주입 기반 RPC 실행 및 데이터 검증 성공!\n")
            print("📊 [최종 반환된 미들웨어 응답 데이터]")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print(f"❌ RPC 실행 실패! 상태 코드: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("❌ [에러] FastAPI 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.")

if __name__ == "__main__":
    TEST_SESSION = "dynamic_test_session_999"
    
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️ GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("   export GEMINI_API_KEY='당신의_API_키' 명령어로 먼저 설정해주세요.")
        exit(1)
        
    run_dynamic_api_test(TEST_SESSION)