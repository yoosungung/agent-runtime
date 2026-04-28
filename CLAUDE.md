# CLAUDE.md

## 프로젝트 목표

LLM 에이전트/MCP 서버를 위한 **런타임 플랫폼**. base image에 사용자 코드를 동적 배포해서 실행(AWS Lambda 방식). LLM, RAG 인프라는 scope 밖.

**예외**: 플랫폼 운영용 관리 콘솔은 이 저장소에 포함한다 — `frontend/`(React+Vite SPA), `backend/`(FastAPI BFF). 런타임 데이터플레인과는 분리된 컴포넌트로 취급.

컴포넌트별 상세는 각 폴더의 `DESIGN.md` 참조. 아키텍처 그림은 `agent-runtime.d2`.

## 개발 방법

- **Python**: 3.12 고정 (`.python-version`). 그 외 버전 쓰지 말 것.
- **패키지 매니저**: uv. 워크스페이스 멤버는 `pyproject.toml`의 `[tool.uv.workspace].members` 참조.
- **첫 셋업**: `uv sync --all-packages`
- **자주 쓰는 명령**
  - `make sync` / `make lint` / `make fmt` / `make typecheck` / `make test`
  - 이미지 빌드: `make images` (개별: `make agent-base-image` 등)
  - k8s 배포: `make k8s-apply-dev`
  - DB 마이그레이션: `make db-migrate`
- **로컬에서 단일 서비스 실행**:
  `uv run uvicorn agent_gateway.app:app --reload --port 8080`
  (다른 서비스도 동일 패턴 — 모듈 경로는 각 `pyproject.toml`의 wheel target 참고)
- **코드 구현** : 
  - 작업 전 해당 폴더의 `DESIGN.md`를 반드시 확인한다. 현재 진행중인 작업이 설계에 반영이 필요하다고 판단되면 `DESIGN.md` 파일을 작업 수행 전에 수정한다. 
  - 개발 에이전트들이 동시에 작업하니, 각 에이전트는 `ROADMAP.md` 파일의 할일을 매번 확인하고 진행상황을 업데이트 해야한다.
  - 완료된 ROADMAP 내용은 해당 DESIGN.md에 합성하고, ROADMAP에서 삭제, 남은 작업은 향후 계획으로 이동시킨다.

## 코드 컨벤션

- `src/` 레이아웃. 패키지명은 하이픈 X, 언더스코어 O (`agent-gateway` 디렉토리 → `agent_gateway` 모듈).
- 공용 로직은 `packages/common` (`runtime_common.*`)에 넣는다. 서비스/런타임에 중복 생기면 여기로 옮긴다.
- `ruff` isort의 first-party 목록은 루트 `pyproject.toml`에 있음 — 새 워크스페이스 패키지 추가하면 거기도 등록.
- 테스트는 `pytest-asyncio`, `asyncio_mode = "auto"`.

## 꼭 알아야 할 내부 계약

- **runtime_pool 식별자 포맷**: `"{kind}:{runtime_kind}"` (예: `agent:compiled_graph`, `mcp:fastmcp`). `source_meta.runtime_pool` 컬럼과 pod의 `RUNTIME_KIND` env가 이 규약으로 맞물린다. 새 kind 추가하려면 `runtime_common.schemas`의 enum, 해당 gateway의 router, 해당 base image의 runner, k8s pool Deployment 네 곳을 함께 업데이트.
- **번들 엔트리포인트 포맷**: `"module.path:attr"` — attr은 factory. 시그니처는 `(cfg: dict, secrets: SecretResolver) -> NativeObj` (하위호환으로 zero-arg·1-arg도 허용). `cfg`는 `source_meta.config`와 `user_meta.config`를 runtime이 shallow merge(user wins)한 결과 — 번들 기본값 + per-principal 덮어쓰기. agent는 프레임워크-네이티브 객체(CompiledGraph 등), mcp는 서버 객체를 반환.
- **베이스 이미지는 이미지 1개 + `RUNTIME_KIND` env**. kind별로 이미지 따로 찍지 않는다.
- **런타임 메타 조회는 deploy-api `/v1/resolve` 단일 경로**. gateway·agent-base·mcp-base 누구도 Postgres에 직접 붙지 않는다. **deploy-api는 read-only** — `source_meta`/`user_meta` **쓰기는 admin backend만**. 런타임 크리티컬 경로(deploy-api)와 쓰기 소유자(admin backend)를 분리해 장애 격리. `source_meta`(코드 정의)는 immutable·versioned, `user_meta`(사용자별 config·secrets_ref)는 mutable — 수명이 다름.
- **사용자/권한 테이블도 동일 규칙**. auth는 `/login`·`/verify`를 위해 `users`·`user_resource_access` **read-only**. 쓰기(사용자 생성·삭제·권한 부여/회수·비밀번호 변경)는 **admin backend만**. `refresh_tokens`는 예외로 auth가 소유(런타임 세션 상태). admin이 비밀번호 변경·계정 비활성 시 auth의 `POST /admin/revoke-tokens` 브릿지 경로를 호출해 refresh token을 revoke.
- **pool `/invoke` payload는 식별자만**: agent는 `{agent, version, input, session_id, principal}`, mcp는 `{server, version, tool, arguments, principal}`. meta는 pool이 deploy-api에 **재조회**해서 가져온다 — gateway 경유 payload에 신뢰 못 할 번들 정보를 섞지 않기 위함.

## 이것만은 하지 말 것

- 루트 외 위치에 `.venv` 만들지 말 것(uv가 루트에 단일 venv 관리).
- pool별 이미지를 만들지 말 것 — env로만 분기.
- `source_meta`/`user_meta`/`users`/`user_resource_access`에 런타임 서비스(gateway·pool·deploy-api·auth)가 직접 INSERT/UPDATE 하지 말 것 — 쓰기 소유자는 admin backend. `refresh_tokens`만 예외로 auth 전용.
- LLM/RAG 코드를 이 저장소에 추가하지 말 것 — scope 밖. (관리 콘솔 `frontend/`·`backend/`는 예외.)
