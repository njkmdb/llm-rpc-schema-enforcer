# LRSE (LLM RPC Schema Enforcer)

| [🇺🇸 English](README.md) | [🇰🇷 한국어](README_ko.md) | [🇯🇵 日本語](README_ja.md)

![100% AI Generated](https://img.shields.io/badge/100%25_AI_Generated-8A2BE2?style=flat&logo=googlegemini&logoColor=white)
[![Version](https://img.shields.io/badge/version-0.4.0-blue.svg)](https://github.com/njkmdb/llm-rpc-schema-enforcer)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)

> **"LLM 호출을 스키마 기반의 백엔드 RPC로 취급하여, AI의 비결정론적 출력을 규격화된 JSON 데이터로 변환하는 미들웨어"**

**LLM RPC Schema Enforcer (LRSE)**는 대형 언어 모델(LLM)의 비결정론적 출력과 환각(Hallucination) 현상을 제어하기 위해 설계된 백엔드 미들웨어입니다. 클라이언트 애플리케이션과 분리된 원격 프로시저 호출(RPC) 서버 형태로 동작합니다.

---

## 🚀 Getting Started (로컬 실행 가이드)

이 프로젝트는 Docker 기반으로 구성되어 있어 복잡한 파이썬 가상 환경 설정 없이 단 한 줄의 명령어로 기동할 수 있습니다.

**1. 환경 변수 세팅**
프로젝트 최상단 경로의 `.env.example` 파일을 복사하여 **`.env`** 파일을 생성합니다. 
*(※ Defacto LTM-Sync 시스템과 연동하여 사용할 경우, API 키는 프론트엔드에서 동적으로 주입되므로 파일 내부를 비워두셔도 무방합니다.)*

**2. 도커 컨테이너 기동**
터미널에서 아래 명령어를 실행하여 미들웨어 서버를 8081 포트에 띄웁니다.
```bash
# 최초 기동 (이미지 빌드 포함)
docker-compose up --build -d

# 일반 기동 (평상시)
docker-compose up -d

# 시스템 종료
docker-compose stop
```

---

## 핵심 아키텍처 철학 (Core Philosophy)

* **결정론적 출력 제어:**  
Pydantic 스키마를 통해 출력 형식을 정의합니다. 모델 온도(Temperature)를 0.0으로 고정하여 일관된 결과를 유도합니다.

* **클라이언트 분리 (Client Decoupling):**  
클라이언트 애플리케이션은 프롬프트 엔지니어링이나 LLM SDK를 직접 구현할 필요가 없습니다. 필요한 데이터 스키마(JSON)와 컨텍스트 페이로드만 API로 전달하여 결과를 수신합니다.

* **무상태 처리 (Stateless Processing):**  
내부 VM 인터프리터는 데이터베이스를 직접 수정하지 않으며, 런타임에 클라이언트가 동적으로 주입하는 JSON Schema(`dynamic_schema_definition`)를 실시간으로 해석하여 상태(세션)를 전혀 만들지 않고도 완벽한 무상태(Stateless) 데이터 변환을 수행할 수 있습니다.

* **Thick vs Thin 클라이언트 이중 지원:**  
상태를 자체적으로 기억하고 복구할 수 있는 무거운 클라이언트에게는 순수 번역 기능(`/rpc/call`)만을 제공하며, 상태 보존 능력이 없는 가벼운 클라이언트(Thin Client)를 위해서는 상태 변이 및 영속화(`/rpc/execute`)까지 책임지는 유연한 아키텍처를 가집니다.

* **동적 모델 탐색 (Auto-discovery):**  
버전에 종속된 모델명 하드코딩을 배제하고, 통신 시점에 현재 사용 가능한 모델 목록을 호출(`list`)하여 가장 최신의 텍스트 생성 전용 모델로 스스로 바인딩합니다.

* **BYOK 및 세션 격리 (Secure Multi-tenancy):**  
클라이언트가 HTTP 헤더를 통해 개인 API 키와 세션 비밀번호를 직접 지참(BYOK)하게 하여 완벽한 테넌트 격리를 구현합니다.

* **오류 복구 및 재시도:**  
LLM의 출력이 스키마 규격을 위반할 경우, 오류 내역을 프롬프트에 포함하여 재요청합니다. 이를 통해 시스템 중단을 방지하고 유효한 데이터 출력을 유도합니다.

* **파괴적 액션의 사용자 통제 (User-Controlled Destructive Actions):**  
데이터 삭제(`DESTROY_ENTITY`)와 같은 파괴적이고 돌이킬 수 없는 로직은 AI의 추론에 맡기지 않고 스키마 레벨에서 원천 차단하여, 데이터 무결성과 시스템 안전성을 보장합니다.

---

## 주요 기능 (Key Features)

### 1. 스키마 기반 출력 제어 (Schema Enforcement)
서버 레지스트리에 등록된 Pydantic 모델에서 JSON Schema 명세를 추출하거나 클라이언트가 보낸 동적 스키마를 바탕으로 LLM에 전달합니다. 반환되는 데이터가 사전에 정의된 JSON 규격을 준수하도록 관리합니다.
* **네이티브 스키마 방어적 도입:** Gemini API의 `response_schema`를 1차로 시도하되, 복잡한 스키마 제약으로 인한 API 에러를 방지하기 위해 기존 텍스트 파싱 및 재시도 로직으로 즉각 Fallback 되도록 이중화하여 안정성을 극대화했습니다.

### 2. 범용 RPC 라우터 (RPC Gateway)
FastAPI 기반의 API 게이트웨이를 제공합니다. 다양한 클라이언트 앱은 도메인 스키마 이름과 컨텍스트만으로 AI 추론 결과를 요청할 수 있습니다.
* **엔드포인트 분리 설계:** 클라이언트의 성격에 따라 상태 보존이 필요 없는 무상태(Stateless) 번역 엔드포인트(`/rpc/call`)와 상태를 직접 변이시키고 영속화하는 상태 유지(Stateful) 엔드포인트(`/rpc/execute`)를 분리하여 제공합니다.
* **안전한 폴백 라우팅 (Fallback Routing):** 클라이언트 요청 시 1) 동적 스키마 정의 -> 2) DB 세션 스냅샷 동적 스키마 -> 3) 내부 정적 레지스트리 순으로 안전하게 스키마를 찾아가는 3단계 계층적 라우팅을 지원합니다.
* **API 스키마 유연성 확보:** `/api/v1/session/init` 엔드포인트에서 불필요한 `api_key`, `model_name` 파라미터를 `Optional`로 변경하여 클라이언트 종속성을 제거했습니다.

