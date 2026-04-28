# agent-base

Agent-Pool의 베이스 이미지. AWS Lambda와 유사하게 **같은 이미지**가 장기 실행 pod로 떠 있다가, 요청이 오면 **deploy-api에서 자기 agent 코드 정의 + 사용자 메타를 조회해 와서** 엔트리포인트를 import 하고 호출한다.

> **범위**: `RUNTIME_KIND ∈ {compiled_graph, adk}` — **Bundle 모드 전용**. Image 모드(`custom`) pool은 admin이 빌드한 별도 OCI 이미지가 직접 운영되며 agent-base와 무관. Image 모드 contract는 [backend/DESIGN.md](../../backend/DESIGN.md)의 "Custom Image 관리" 참조.

## 설계

- **이미지 1개, 하드웨어적 분리는 Deployment 단위**. 각 Deployment는 `RUNTIME_KIND` env로 자기 정체성을 정한다: `compiled_graph` / `adk` / `custom`.
- **요청 처리** (`POST /invoke`)
  - payload: `{agent, version?, input, session_id?, principal}` — 식별자만 받는다. 번들 정보는 안 받는다.
  1. **`DeployApiClient.resolve(kind='agent', name=agent, version=version, principal=principal.id)`** → `{source, user}` 획득.
  2. `source.runtime_pool`이 `agent:{RUNTIME_KIND}`와 일치하는지 검증. 불일치 시 400.
  3. `BundleLoader.load(source)` — 디스크 캐시에 없으면 `bundle_uri`에서 zip 다운로드·체크섬 검증·압축 해제·`sys.path` 추가·`module:attr` import.
  4. 로더가 리턴한 `factory`를 **`factory(cfg, secrets)` 형태**로 호출해서 instance 얻음.
     - `cfg` = `runtime_common.factory.merge_configs(source.config, user.config if user else None)` — **shallow merge, user가 같은 키면 덮어씀**. source-only / user-only 키는 그대로 유지. 자세한 합의는 [/DESIGN.md](../../DESIGN.md)의 "source_meta / user_meta config 병합".
     - `secrets` = `SecretResolver` 인스턴스 (실제 비밀값은 `user.secrets_ref`에서 lazy resolve)
     - 하위호환: zero-arg factory / `(cfg,)` 1-arg factory도 인트로스펙션으로 허용 — `runtime_common.factory.call_factory`가 시그니처 자동 분기.
  5. `runner.run(kind, instance, input, session_id)` — kind별 어댑터가 프레임워크-네이티브 호출.
     - `compiled_graph` → LangGraph `CompiledGraph.ainvoke(input, config={"configurable": {"thread_id": session_id}})`. **체크포인터는 Redis** — 번들 내 factory가 `runtime_common.providers.langgraph.build_checkpointer(cfg, secrets)` 로 구성해서 `CompiledGraph`에 붙인다. 대화 상태가 pod-local이 아니므로 다음 턴이 다른 pod로 가도 정상 동작 → **pod affinity 불필요, graceful drain·scale-down이 단순**. DeepAgents (`create_deep_agent`) 도 동일 풀에서 동작 — 반환 타입이 `CompiledStateGraph` 라 어댑터 분기 불필요.
     - `adk` → ADK `LlmAgent` 를 `Runner(agent=..., session_service=InMemorySessionService())` 로 감싸 `runner.run_async(...)`. 번들은 agent 만 반환하면 된다 (Runner 는 agent-base 가 만든다).
     - `custom` → `.ainvoke(input)` 또는 callable

- **이미지에 사전설치되는 framework / provider deps**:
  - `langgraph>=1.0`, `deepagents>=0.5`, `google-adk>=0.1.0`
  - `langchain-anthropic`, `langchain-openai` — `init_chat_model` 이 `cfg.langgraph.model` 의 `provider:` 접두어로 자동 분기. 새 provider 지원 시 이 deps 목록을 늘린다 (번들에 두지 말 것 — cold-start 비용·중복).
  - ADK 가 비-Gemini 모델을 부를 때는 번들 코드가 `LiteLlm("openai/...")` / `LiteLlm("anthropic/...")` 으로 wrap. `litellm` 은 `google-adk` 의존으로 따라온다.
