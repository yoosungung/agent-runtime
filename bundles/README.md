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

## import 규칙 (pool 런타임)

pool pod의 `BundleLoader`는 checksum별 namespace(`_rt_bundle_{checksum}`)로 번들을 격리 로드한다. 번들 작성 시:

- zip 루트 기준 **절대 import** 사용 — `from utils import …`, `from providers.outlook import …` (현재 `email_bundle` 등과 동일 패턴).
- `runtime_common.*`, `httpx` 등 **베이스/워크스페이스 패키지**는 그대로 import.
- pool 배포 시 `sys.path` 조작 **불필요** — `app.py`의 `sys.path.insert`는 로컬 단독 실행용이며 런타임 loader가 무시한다.
- import 중 백그라운드 스레드에서 추가 import를 하면 namespace 격리가 깨질 수 있으므로 factory/build 시점 import는 동기로 유지.

상세: [packages/common/DESIGN.md](../packages/common/DESIGN.md) `bundle_import.py`.

## zip 만들기

`entrypoint`가 `app:build_server` / `app:build_agent`이면 **`app.py`가 zip 루트**에 있어야 한다. 디렉터리 이름으로 한 겹 감싸면 pool import가 실패한다.

```bash
# 예: bundles/mcp/search_bundle → bundles/mcp/search_bundle.zip
cd bundles/mcp/search_bundle
zip -r ../search_bundle.zip . -x '*/__pycache__/*' '*.pyc' '*/__MACOSX/*'

# 다른 번들도 동일 — <bundle_dir> 안에서 zip -r <출력.zip> .
cd bundles/mcp/email_bundle
zip -r ../email_bundle.zip . -x '*/__pycache__/*' '*.pyc' '*/__MACOSX/*'
```

잘못된 예 (루트에 `search_bundle/app.py`가 들어감):

```bash
# repo 루트나 상위에서 디렉터리 이름을 넣지 말 것
zip -r search_bundle.zip search_bundle   # ❌
```

e2e 헬퍼와 동일: [deploy/examples/tests/e2e/lib.sh](../deploy/examples/tests/e2e/lib.sh) `build_bundle_zip`.

## 배포

배포 절차 정본: [deploy/examples/mcp-base/README.md](../deploy/examples/mcp-base/README.md) (zip → upload → `source_meta` 등록 → ACL·`user_meta`).

## 테스트

단위 테스트는 `deploy/examples/tests/` 에 두되, `load_bundle("mcp/email_bundle", …)` 처럼 `bundles/` 경로를 사용한다. conftest 가 `deploy/examples/` 다음 `bundles/` 를 순서대로 탐색한다.

## 번들 목록

| 경로 | kind | name (예) | runtime_pool | 상태 |
|------|------|-----------|--------------|------|
| [mcp/email_bundle](mcp/email_bundle/) | mcp | `email-server` | `mcp:mcp_sdk` | 구현됨 |
| [mcp/search_bundle](mcp/search_bundle/) | mcp | `search-server` | `mcp:mcp_sdk` | 구현됨 |
| [mcp/calendar_outlook_bundle](mcp/calendar_outlook_bundle/) | mcp | `calendar-outlook` | `mcp:mcp_sdk` | 구현됨 |
| [mcp/calendar_google_bundle](mcp/calendar_google_bundle/) | mcp | `calendar-google` | `mcp:mcp_sdk` | 구현됨 |
| [mcp/teams_bundle](mcp/teams_bundle/) | mcp | `teams-server` | `mcp:mcp_sdk` | 구현됨 |

Agent 번들은 [agent/README.md](agent/README.md) 참조.
