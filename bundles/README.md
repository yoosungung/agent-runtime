# bundles — 운영용 번들

실제 업무에 배포·운영하는 agent / MCP 번들 모음.

`deploy/examples/` 와 **같은 런타임 계약**(`build_agent` / `build_server`, `source_meta`, zip 배포)을 따르지만 목적이 다르다.

| | `deploy/examples/` | `bundles/` |
|---|---|---|
| 목적 | 프레임워크·런타임 **학습용** 샘플 | **운영** — 실제 업무 자동화 |
| 특성 | 키 없이 CI 가능, 코드 최소 | 외부 API·OAuth·조직 자격증명 |
| 대상 | 온보딩, e2e smoke, provider 패턴 시연 | 프로덕션 등록·principal별 접근 제어 |

## 레이아웃

```
bundles/
├── mcp/          MCP 서버 번들 (mcp:fastmcp, mcp:mcp_sdk, …)
└── agent/        Agent 번들 (agent:compiled_graph, agent:adk, …)
```

각 `<name>_bundle/` 디렉토리:

- `app.py` — `app:build_server` 또는 `app:build_agent` 엔트리포인트
- `pyproject.toml` — 번들 전용 deps (베이스 이미지에 없는 패키지)
- (선택) README — config·시크릿·운영 절차

## 배포

배포 절차 정본: [deploy/examples/mcp-base/README.md](../deploy/examples/mcp-base/README.md) (zip → upload → `source_meta` 등록 → ACL·`user_meta`).

## 테스트

단위 테스트는 `deploy/examples/tests/` 에 두되, `load_bundle("mcp/email_bundle", …)` 처럼 `bundles/` 경로를 사용한다. conftest 가 `deploy/examples/` 다음 `bundles/` 를 순서대로 탐색한다.

## 번들 목록

| 경로 | kind | name (예) | runtime_pool | 상태 |
|------|------|-----------|--------------|------|
| [mcp/email_bundle](mcp/email_bundle/) | mcp | `email-server` | `mcp:mcp_sdk` | 구현됨 |

Agent 번들은 [agent/README.md](agent/README.md) 참조.
