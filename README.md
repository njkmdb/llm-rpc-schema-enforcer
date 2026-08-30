# LRSE (LLM RPC Schema Enforcer)

| [🇺🇸 English](README.md) | [🇰🇷 한국어](README_ko.md) | [🇯🇵 日本語](README_ja.md)

![100% AI Generated](https://img.shields.io/badge/100%25_AI_Generated-8A2BE2?style=flat&logo=googlegemini&logoColor=white)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://github.com/njkmdb/llm-rpc-schema-enforcer)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)

> **"A middleware that treats LLM calls as schema-based backend RPCs, transforming the AI's non-deterministic outputs into standardized JSON data."**

**LLM RPC Schema Enforcer (LRSE)** is a backend middleware designed to control the non-deterministic outputs and hallucination phenomena of Large Language Models (LLMs). It operates in the form of a Remote Procedure Call (RPC) server separated from client applications.

---

## 🚀 Getting Started (Local Execution Guide)

This project is configured based on Docker, allowing it to be booted up with a single command without complex Python virtual environment setups.

**1. Environment Variable Setup**
Copy the `.env.example` file in the root directory to create an **`.env`** file.
*(※ If you are using this in conjunction with the Defacto LTM-Sync system, the API key is dynamically injected from the frontend, so you can leave the inside of the file empty.)*

**2. Booting the Docker Container**
Run the following command in the terminal to boot the middleware server on port 8081.
```bash
# Initial Boot (including image build)
docker-compose up --build -d

# Normal Boot (regular execution)
docker-compose up -d

# System Shutdown
docker-compose stop
```

---

## Core Philosophy

* **Deterministic Output Control:** Defines the output format through Pydantic schemas. Induces consistent results by fixing the model temperature to 0.0.
* **Client Decoupling:** Client applications do not need to implement prompt engineering or LLM SDKs directly. They receive results by simply passing the required data schema (JSON) and context payload via API.
* **Stateless Processing:** The internal VM interpreter does not directly modify the database (persistence layer). It maintains atomicity by processing transactions in the form of pure functions in memory.
* **Thick vs Thin Client Dual Support:** Provides only pure translation functions (`/rpc/call`) for heavy clients that can remember and restore state internally, while maintaining a flexible architecture responsible for state mutation and persistence (`/rpc/execute`) for lightweight clients (Thin Clients) without state preservation capabilities.
* **BYOK and Session Isolation (Secure Multi-tenancy):** Implements perfect tenant isolation by requiring clients to directly bring their personal API keys and session passwords via HTTP headers (BYOK).
* **Error Recovery and Retry:** If the LLM's output violates the schema specifications, it re-requests by including the error details in the prompt. This prevents system interruptions and induces valid data output.
* **User-Controlled Destructive Actions:** Ensures data integrity and system safety by fundamentally blocking destructive and irreversible logic, such as data deletion (`DESTROY_ENTITY`), at the schema level rather than leaving it to the AI's inference.

---

## Key Features

### 1. Schema Enforcement
Extracts JSON Schema specifications from Pydantic models registered in the server registry and passes them to the LLM. Manages the returned data to comply with the predefined JSON specifications.
* **Defensive Adoption of Native Schema:** Primarily attempts the Gemini API's `response_schema`, but maximizes stability by adopting a dual structure that immediately falls back to the existing text parsing and retry logic to prevent API errors caused by complex schema constraints.

### 2. Universal RPC Gateway
Provides a FastAPI-based API gateway. Various client apps can request AI inference results using only domain schema names and contexts.
* **Endpoint Separation Design:** Depending on the nature of the client, it separates and provides a stateless translation endpoint (`/rpc/call`) that does not require state preservation, and a stateful endpoint (`/rpc/execute`) that directly mutates and persists state.
* **Securing API Schema Flexibility:** Eliminated client dependencies by changing unnecessary `api_key` and `model_name` parameters to `Optional` in the `/api/v1/session/init` endpoint.

### 3. Auto Retry Logic (Retry Loop)
When a Pydantic validation failure (`ValidationError`) occurs, it feeds back the error log to the LLM instead of returning empty data. Requests data regeneration up to 3 times to correct the structure.

### 4. Append-Only State Management (State Manager)
Does not directly overwrite (UPDATE) data, but changes the pointer after replicating the entire snapshot. Manages state safely using the Multi-Version Concurrency Control (MVCC) method.
* **Introduction of Optimistic Lock:** Added a lightweight optimistic lock mechanism that verifies versions in session metadata to prevent concurrency issues that can occur in SQLite environments.
* **Single Entity Lookup (Helper Method):** Can quickly and safely lookup by fetching the entire snapshot payload through the `get_entity` method and filtering only the necessary entities in memory.

---
## Changelog

* **2026.08.30 (v0.3.1)**  
・Established a standalone execution environment based on Docker (`Dockerfile`, `docker-compose.yml`)  
・Applied volume mounting to ensure SQLite state persistence in the container environment  
・Fundamentally blocked API key leaks by separating `.env` files and strengthening GitHub security policies (`.gitignore`)

* **2026.08.16 (v0.3.0)**
・Fundamentally blocked `DESTROY_ENTITY` action permissions at the schema level
・Added `get_entity` helper method for single entity lookup
・Resolved state evaporation bug and introduced state merge architecture
・Fixed crash due to `commit_turn` parameter mismatch
・Documented endpoint role division according to client type (Thick/Thin)

* **2026.08.02 (v0.2.0)**
・Introduced native schema (`response_schema`) and text parsing-based fallback dual structure
・Prevented concurrency issues by introducing SQLite Optimistic Lock
・Changed unnecessary parameters (`api_key`, `model_name`) of the session initialization API (`/init`) to Optional

* **2026.07.15 (v0.1.0)**
・Initial release

---

## Directory Structure

```text
llm-rpc-schema-enforcer/
├── core_engine/                 # Stateless backend core system (LRSE Middleware)
│   ├── api/                     # FastAPI gateway and RPC router (`main.py`)
│   ├── schemas/                 # Pydantic V2 data validation and client schema registry (`api_models.py`, `llm_io.py`)
│   ├── state/                   # SQLite-based Append-Only persistence layer (`db_manager.py`)
│   └── vm/                      # AI prompt adapter and schema validation core module (`lrse_enforcer.py`, `interpreter.py`)
├── scripts/                     # CLI utilities for DB initialization and state check (`init_db.py`, `check_db.py`)
├── test_pipeline.py             # E2E pipeline validation test script
└── README.md