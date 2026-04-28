실 dev 클러스터(Ingress: `https://agents.didim365.app`) 에 대한 curl 기반 e2e 스모크 테스트.

번들 4종을 등록하고 agent 2종을 호출한다 — agent → ext-authz/Envoy → agent-pool → (필요 시) mcp-pool 경로 전체를 검증.

## 실행

```bash
export ADMIN_PASSWORD='<initial admin password>'
export OPENAI_API_KEY='sk-...'      # 두 agent 모두 OpenAI로 LLM 호출
./run.sh
```

### 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ADMIN_PASSWORD` | (필수) | 백엔드 BFF 로그인 비밀번호 |
| `AGENTS_HOST` | `https://agents.didim365.app` | Ingress 호스트 |
| `ADMIN_USER` | `admin` | 로그인 계정 |
| `OPENAI_API_KEY` | (선택) | DeepAgent / ADK 양쪽 모두 OpenAI 모델 사용 |
| `OPENAI_MODEL` | `openai:gpt-4o-mini` | 두 agent 의 model spec |
| `ANTHROPIC_API_KEY` | (선택) | DeepAgent 가 `anthropic:` 모델일 때 |
| `GOOGLE_API_KEY` | (선택) | ADK 가 `google:gemini-...` 모델일 때 |
| `NAVER_CLIENT_ID` | (선택) | search-server 의 `naver_search` 툴이 사용 |
| `NAVER_CLIENT_SECRET` | (선택) | 동일 |

LLM 키가 빠지면 등록·resolve·factory build 까지는 통과하지만 step 5 의 invoke 가 5xx 로 떨어진다(스크립트가 warn 한다).

의존성: `curl`, `jq`, `zip`.

## 흐름

| 단계 | 엔드포인트 | 동작 |
|---|---|---|
| 1. login | `POST /api/auth/login` | 백엔드 BFF 가 auth 서비스에 위임 후 `access_token` / `refresh_token` / `csrf_token` 쿠키 발급. 이후 admin API 는 cookie + `X-CSRF-Token` 헤더, agent invoke 는 `Authorization: Bearer <access_token cookie 값>`. |
| 2. zip + register | `POST /api/source-meta/bundle` (multipart) | 4개 번들 디렉토리를 zip(루트에 `app.py`)으로 묶어 업로드. **`meta` JSON 의 `config` 필드에 LLM/Naver 키를 env 에서 읽어 주입** — 시크릿이 git 에 들어가지 않게 한다. backend 가 zip 을 S3 / 로컬에 저장하고 sha256 계산 후 `source_meta` 행을 만든다. |
| 3. user_meta upsert | `PUT /api/user-meta` | 2개 agent 에 대해 admin 사용자의 `mcp_server` override 등록 — 1-depth deep merge 경로 검증용. |
| 4. grant access | `POST /api/users/{id}/access` | `(admin, kind, name)` 4쌍을 `user_resource_access` 에 INSERT. **admin 도 자동 면제 아님** — `Principal.can_access` 가 명시 row 를 요구. |
| 5. invoke | `POST /v1/agents/invoke` | 두 agent 를 각각 호출. ADK 는 자체 `calculate` 툴 사용 / DeepAgent 는 LLM 응답. MCP 호출은 LLM 이 판단 시 `MCP_GATEWAY_URL/v1/mcp/invoke-internal` 경유 (Naver 키 있을 때만 의미). |

## 등록되는 번들

| 디렉토리 | kind | name | runtime_pool | entrypoint |
|---|---|---|---|---|
| `agent-base/compiled_graph_bundle` | agent | `research-orchestrator` | `agent:compiled_graph` | `app:build_agent` |
| `agent-base/adk_bundle` | agent | `research-math-agent` | `agent:adk` | `app:build_agent` |
| `mcp-base/fastmcp_bundle` | mcp | `utility-server` | `mcp:fastmcp` | `app:build_server` |
| `mcp-base/mcp_sdk_bundle` | mcp | **`search-server`** | `mcp:mcp_sdk` | `app:build_server` |

⚠️ mcp_sdk 번들은 반드시 `search-server` 로 등록해야 한다 — agent 번들이 `cfg["mcp_server"]` 디폴트로 이 이름을 호출한다. fastmcp 번들(`utility-server`)은 풀 종류 검증용이지 agent 가 직접 부르지 않는다.

## 키 / config 분리 컨벤션

- **API 키 (LLM, Naver)** — `source_meta.config` 에 직접 (예: `cfg["openai_api_key"]`, `cfg["naver"]["client_id"]`). 번들 코드가 cfg 에서 읽어 필요 시 env var 로 export.
- **인프라 DSN** — `secrets_ref` 경유 (이 e2e 는 `checkpointer: "none"` 이라 DSN 불필요).

자세한 컨벤션은 [packages/common/src/runtime_common/config_schema.py](../../../../packages/common/src/runtime_common/config_schema.py) 상단 docstring 참조.

## 멱등성

`source_meta` UNIQUE `(kind, name, version)` 충돌(409) 은 자동으로 **기존 row 의 id 를 조회해 재사용**한다. `user_resource_access` 도 grant API 가 idempotent. 따라서 같은 호스트에 대해 `./run.sh` 를 반복 실행해도 안전하다.

⚠️ 번들 **코드** 를 바꾸고 다시 등록하려면: ① `version` 을 올리거나, ② 같은 (kind, name, version) 행을 직접 DELETE 해야 한다 (409 핸들러는 새 코드를 무시하고 옛 id 반환).

## 산출물

`work/` 아래에 zip · cookie jar · state 파일이 떨어진다 (gitignore 처리).
