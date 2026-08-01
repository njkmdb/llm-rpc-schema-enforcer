# LRSE (LLM RPC Schema Enforcer) v0.1.0

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/njkmdb/llm-rpc-schema-enforcer)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)

> **"LLM 호출을 스키마 기반의 백엔드 RPC로 취급하여, AI의 비결정론적 출력을 규격화된 JSON 데이터로 변환하는 미들웨어"**

**LLM RPC Schema Enforcer (LRSE)**는 대형 언어 모델(LLM)의 비결정론적 출력과 환각(Hallucination) 현상을 제어하기 위해 설계된 백엔드 미들웨어입니다. 클라이언트 애플리케이션과 분리된 원격 프로시저 호출(RPC) 서버 형태로 동작합니다.

## 핵심 아키텍처 철학 (Core Philosophy)

* **결정론적 출력 제어:** Pydantic 스키마를 통해 출력 형식을 정의합니다. 모델 온도(Temperature)를 0.0으로 고정하여 일관된 결과를 유도합니다.
* **클라이언트 분리 (Client Decoupling):** 클라이언트 애플리케이션은 프롬프트 엔지니어링이나 LLM SDK를 직접 구현할 필요가 없습니다. 필요한 데이터 스키마(JSON)와 컨텍스트 페이로드만 API로 전달하여 결과를 수신합니다.
* **무상태 처리 (Stateless Processing):** 내부 VM 인터프리터는 데이터베이스(영속성 계층)를 직접 수정하지 않습니다. 메모리 상에서 순수 함수(Pure Function) 형태로 트랜잭션을 처리하여 원자성(Atomicity)을 유지합니다.
* **BYOK 및 세션 격리 (Secure Multi-tenancy):** 클라이언트가 HTTP 헤더를 통해 개인 API 키와 세션 비밀번호를 직접 지참(BYOK)하게 하여 완벽한 테넌트 격리를 구현합니다.
* **오류 복구 및 재시도:** LLM의 출력이 스키마 규격을 위반할 경우, 오류 내역을 프롬프트에 포함하여 재요청합니다. 이를 통해 시스템 중단을 방지하고 유효한 데이터 출력을 유도합니다.

---

## 주요 기능 (Key Features)

### 1. 스키마 기반 출력 제어 (Schema Enforcement)
서버 레지스트리에 등록된 Pydantic 모델에서 JSON Schema 명세를 추출하여 LLM에 전달합니다. 반환되는 데이터가 사전에 정의된 JSON 규격을 준수하도록 관리합니다.

### 2. 범용 RPC 라우터 (RPC Gateway)
FastAPI 기반의 API 게이트웨이를 제공합니다. 다양한 클라이언트 앱은 도메인 스키마 이름과 컨텍스트만으로 AI 추론 결과를 요청할 수 있습니다.

### 3. 자동 재시도 로직 (Retry Loop)
Pydantic 검증 실패(`ValidationError`) 발생 시, 빈 데이터를 반환하는 대신 에러 로그를 LLM에 피드백합니다. 최대 3회까지 데이터를 다시 생성하도록 요청하여 구조를 교정합니다.

### 4. Append-Only 상태 관리 (State Manager)
데이터를 직접 덮어쓰기(UPDATE)하지 않고, 전체 스냅샷 복제 후 포인터를 변경합니다. 다중 버전 동시성 제어(MVCC) 방식을 사용하여 상태를 안전하게 관리합니다.

---

## 프로젝트 구조 (Directory Structure)

```text
llm-rpc-schema-enforcer/
├── core_engine/                 # 무상태 백엔드 코어 시스템 (LRSE 미들웨어)
│   ├── api/                     # FastAPI 게이트웨 및 RPC 라우터 (`main.py`)
│   ├── schemas/                 # Pydantic V2 데이터 검증 및 클라이언트 스키마 레지스트리 (`api_models.py`, `llm_io.py`)
│   ├── state/                   # SQLite 기반 Append-Only 영속성 계층 (`db_manager.py`)
│   └── vm/                      # AI 프롬프트 어댑터 및 스키마 검증 코어 모듈 (`lrse_enforcer.py`, `interpreter.py`)
├── scripts/                     # DB 초기화 및 상태 점검을 위한 CLI 유틸리티 (`init_db.py`, `check_db.py`)
├── test_pipeline.py             # E2E 파이프라인 검증 테스트 스크립트
└── README.md