- **캐시**:
  - 번들: pod당 `BUNDLE_CACHE_MAX`(기본 16)개 버전을 디스크 + 인-프로세스 import 캐시로 유지. 키는 `source.checksum`.
  - **user_meta는 매 invoke마다 fresh 조회** (짧은 TTL 로컬 캐시는 옵션). 번들과 수명이 다르기 때문.
- **Postgres에 붙지 않는다**. `DEPLOY_API_URL`만 알면 됨.
- **cold-start**: 첫 호출 시 번들 fetch + import 비용 발생. warm이면 resolve RTT + 해시 lookup만.

### JWT forwarding (MCP 호출 시)

factory가 리턴한 instance가 실행 중 mcp-gateway로 tool 호출을 보낼 때 **사용자 JWT를 그대로 forward**. 서비스 간 별도 토큰을 발급하지 않는다.

- pool pod는 `/invoke` 진입 시 받은 `Authorization` 헤더를 **request-scoped**로 보관(LangGraph `config` 또는 contextvar)하고, MCP 호출 시점에 그대로 `Authorization: Bearer <same jwt>`로 재사용.
- **내부 경로**를 호출: `POST {MCP_GATEWAY_URL}/v1/mcp/invoke-internal` (엣지 경로 아님). 추가로 `X-Runtime-Caller: agent-pool` 헤더를 감사용으로 실음. pool Deployment만 NetworkPolicy로 이 경로에 도달 가능.
- **grace period 기대**: 내부 경로이므로 mcp-gateway가 `AuthClient.verify(token, grace_sec=300)` 로 검증 → 한 턴이 LLM 스트리밍 + 다중 tool call로 토큰 TTL을 넘겨도 401 없이 완주. 세부 정책은 [/DESIGN.md](../../DESIGN.md)의 "내부 호출의 토큰 Grace Period".
- **토큰 재발급 금지**: pool은 auth `/login`을 모르고 사용자 credential도 없다. 동일 JWT를 turn 범위 내에서만 재사용.
- **다음 turn에서는 새 토큰**: user의 다음 `/v1/agents/invoke` 는 UI가 fresh 토큰으로 보냄. grace는 "한 turn 안에서만" 효과.

### LLM 관찰가능성 (Opik)

OTel(`telemetry.py`)은 **인프라 지표**만 담당한다. LLM call trace·토큰 사용량·프롬프트/응답은 **Opik SDK**로 분리해 Opik 백엔드(`opik.monitoring.svc.cluster.local:5173`)로 전송한다.

#### 기동 시 초기화

lifespan에서 `configure_opik()` 호출(OTel 초기화 직후):

```python
from runtime_common.opik_tracing import configure_opik
configure_opik(settings.opik_url, settings.opik_workspace)
```

`OPIK_URL_OVERRIDE` 미설정 시 no-op — dev 환경에서 Opik 없어도 기동 가능.

#### invoke 경계에서 trace 열기

`/invoke` 핸들러에서 `opik_trace_context()` context manager로 감싼다:

```python
from runtime_common.opik_tracing import opik_trace_context

async with opik_trace_context(
    name=f"agent:{req.agent}",
    project_name=req.agent,          # Opik 프로젝트 = 에이전트명
    session_id=req.session_id,       # → Opik thread_id (대화 연속성)
    user_id=str(principal.user_id),
    metadata={"version": req.version, "runtime_kind": settings.runtime_kind},
):
    result = await run(...)
```

Opik SDK는 `contextvars.ContextVar`를 사용하므로 FastAPI asyncio task 단위로 자동 격리. 동시 invoke 간 trace 혼용 없음.

#### LangGraph runner 연동

`runner.py`의 `compiled_graph` 분기에서 `OpikTracer`를 LangGraph callback으로 주입:

```python
from opik.integrations.langchain import OpikTracer

tracer = OpikTracer(
    project_name=agent_name,
    thread_id=session_id,
    opik_context_read_only_mode=True,  # async LangGraph 노드에서 context 오염 방지
)
result = await graph.ainvoke(
    input,
    config={
        "configurable": {"thread_id": session_id},
        "callbacks": [tracer],          # LangGraph → LangChain callback → Opik
    },
)
```

