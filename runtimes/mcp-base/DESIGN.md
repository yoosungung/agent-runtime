# mcp-base

MCP-Pool의 베이스 이미지. 구조는 agent-base와 평행 — 같은 Lambda 스타일 동적 로딩, 다만 호스팅하는 대상이 MCP 서버(FastMCP / MCP SDK / DidimRAG / T2SQL).

> **범위**: `RUNTIME_KIND ∈ {fastmcp, mcp_sdk, didim_rag, t2sql}` — **Bundle 모드 전용**. Image 모드(`custom`) MCP pool은 admin이 빌드한 별도 OCI 이미지가 직접 운영되며 mcp-base와 무관. Image 모드 contract는 [backend/DESIGN.md](../../backend/DESIGN.md)의 "Custom Image 관리" 참조.

## 설계

- `RUNTIME_KIND` env가 pod 정체성을 정함: `fastmcp` / `mcp_sdk` / `didim_rag` / `t2sql`.
- **요청 처리** (`POST /invoke`)
  - payload: `{server, version?, tool, arguments, principal}` — 식별자만.
  1. **`DeployApiClient.resolve(kind='mcp', name=server, version=version, principal=principal.id)`** → `{source, user}`.
  2. `source.runtime_pool == "mcp:{RUNTIME_KIND}"` 검증.
  3. 공용 `BundleLoader`로 번들 로드 → `factory` 얻음.
  4. `factory(cfg, secrets)` 호출해 instance 얻음. `cfg` = `runtime_common.factory.merge_configs(source.config, user.config)` — shallow merge, user wins. 자세한 합의는 [/DESIGN.md](../../DESIGN.md)의 "source_meta / user_meta config 병합". zero-arg / 1-arg 하위호환은 `call_factory`가 처리.
  5. `runner.run(kind, instance, tool, arguments)` — kind별 툴 호출 어댑터.
     - `fastmcp` → `instance.call_tool(tool, arguments)`
     - `mcp_sdk` → `instance.dispatch(tool, arguments)` 또는 `request_handlers[tool](arguments)`
     - `didim_rag` / `t2sql` → 자체 프로토콜 `instance.call(tool, arguments)` (duck-typed)
- **Postgres 직결 없음**. `DEPLOY_API_URL`만 사용.
- DidimRAG/T2SQL은 MCP 표준 위가 아닌 **내부 convention**으로 취급. 외부 infra(DidimRAG 스토리지, postgres pgvector)에 붙을 때 클라이언트 코드가 번들 안에 들어간다.

### LLM 관찰가능성 (Opik)

MCP tool call은 LLM 호출이 아니므로 agent-base보다 가볍게 적용한다. tool call 경계에서 **span 단위**만 찍는다.

```python
from runtime_common.opik_tracing import configure_opik
import opik

# lifespan
configure_opik(settings.opik_url, settings.opik_workspace)

# /invoke 핸들러
with opik.start_as_current_span(
    name=f"mcp:{req.server}/{req.tool}",
    type="tool",
    project_name=req.server,
    metadata={"tool": req.tool, "version": req.version},
    input=req.arguments,
) as span_data:
    result = await run(...)
    span_data.output = result
```

`configure_opik()` 초기화는 `runtime_common.opik_tracing.configure_opik()`를 공유한다.

### warm-registry 퍼블리시

agent-base와 동일 규약. 상태 + 이벤트 양측 발행:
- 상태: `rt:warm:mcp_{RUNTIME_KIND}:{checksum}` / `rt:load:{pod_id}` (HASH: `{active, max, addr}`, TTL 3s).
- 이벤트: `PUBLISH rt:events:mcp_{RUNTIME_KIND}` 에 snapshot JSON — mcp-gateway의 `RegistrySubscriber`가 구독해 메모리 라우팅 테이블 유지.

`runtime_common.registry.RegistryPublisher` 공용 모듈 사용. 자세한 내용은 [../agent-base/DESIGN.md](../agent-base/DESIGN.md)의 같은 섹션 참조.

MCP는 세션 개념이 없어 active 카운터는 현재 진행 중인 tool call 수만 반영 — 단순.

