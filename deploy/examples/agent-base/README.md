# agent-base 예제 번들

각 디렉토리는 배포 가능한 agent 번들의 대표 예제다. **자체 tool + MCP server 호출** 패턴을 보여준다 — 에이전트는 자기 코드의 툴(reflection / 산술)과 mcp-pool 의 외부 툴(웹 검색 / URL fetch) 둘 다 사용.

**런타임 계약 요약**

- factory 시그니처: `def build_agent(cfg: dict, secrets: SecretResolver) -> NativeObj`
- factory 는 `(checksum, principal_id, user.updated_at)` 조합당 **정확히 1회** 호출. 반환된 객체는 모든 invoke 에 재사용 ([packages/common/DESIGN.md](../../../packages/common/DESIGN.md) 의 instance_cache 참조).
- 무거운 자원(LLM 클라이언트, DB 풀)은 factory 안에서 만들어도 안전.
- **API 키는 `source_meta.config`** 에 직접 둔다 (이 프로젝트 컨벤션 — bundle/tool 별 자격증명은 cfg, 인프라 DSN 은 secrets_ref). 자세한 매핑은 [packages/common/src/runtime_common/config_schema.py](../../../packages/common/src/runtime_common/config_schema.py) 상단 참조.
- **MCP 호출 경로**: `agent_base.app.get_current_token()` 으로 사용자 JWT 를 잡아 `POST {MCP_GATEWAY_URL}/v1/mcp/invoke-internal` 에 `Authorization: Bearer ...` + `X-Runtime-Caller: agent-pool` 로 전달. ext-authz 의 grace 기간 검증 통과 후 mcp-pool 로 라우팅.

---

## compiled_graph_bundle — DeepAgents 리서치 오케스트레이터

`create_deep_agent()` 로 만든 `CompiledStateGraph`. **자체 툴 1개 + MCP 툴 2개 + 위임 subagent 1개** 구성:

| 툴 | 종류 | 설명 |
|----|------|------|
| `think_tool` | 자체 (LLM 없음, I/O 없음) | reflection 기록 |
| `naver_search` | MCP 라우팅 → `search-server.naver_search` | 한국어 웹 검색 |
| `fetch_url` | MCP 라우팅 → `search-server.fetch_url` | URL 본문 가져오기 (8KB cap) |

`researcher` 라는 이름의 subagent 가 같은 툴 셋을 갖고 있어 orchestrator 가 주제별로 위임 가능.

**번들 deps**: `httpx>=0.27` 만. LangGraph / LangChain / deepagents / `langchain-anthropic` / `langchain-openai` 는 베이스 이미지에 포함.

**지원 모델 provider** — `cfg.langgraph.model` 의 prefix 로 자동 분기 (`init_chat_model` 사용):
- `anthropic:claude-...` → `cfg["anthropic_api_key"]` 또는 env `ANTHROPIC_API_KEY`
- `openai:gpt-...` → `cfg["openai_api_key"]` 또는 env `OPENAI_API_KEY`
- `google:gemini-...` → `cfg["google_api_key"]` 또는 env `GOOGLE_API_KEY`

**source_meta.config 예시**

```json
{
  "langgraph": {
    "model": "openai:gpt-4o-mini",
    "checkpointer": "redis",
    "store": {"backend": "memory"}
  },
  "mcp_server": "search-server",
  "openai_api_key": "sk-..."
}
```

**user_meta.secrets_ref 키** (UPPERCASE — env var 컨벤션, 인프라 DSN 만)

```
CHECKPOINTER_DSN  : redis://redis:6379/0
STORE_DSN         : (사용 시)
```

**user_meta.config (override 예시)**

```json
{"langgraph": {"model": "anthropic:claude-opus-4-7"}, "mcp_server": "search-server-v2"}
```

**source_meta 등록**

```sql
INSERT INTO source_meta (kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, config)
VALUES (
  'agent', 'research-orchestrator', 'v1', 'agent:compiled_graph',
  'app:build_agent', 's3://bundles/research-orchestrator-v1.zip', 'sha256:<…>',
  '{"langgraph":{"model":"anthropic:claude-sonnet-4-6","checkpointer":"redis"},"mcp_server":"search-server","anthropic_api_key":"sk-ant-..."}'::jsonb
);
```

---

## adk_bundle — Google ADK research-and-math 에이전트

`LlmAgent` (Gemini) + **자체 툴 1개 + MCP 툴 2개**:

| 툴 | 종류 | 설명 |
|----|------|------|
| `calculate` | 자체 (ast 기반 안전 산술) | `+ - * / // % **` 평가 |
| `naver_search` | MCP 라우팅 | 한국어 웹 검색 |
| `fetch_url` | MCP 라우팅 | URL 본문 가져오기 |

`agent-base` 가 `Runner` (with InMemorySessionService) 를 만들어 감싸므로 번들은 `Agent` 만 반환.

**번들 deps**: 베이스 이미지의 `google-adk` + `httpx` 사용 — 추가 deps 없음.

**지원 모델 provider** — `cfg.adk.model` 의 prefix 로 자동 분기:
- `google:gemini-...` → ADK 네이티브, `cfg["google_api_key"]`
- `openai:gpt-...` → `LiteLlm("openai/...")` 으로 래핑, `cfg["openai_api_key"]`
- `anthropic:claude-...` → `LiteLlm("anthropic/...")`, `cfg["anthropic_api_key"]`

**source_meta.config 예시**

```json
{
  "adk": {
    "model": "openai:gpt-4o-mini",
    "temperature": 0.0,
    "max_output_tokens": 4096
  },
  "mcp_server": "search-server",
  "openai_api_key": "sk-..."
}
```

**user_meta.config (override)**

```json
{"adk": {"model": "google:gemini-2.5-flash", "temperature": 0.7}, "mcp_server": "search-server-v2"}
```

**source_meta 등록**

```sql
INSERT INTO source_meta (kind, name, version, runtime_pool, entrypoint, bundle_uri, checksum, config)
VALUES (
  'agent', 'research-math-agent', 'v1', 'agent:adk',
  'app:build_agent', 's3://bundles/research-math-agent-v1.zip', 'sha256:<…>',
  '{"adk":{"model":"openai:gpt-4o-mini","temperature":0.0},"mcp_server":"search-server","openai_api_key":"sk-..."}'::jsonb
);
```

---

## 배포 절차 (양 번들 공통)

1. 디렉토리 내용을 zip 으로 묶는다 (`app.py` 가 아카이브 루트에 오도록).
2. S3 / OCI / file / http URI 에 업로드.
3. `source_meta` 행을 admin backend 의 `POST /admin/source-meta` 로 등록 (위 SQL 은 직삽 디버깅용).
4. principal 별 override 가 필요하면 admin backend `POST /admin/user-meta` 로 `user_meta` 행 추가.
5. **MCP server 도 함께 배포** — agent 가 호출하려는 MCP 서버 (예: `mcp-base/mcp_sdk_bundle` → `search-server`) 가 mcp-pool 에 등록돼 있어야 함.
