# bundles/agent — 운영 Agent 번들

업무 자동화용 agent 번들. agent-base pool(`agent:compiled_graph`, `agent:adk`, …)에 배포한다.

**런타임 계약** — [deploy/examples/agent-base/README.md](../../deploy/examples/agent-base/README.md) 와 동일. `source_meta.config` / `user_meta` 층은 [ARCHITECTURE.md](../../ARCHITECTURE.md) §5.

## 패턴

운영 agent 는 보통 다음을 조합한다.

- **자체 툴** — 도메인 로직, 사내 API 래퍼
- **MCP 툴** — `bundles/mcp/` 에 등록된 서버 (예: `email-server`, `search-server`)
- **subagent** — (선택) DeepAgents 위임

`source_meta.config` 예:

```json
{
  "langgraph": {"model": "openai:gpt-4o", "checkpointer": "postgres"},
  "mcp_server": "email-server"
}
```

## 번들 목록

| 경로 | kind | name | runtime_pool | 상태 |
|------|------|------|--------------|------|
| — | — | — | — | (추가 예정) |

---

리서치·산술 데모 agent 는 [deploy/examples/agent-base/](../../deploy/examples/agent-base/) 를 본다.
