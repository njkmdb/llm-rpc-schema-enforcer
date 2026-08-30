# LRSE (LLM RPC Schema Enforcer)

| [🇺🇸 English](README.md) | [🇰🇷 한국어](README_ko.md) | [🇯🇵 日本語](README_ja.md)

![100% AI Generated](https://img.shields.io/badge/100%25_AI_Generated-8A2BE2?style=flat&logo=googlegemini&logoColor=white)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://github.com/njkmdb/llm-rpc-schema-enforcer)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)

> **「LLMの呼び出しをスキーマベースのバックエンドRPCとして扱い、AIの非決定論的な出力を規格化されたJSONデータに変換するミドルウェア」**

**LLM RPC Schema Enforcer (LRSE)** は、大規模言語モデル (LLM) の非決定論的な出力とハルシネーション (Hallucination) 現象を制御するために設計されたバックエンドミドルウェアです。クライアントアプリケーションから分離されたリモートプロシージャコール (RPC) サーバーの形態で動作します。

---

## 🚀 Getting Started (ローカル実行ガイド)

このプロジェクトはDockerベースで構成されており、複雑なPython仮想環境の設定なしに、たった1行のコマンドで起動できます。

**1. 環境変数の設定**
プロジェクトの最上位ディレクトリにある `.env.example` ファイルをコピーして、**`.env`** ファイルを作成します。
*（※ Defacto LTM-Syncシステムと連動して使用する場合、APIキーはフロントエンドから動的に注入されるため、ファイルの中身は空のままでも構いません。）*

**2. Dockerコンテナの起動**
ターミナルで以下のコマンドを実行し、ミドルウェアサーバーをポート8081で立ち上げます。
```bash
# 初回起動 (イメージビルドを含む)
docker-compose up --build -d

# 通常起動 (普段の実行)
docker-compose up -d

# システムの終了
docker-compose stop
```

---

## コアアーキテクチャ哲学 (Core Philosophy)

* **決定論的な出力制御:** Pydanticスキーマを通じて出力形式を定義します。モデルの温度 (Temperature) を0.0に固定し、一貫した結果を誘導します。
* **クライアントの分離 (Client Decoupling):** クライアントアプリケーションは、プロンプトエンジニアリングやLLM SDKを直接実装する必要がありません。必要なデータスキーマ (JSON) とコンテキストペイロードのみをAPIで渡し、結果を受信します。
* **ステートレス処理 (Stateless Processing):** 内部のVMインタープリタはデータベース (永続化層) を直接変更しません。メモリ上で純粋関数 (Pure Function) の形でトランザクションを処理し、原子性 (Atomicity) を維持します。
* **Thick vs Thin クライアントのデュアルサポート:** 状態を独自に記憶して復元できる重いクライアントには純粋な翻訳機能 (`/rpc/call`) のみを提供し、状態保存能力のない軽いクライアント (Thin Client) のためには状態の変異と永続化 (`/rpc/execute`) まで担う柔軟なアーキテクチャを持ちます。
* **BYOK およびセッションの隔離 (Secure Multi-tenancy):** クライアントがHTTPヘッダーを通じて個人のAPIキーとセッションパスワードを直接持参 (BYOK) させることで、完璧なテナント隔離を実装します。
* **エラー復旧と再試行:** LLMの出力がスキーマ規格に違反した場合、エラー内容をプロンプトに含めて再リクエストします。これにより、システムの中断を防ぎ、有効なデータ出力を誘導します。
* **破壊的アクションのユーザー統制 (User-Controlled Destructive Actions):** データの削除 (`DESTROY_ENTITY`) のような破壊的で取り返しのつかないロジックは、AIの推論に任せずスキーマレベルで根本から遮断し、データ整合性とシステム安全性を保証します。

---

## 主な機能 (Key Features)

### 1. スキーマベースの出力制御 (Schema Enforcement)
サーバーのレジストリに登録されたPydanticモデルからJSON Schema仕様を抽出し、LLMに伝達します。返されるデータが事前に定義されたJSON規格を遵守するように管理します。
* **ネイティブスキーマの防御的導入:** Gemini APIの `response_schema` を1次として試みますが、複雑なスキーマ制約によるAPIエラーを防ぐため、既存のテキスト解析および再試行ロジックに即座にフォールバック (Fallback) されるように二重化し、安定性を極大化しました。

### 2. 汎用RPCルーター (RPC Gateway)
FastAPIベースのAPIゲートウェイを提供します。多様なクライアントアプリは、ドメインスキーマ名とコンテキストのみでAI推論結果をリクエストできます。
* **エンドポイント分離設計:** クライアントの性質に応じて、状態保存が不要なステートレス (Stateless) 翻訳エンドポイント (`/rpc/call`) と、状態を直接変異させて永続化するステートフル (Stateful) エンドポイント (`/rpc/execute`) を分離して提供します。
* **APIスキーマの柔軟性確保:** `/api/v1/session/init` エンドポイントで不要な `api_key`、`model_name` パラメータを `Optional` に変更し、クライアントへの依存性を排除しました。

### 3. 自動再試行ロジック (Retry Loop)
Pydanticの検証失敗 (`ValidationError`) 発生時、空のデータを返す代わりにエラーログをLLMにフィードバックします。最大3回までデータを再生成するようにリクエストし、構造を校正します。

### 4. Append-Only 状態管理 (State Manager)
データを直接上書き (UPDATE) せず、全体スナップショットを複製した後にポインターを変更します。多重バージョン同時実行制御 (MVCC) 方式を使用して状態を安全に管理します。
* **楽観的ロック (Optimistic Lock) の導入:** SQLite環境で発生しうる同時実行性の問題を防ぐため、セッションメタデータにバージョンを照合する軽量な楽観的ロックメカニズムを追加しました。
* **単一エンティティの照会 (Helper Method):** `get_entity` メソッドを通じて全体スナップショットペイロードを取得した後、メモリ上で必要なエンティティのみをフィルタリングし、迅速かつ安全に照会できます。

---
## アップデート履歴 (Changelog)

* **2026.08.30 (v0.3.1)**  
・Dockerベースの独立実行環境の構築 (`Dockerfile`, `docker-compose.yml`)  
・コンテナ環境におけるSQLite状態の永続性 (Persistence) 保証のためのボリュームマウント適用  
・`.env` ファイルの分離およびGitHubセキュリティポリシー (`.gitignore`) 強化によるAPIキー流出の根本的遮断

* **2026.08.16 (v0.3.0)**  
・`DESTROY_ENTITY` アクション権限をスキーマレベルで根本から遮断  
・単一エンティティ照会用の `get_entity` ヘルパーメソッドを追加  
・状態蒸発 (State Evaporation) バグの解決および状態マージ (Merge) アーキテクチャの導入  
・`commit_turn` パラメータ不一致のクラッシュを修正  
・クライアントのタイプ (Thick/Thin) に応じたエンドポイントの役割分担を文書化  

* **2026.08.02 (v0.2.0)**  
・ネイティブスキーマ (`response_schema`) およびテキスト解析ベースのFallback二重化構造の導入  
・SQLite楽観的ロック (Optimistic Lock) の導入による同時実行性の問題の防御  
・セッション初期化API (`/init`) の不要なパラメータ (`api_key`, `model_name`) をOptionalに変更

* **2026.07.15 (v0.1.0)**  
・初回リリース

---

## プロジェクト構造 (Directory Structure)

```text
llm-rpc-schema-enforcer/
├── core_engine/                 # ステートレスバックエンドコアシステム (LRSE ミドルウェア)
│   ├── api/                     # FastAPI ゲートウェイおよびRPCルーター (`main.py`)
│   ├── schemas/                 # Pydantic V2 データ検証およびクライアントスキーマレジストリ (`api_models.py`, `llm_io.py`)
│   ├── state/                   # SQLiteベースの Append-Only 永続化層 (`db_manager.py`)
│   └── vm/                      # AIプロンプトアダプタおよびスキーマ検証コアモジュール (`lrse_enforcer.py`, `interpreter.py`)
├── scripts/                     # DB初期化および状態点検用のCLIユーティリティ (`init_db.py`, `check_db.py`)
├── test_pipeline.py             # E2Eパイプライン検証テストスクリプト
└── README.md