### 3. 자동 재시도 로직 (Retry Loop)
Pydantic 검증 실패(`ValidationError`) 발생 시, 빈 데이터를 반환하는 대신 에러 로그를 LLM에 피드백합니다. 최대 3회까지 데이터를 다시 생성하도록 요청하여 구조를 교정합니다.

### 4. Append-Only 상태 관리 (State Manager)
데이터를 직접 덮어쓰기(UPDATE)하지 않고, 전체 스냅샷 복제 후 포인터를 변경합니다. 다중 버전 동시성 제어(MVCC) 방식을 사용하여 상태를 안전하게 관리합니다.
* **낙관적 락(Optimistic Lock) 도입:** SQLite 환경에서 발생할 수 있는 동시성 이슈를 방어하기 위해 세션 메타데이터에 버전을 대조하는 가벼운 낙관적 락 메커니즘을 추가했습니다.
* **단일 엔티티 조회 (Helper Method):** `get_entity` 메서드를 통해 전체 스냅샷 페이로드를 가져온 뒤 메모리 상에서 필요한 엔티티만 필터링하여 빠르고 안전하게 조회할 수 있습니다.

---
## 업데이트 내역 (Changelog)

* **2026.09.01 (v0.4.0)**  
・런타임 동적 스키마(`dynamic_schema_definition`) 주입을 통한 완전한 무상태(Stateless) 아키텍처 지원  
・우선순위 기반(동적 스키마 -> 세션 DB -> 레지스트리) 폴백 라우팅 구축

* **2026.08.30 (v0.3.1)**  
・도커(Docker) 기반 독립 실행 환경 구축 (`Dockerfile`, `docker-compose.yml`)  
・컨테이너 환경에서의 SQLite 상태 영속성(Persistence) 보장을 위한 볼륨 마운트 적용  
・`.env` 파일 분리 및 깃허브 보안 정책(`gitignore`) 강화를 통한 API 키 유출 원천 차단

* **2026.08.16 (v0.3.0)**  
・DESTROY_ENTITY 액션 권한 스키마 레벨 원천 차단  
・단일 엔티티 조회를 위한 get_entity 헬퍼 메서드 추가  
・상태 증발(State Evaporation) 버그 해결 및 상태 병합(Merge) 아키텍처 도입  
・commit_turn 파라미터 불일치 크래시 수정  
・클라이언트 유형(Thick/Thin)에 따른 엔드포인트 역할 분담 문서화  

* **2026.08.02 (v0.2.0)**  
・네이티브 스키마(`response_schema`) 및 텍스트 파싱 기반 Fallback 이중화 구조 도입  
・SQLite 낙관적 락(Optimistic Lock) 도입을 통한 동시성 이슈 방어  
・세션 초기화 API(`/init`)의 불필요한 파라미터(`api_key`, `model_name`) Optional 변경

* **2026.07.15 (v0.1.0)**  
・초기 릴리즈

---

## 프로젝트 구조 (Directory Structure)

```text
llm-rpc-schema-enforcer/
├── core_engine/                 # 무상태 백엔드 코어 시스템 (LRSE 미들웨어)
│   ├── api/                     # FastAPI 게이트웨이 및 RPC 라우터 (`main.py`)
│   ├── schemas/                 # Pydantic V2 데이터 검증 및 클라이언트 스키마 레지스트리 (`api_models.py`, `llm_io.py`)
│   ├── state/                   # SQLite 기반 Append-Only 영속성 계층 (`db_manager.py`)
│   └── vm/                      # AI 프롬프트 어댑터 및 스키마 검증 코어 모듈 (`lrse_enforcer.py`, `interpreter.py`)
├── scripts/                     # DB 초기화 및 상태 점검을 위한 CLI 유틸리티 (`init_db.py`, `check_db.py`)
├── test_pipeline.py             # E2E 파이프라인 검증 테스트 스크립트
└── README.md