`opik_context_read_only_mode=True` 필수 — LangGraph의 asyncio task 분기로 인해 Opik ContextVar를 자식 task에서 수정하면 부모 context와 충돌 가능.

#### 데이터 흐름

```
/invoke
  └─ opik_trace_context (invoke 외곽 span, project=agent_name, thread_id=session_id)
       └─ runner.run()
            └─ graph.ainvoke(callbacks=[OpikTracer])
                 ├─ LangGraph node spans (자동 계측)
                 └─ LLM call spans (Anthropic/OpenAI 자동 계측)
```

#### 설정 (env)

| 변수 | 설명 | 기본값 |
|---|---|---|
| `OPIK_URL_OVERRIDE` | Opik 서버 URL | 없음 (비활성) |
| `OPIK_WORKSPACE` | Opik workspace | `default` |
| `OPIK_TRACK_DISABLE` | 전체 비활성 | `false` |

### warm-registry 퍼블리시 (스케줄러와의 계약)

gateway 쪽 warm-aware 스케줄러(전체 방향은 [/DESIGN.md](../../DESIGN.md)의 "확장 로드맵" 참조)가 **"어떤 pod가 어떤 checksum을 load했고 지금 얼마나 바쁜지"** 를 보게 하려면 pod가 Redis에 상태를 **저장 + 이벤트 발행** 해야 한다.

- **키/채널 규약** (agent/mcp 공용):
  ```
  rt:warm:agent_{RUNTIME_KIND}:{checksum}  SET of pod_id          TTL 3s   # 상태
  rt:load:{pod_id}                         HASH {active,max,addr} TTL 3s   # 상태
  rt:events:agent_{RUNTIME_KIND}           Pub/Sub snapshot/down JSON       # 이벤트
  ```
- **HASH 필드**: `active` = 현재 진행 중 요청 수, `max` = `MAX_CONCURRENT`, `addr` = `"POD_IP:PORT"`. gateway가 pod_id에서 바로 연결 주소를 얻도록 HASH에 함께 실음.
- **쓰는 시점**: 백그라운드 태스크에서 1~2초 주기 — 같은 틱 안에서 둘 다 수행:
  1. **상태 저장**: `BundleLoader.warm_checksums()`의 각 checksum에 대해 `SADD rt:warm:agent_{RUNTIME_KIND}:{cs} {pod_id}` + `EXPIRE 3`, 그리고 `HSET rt:load:{pod_id} active=... max=... addr=...` + `EXPIRE 3`. LRU에서 밀려난 checksum은 TTL로 자연 소멸.
  2. **이벤트 발행**: `PUBLISH rt:events:agent_{RUNTIME_KIND}` 에 snapshot JSON
     ```json
     {"type":"snapshot","pod_id":"<pod>","addr":"<ip:port>","active":N,"max":M,"checksums":["sha256:a", ...],"ts":...}
     ```
     gateway의 `RegistrySubscriber`가 이걸 받아 메모리 라우팅 테이블을 갱신 → per-invoke Redis 왕복 제거.
- **active 카운터**: `/invoke` 진입/종료에서 증감. 세마포어와 동일한 카운터(`runtime_common.registry.ActiveCounter`)를 재사용.
- **pod_id**: Kubernetes가 주는 `POD_NAME` (downward API) 또는 `HOSTNAME`. endpoint 주소 `addr`은 `POD_IP` + 서버 리스닝 포트 조합.
- **shutdown**: `preStop`에서 `PUBLISH rt:events:... {"type":"down","pod_id":"<pod>","ts":...}` 한 번 → heartbeat 중단 → 3초 내 상태 TTL 자연 소멸. `SREM` + `DEL rt:load:{pod_id}`는 선택적 optimization (빠른 제거).
- **재사용**: 이 퍼블리시 로직(상태 + 이벤트)은 mcp-base와 공유 → `runtime_common.registry.RegistryPublisher` 모듈로 분리.

