# runtime-common

모든 서비스(agent-gateway, mcp-gateway, auth, deploy-api)와 런타임 베이스 이미지(agent-base, mcp-base)가 공용으로 import 하는 라이브러리.

## 설계

- **Pure library**: FastAPI app 없음. 부수효과 없음(단, `BundleLoader`는 파일시스템 사용).
- **모듈 경계**
  - `settings.py` — `BaseRuntimeSettings` (pydantic-settings). 모든 서비스가 이걸 상속해서 자기 env 필드를 추가.
  - `schemas.py` — 서비스 간 계약. `SourceMeta`, `UserMeta`, `ResolveResponse`, `AgentRuntimeKind`, `McpRuntimeKind`, `Principal`, `AgentInvokeRequest`, `McpInvokeRequest`.
    - `SourceMeta(..., config: dict)` — **번들 기본 config**. 버전 고정 immutable. runtime이 `user_meta.config`와 shallow merge 후 factory에 주입.
    - `UserMeta(principal_id, config: dict, secrets_ref: str | None, updated_at)` — per-principal 덮어쓰기.
    - `ResolveResponse(source: SourceMeta, user: UserMeta | None)`
    - `AgentInvokeRequest` / `McpInvokeRequest`는 **식별자 기반** — meta/bundle 정보를 직접 담지 않는다.
    - `Principal`에 `grace_applied: bool` 추가 — `/verify` 에서 내려받은 "이 요청이 exp 유예로 통과되었는가" 플래그. gateway가 감사·관측에 사용.
  - `db/` — Postgres에 붙는 서비스들의 공용 레이어 (gateway/base image는 import 하지 않는다):
    - `db/engine.py` — async SQLAlchemy engine/session factory + `session_scope` 컨텍스트. `make_engine(dsn, pgbouncer=False)` / `make_session_factory(engine)` / `session_scope(factory)`.
    - `db/models.py` — **공용 SQLAlchemy row 모델**. 6개 테이블 전부: `UserRow`, `UserResourceAccessRow`, `RefreshTokenRow`, `ApiKeyRow`, `SourceMetaRow`, `UserMetaRow`. 세 서비스(deploy-api / auth / backend)가 **동일 선언을 import** — 과거에 서비스별 `models.py`가 같은 테이블을 3중 재선언하던 중복을 제거.
    - `db/__init__.py` — 엔진 유틸만 re-export (`make_engine`, `make_session_factory`, `session_scope`). 모델은 `from runtime_common.db.models import SourceMetaRow` 처럼 명시적으로 import — engine만 쓰는 쪽(`runtime_common.db.engine`)은 SQLAlchemy declarative 모델을 로드하지 않음.
    - **schemas.py와의 관계**: `schemas.py`(pydantic)는 HTTP wire 계약으로 **모든** 서비스·런타임이 import. `db/models.py`(SQLAlchemy)는 **DB에 붙는 서비스만** import. 두 파일은 합치지 않는다 — gateway/pool이 SQLAlchemy 의존을 안 끌게 하기 위함.
    - **변환 헬퍼**: `SourceMeta.from_row(row: SourceMetaRow) -> SourceMeta` 같은 classmethod를 `schemas.py`에 추가해 deploy-api·backend의 수동 필드 매핑을 제거.
  - `auth.py` — `AuthClient` (auth 서비스 호출용 thin httpx 래퍼). `verify(token, grace_sec: int = 0) -> Principal` — 엣지 gateway는 기본값(0), 내부 경로는 운영값(예: 300) 전달. 서버측 `GRACE_MAX_SEC`로 clamp. 전체 정책은 `/DESIGN.md`의 "내부 호출의 토큰 Grace Period".
  - **`deploy_client.py`** — `DeployApiClient`. gateway·agent-base·mcp-base가 공유. 주요 메서드:
    - `resolve(kind, name, version, principal) -> ResolveResponse`
    - ETag + 로컬 LRU 캐시(크기·TTL 설정 가능). 조건부 요청(`If-None-Match`) 지원.
    - 등록(`register`)은 admin 서비스 담당으로 이전 — 이 클라이언트에서 제거.
  - **`secrets.py`** — `SecretResolver` 프로토콜. `resolve(ref: str) -> str`. 구현: `EnvSecretResolver`, `VaultSecretResolver`, `AwsSecretsManagerResolver`. `user_meta.secrets_ref` 값을 런타임에 실제 비밀로 변환.
  - `logging.py` — structlog JSON 로깅 구성.
  - `telemetry.py` — OpenTelemetry tracer provider + OTLP exporter. **인프라 관찰가능성 전용** (HTTP 지표·trace → otel-collector → Prometheus/Grafana).
  - `opik_tracing.py` — **LLM 관찰가능성 전용**. OTel과 완전 분리된 Opik SDK 초기화·컨텍스트 헬퍼.
    - `configure_opik()` — `OPIK_URL_OVERRIDE` / `OPIK_WORKSPACE` 환경변수를 읽어 SDK를 초기화. `opik.configure()` 대신 env var 우선(컨테이너 환경에서 `~/.opik.config` 파일 쓰기 없음). `OPIK_TRACK_DISABLE=true` 이면 no-op.
    - `opik_trace_context(name, project_name, session_id, user_id, metadata)` — `opik.start_as_current_trace()` 래퍼. invoke 경계에서 호출해 per-request ContextVar 격리를 보장. Opik SDK가 `contextvars.ContextVar` 기반이므로 FastAPI asyncio task 단위로 자동 격리 — 동시 invoke 간 trace 혼용 없음.
  - `loader.py` — **Lambda 스타일 동적 번들 로더**. `SourceMeta`를 받아 아카이브를 받아오고(sha256 검증 → 서명 검증 → 압축 해제), 엔트리포인트 `module:attr`를 import 하고, 프로세스 내 LRU 캐시에 보관. agent-base와 mcp-base가 공유. `user_meta`는 만지지 않음 — 호출자(runner)가 처리.
    - **번들 서명 검증**: `BUNDLE_VERIFY_SIGNATURES=true`이면 `source_meta.sig_uri`에서 서명 파일을 받아 공개키(`BUNDLE_SIGNING_PUBLIC_KEY` PEM)로 검증. 실패 시 `BundleSignatureError`(→ HTTP 500). 지원 키: ECDSA P-256(cosign 기본), Ed25519. `cryptography` 라이브러리 사용 — 별도 바이너리 없음. dev에서는 기본 off; prod에서는 반드시 켤 것. 서명 형식: `cosign sign-blob --key` 출력(base64 DER). `sig_uri` 스킴은 `http(s)://` · `file://` 지원.
  - **`config_schema.py`** — `source_meta.config` / `user_meta.config` 의 단일 진실 소스. Pydantic 모델로 런타임별 허용 키·타입·기본값을 명세.
    - `SourceConfig` — 전체 source config 루트. 공통(`timeout_seconds`, `log_level`) + 런타임 섹션(`langgraph`, `adk`, `fastmcp`, `mcp`). 루트는 `extra="allow"` — 번들 작성자가 자기만의 top-level 키 추가 가능 (예: `mcp_server`, `naver`, `anthropic_api_key`). 표준 섹션 내부는 여전히 `extra="forbid"` 로 strict.
    - `UserConfig` — per-principal override 루트. 허용된 override 키만 Optional로 노출. `fastmcp`·`mcp`는 per-principal override 없음. 루트는 동일하게 `extra="allow"` (override 가 bundle-specific 키도 타깃 가능).
    - 섹션별 모델: `LangGraphSourceConfig` / `LangGraphUserConfig`, `AdkSourceConfig` / `AdkUserConfig`, `FastMcpSourceConfig`, `McpSdkSourceConfig`.
    - **secrets_ref 키 컨벤션 (UPPERCASE — env var 명규약, EnvSecretResolver 와 호환)**: 인프라 DSN 만 `secrets_ref` 로 흐른다. 표준 키: `CHECKPOINTER_DSN`, `STORE_DSN`, `CACHE_DSN`, `EMBED_API_KEY`, `SESSION_DB_DSN`, `VERTEXAI_CREDENTIALS`, `GCS_BUCKET`, `SESSION_REDIS_DSN`, `TASK_REDIS_DSN`.
    - **API 키는 `source_meta.config` 에 직접** (이 프로젝트 컨벤션 — bundle/tool 별 자격증명은 cfg, 인프라 DSN 만 secrets). 예: `cfg["anthropic_api_key"]`, `cfg["google_api_key"]`, `cfg["naver"]["client_id"]`. 번들 코드가 cfg 에서 읽어 필요 시 env var 로 export (LangChain·ADK 의 `init_chat_model` 같은 헬퍼가 env var 를 자동 인식).
    - admin backend가 등록 시 `SourceConfig.model_validate(config)` / `UserConfig.model_validate(config)` 로 검증.
  - **`providers/`** — config + secrets → 프레임워크-네이티브 인프라 객체 빌더. 번들 factory 가 이 헬퍼들을 호출해 매번 wiring 코드를 반복하지 않도록 한다. **모든 framework 의존(`langgraph`, `google.adk`, `fastmcp`, `mcp`)은 함수 본문 내 lazy import** — mcp-base 이미지에 langgraph 가 없어도 mcp_sdk 번들이 정상 동작.
    - **`providers/langgraph.py`** (LangGraph / DeepAgents 공용)
      - `get_recursion_limit(cfg)` / `get_model_spec(cfg)` — cfg 에서 단순 값 추출.
      - `build_checkpointer(cfg, secrets)` — `cfg.langgraph.checkpointer ∈ {none, memory, sqlite, postgres, mongo, redis}` → `MemorySaver` / `AsyncSqliteSaver` / `AsyncPostgresSaver` / `AsyncMongoDBSaver` / `RedisSaver`. DSN 은 `secrets["CHECKPOINTER_DSN"]`.
      - `build_store(cfg, secrets)` — `cfg.langgraph.store.{backend, index}` → `InMemoryStore` / `AsyncPostgresStore` / `AsyncRedisStore`. `index.embed`/`dims` 가 있으면 semantic search 활성. DSN 은 `secrets["STORE_DSN"]`.
      - `build_cache(cfg, secrets)` — `cfg.langgraph.cache ∈ {none, memory, sqlite, redis}` → `InMemoryCache` / `SqliteCache` / `RedisCache`. DSN 은 `secrets["CACHE_DSN"]`.
    - **`providers/adk.py`** (Google ADK)
      - `get_model(cfg)` / `get_max_llm_calls(cfg)` — 단순 값 추출.
      - `build_generate_content_config(cfg)` — `cfg.adk.{temperature, max_output_tokens, top_p, top_k}` → `genai_types.GenerateContentConfig`.
      - `build_session_service(cfg, secrets)` — `cfg.adk.session_service ∈ {memory, database, vertexai}` → 해당 service. database 는 `secrets["SESSION_DB_DSN"]`.
      - `build_memory_service(cfg, secrets)` — `cfg.adk.memory_service ∈ {memory, vertexai}`.
      - `build_artifact_service(cfg, secrets)` — `cfg.adk.artifact_service ∈ {memory, gcs, database}`. gcs 는 `secrets["GCS_BUCKET"]`.
    - **`providers/fastmcp.py`** (FastMCP)
      - `build_server_kwargs(cfg, secrets)` — `cfg.fastmcp.{strict_input_validation, mask_error_details, list_page_size, session_state_store}` 를 `FastMCP(...)` 생성자 kwargs 로 변환. `session_state_store="redis"` 면 `secrets["SESSION_REDIS_DSN"]` 으로 `RedisStore` 생성해서 주입.
      - `apply_task_queue_env(cfg, secrets)` — `cfg.fastmcp.{task_queue, task_concurrency}` → `FASTMCP_DOCKET__URL` / `FASTMCP_DOCKET__CONCURRENCY` env var 설정. `FastMCP(...)` 생성 **전** 호출.
    - **`providers/mcp_sdk.py`** (공식 MCP SDK)
      - `get_mask_error_details(cfg)` — `cfg.mcp.mask_error_details` 반환. SDK 자체에 hook 이 없어 어댑터가 try/except 로 강제.
    - **사용 패턴** (번들 factory 안에서):
      ```python
      from runtime_common.providers.langgraph import build_checkpointer, build_store
      def build_agent(cfg, secrets):
          return graph.compile(
              checkpointer=build_checkpointer(cfg, secrets),
              store=build_store(cfg, secrets),
          )
      ```
    - 대표 사용 예시는 [deploy/examples/](../../deploy/examples/) 참조 — 4개 번들 모두 provider 사용 패턴 시연.
  - **`factory.py`** — factory 호출 헬퍼.
    - `merge_configs(source_cfg: dict, user_cfg: dict | None) -> dict` — **1-depth 섹션 단위 merge, user wins**. 최상위 값이 둘 다 dict(= 섹션)이면 `{**source_section, **user_section}` 으로 병합해 source 섹션의 나머지 키를 보존. 스칼라·2단 이상 중첩은 user 값으로 교체. source_cfg·user_cfg 원본 불변. agent-base/mcp-base가 resolve 결과를 받은 직후 호출.
    - `call_factory(factory, cfg, secrets)` — zero-arg / `(cfg)` / `(cfg, secrets)` 세 시그니처를 인트로스펙션으로 분기해 하위호환 유지. `cfg`는 `merge_configs`의 결과.
  - **`instance_cache.py`** — factory 가 만든 native instance(CompiledGraph / Runner / FastMCP server) 의 async LRU 캐시.
    - **존재 이유**: factory 호출은 그래프 컴파일·DB 커넥션 풀·체크포인터 세션 등 무거운 인프라를 만든다. 매 invoke마다 재호출하면 운영 비용이 폭발. 이 캐시가 (source 버전 × user override 버전) 당 1회만 호출되도록 보장.
    - `InstanceCache(max_entries)` + `get_or_build(key, builder) -> instance` — sync/async builder 모두 지원. 락으로 콜드스타트 race 차단(같은 key 동시 빌드 직렬화).
    - **캐시 키**: `make_instance_key(checksum, principal_id, user_updated_at) -> (str|None, str|None, float|None)`.
      - `checksum` — source_meta 버전 핀(immutable per checksum).
      - `principal_id` — user_meta 가 있을 때 principal 별 분리.
      - `user_updated_at` — 해당 principal 의 user_meta 갱신 시 자동 무효화 (deploy-api ETag 와 동일 신호 활용).
      - user_meta 가 없으면 `principal_id`/`user_updated_at` 둘 다 None → override 없는 모든 principal 이 단일 entry 공유.
    - **eviction cleanup**: LRU 에서 빠지거나 explicit invalidate 시 instance 의 `aclose()` → `close()` 를 best-effort 로 호출. 예외는 swallow + warning 로그. 번들 작성자가 반환 객체에 이 메서드를 노출해 두면 PG 풀·Redis 연결 등을 안전하게 정리.
    - `invalidate_checksum(checksum)` — 번들 재배포 시 해당 source 의 모든 principal entry 일괄 드롭.
    - `invalidate_principal(checksum, principal_id)` — 특정 principal 의 모든 updated_at entry 드롭.
    - `clear()` — lifespan shutdown 에서 호출.
    - **번들 작성자 계약**: factory 는 `(checksum, principal_id, user.updated_at)` 조합당 1회만 호출됨이 보장. → factory 안에서 PG 풀 같은 무거운 자원을 만들어도 안전. 정리 코드는 반환 객체의 `aclose()`/`close()` 에 둘 것.
  - **`registry.py`** — Redis 기반 warm-registry + Pub/Sub 이벤트 허브. 3면 API:
    - **publisher (pool 측)**: `RegistryPublisher(redis_url, pod_id, addr, runtime_kind, kind, max_concurrent, interval=2s, ttl=3s)` — 백그라운드 태스크로 매 틱에 **(a) 상태 저장**: `rt:warm:{kind}_{runtime_kind}:{checksum}` SADD + `rt:load:{pod_id}` HSET(`active, max, addr`) + EXPIRE, **(b) 이벤트 발행**: `PUBLISH rt:events:{kind}_{runtime_kind}` 에 snapshot JSON(`{type:"snapshot", pod_id, addr, active, max, checksums, ts}`). `preStop` 시 `{type:"down", pod_id, ts}` 발행. warm checksum 집합은 `BundleLoader.warm_checksums()` 같은 getter로 주입. `active` 카운터는 공용 세마포어(`ActiveCounter`)가 공급.
    - **subscriber (gateway 측, push 기반 — 런타임 경로)**: `RegistrySubscriber(redis_url, kind, ttl_sec=3, reconcile_interval_sec=30)` — lifespan에서 `start()` 호출.
      - `PSUBSCRIBE rt:events:{kind}_*` 로 자기 kind의 모든 pool 채널 구독.
      - 내부 테이블: `pods: dict[pod_id, PodState{addr, active, max, checksums: set, last_seen}]` + 역인덱스 `warm: dict[checksum, set[pod_id]]`.
      - `snapshot()` — 메모리 스냅샷 반환 (Scheduler가 invoke 시점에 O(1) 조회).
      - **bootstrap**: subscribe 성립 후 `SCAN MATCH rt:warm:{kind}_*` + pipeline `HGETALL rt:load:*` 로 초기 적재. 순서상 subscribe 먼저 → SCAN 나중 (이벤트 유실 방지, 중복은 idempotent 병합).
      - **reconcile 루프**: 기본 30s 주기로 동일 SCAN 재수행 → drift 보정.
      - **TTL reaper**: `last_seen`이 `ttl_sec × 2`(6s) 경과 pod 엔트리 제거.
      - **재접속**: Redis 단절 시 `healthy()==False`. 재접속 후 subscribe 재성립 + bootstrap 재실행. 단절 구간엔 Scheduler가 `RegistryQuery` 폴백 또는 ring-hash로 전환.
    - **pull 폴백 (gateway 측, degraded 경로)**: `RegistryQuery(redis_url)` — `warm_pods(kind, runtime_kind, checksum) -> list[pod_id]`, `load(pod_ids) -> dict[pod_id, PodLoad{active, max, addr}]`. subscriber가 unhealthy일 때 직접 Redis에 pipeline으로 2 round-trip. 런타임 경로 기본은 subscriber.
    - **key/channel 규약 (agent/mcp 공용)**:
      - 상태: `rt:warm:{agent,mcp}_{runtime_kind}:{checksum}` (SET, TTL 3s), `rt:load:{pod_id}` (HASH `{active, max, addr}`, TTL 3s).
      - 이벤트: `rt:events:{agent,mcp}_{runtime_kind}` (Pub/Sub, JSON payload).
    - `make_redis_saver(url)` 헬퍼: LangGraph `RedisSaver` 팩토리 — 번들 factory가 동일 구성을 반복하지 않도록. 체크포인터 key는 `rt:ckpt:*` prefix.
  - **`scheduling.py`** — gateway 공용 스케줄러. `Scheduler(subscriber, kind, ring_fallback, query=None)`의 `pick(runtime_kind, checksum, endpoints) -> Endpoint`:
    1. `subscriber.healthy()` → `subscriber.snapshot()` 에서 warm pod 집합 + load 조회 → p2c.
    2. subscriber unhealthy → `query`가 있으면 pull로 폴백, 없거나 역시 실패면 `ring_fallback.pick(key=(kind,name,version,checksum))`.
    - agent-gateway/mcp-gateway가 공유.
  - **`active_counter.py`** (또는 `registry.ActiveCounter`) — `asyncio.Semaphore`를 감싸 `active`/`max` 노출. warm-registry publisher가 읽고, pool 런타임이 진입/종료에서 갱신.

