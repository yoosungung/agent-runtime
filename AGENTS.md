# AGENTS.md

This file provides guidance to AI coding assistants (Claude Code, Codex, Gemini, ...) when working with code in this repository. `CLAUDE.md`와 `GEMINI.md`는 이 파일로의 심볼릭 링크다 — 정본은 `AGENTS.md` 하나.

에이전트·기여자가 **무엇을 어디서 읽고 어떻게 실행하는지**만 담는다. 불변 규칙은 [ARCHITECTURE.md](ARCHITECTURE.md), 일정은 [ROADMAP.md](ROADMAP.md).

## 1. Documentation layout (문서 용도)

각 문서는 하나의 명확한 용도만 가진다. 같은 내용을 여러 문서에 중복하지 않는다. 한쪽을 고칠 때 다른 쪽이 같이 바뀌어야 한다면 잘못 나눈 것이므로 합치거나 한쪽이 다른 쪽을 참조하게 만든다.

| 파일 | 용도 | 위치 |
|------|------|------|
| `AGENTS.md` (이 파일, 정본) ← `CLAUDE.md`, `GEMINI.md` 심볼릭 | 수행 방법 + 문서 레이아웃 + 현황 | 루트 |
| `ARCHITECTURE.md` | **계약사항(불변 규칙)** + 컴포넌트 *간* 인터페이스 형태(스키마·레이아웃·이벤트) | 루트 |
| `README.md` | 저장소 방문자용 소개 + 로컬 quickstart | 루트 |
| `ROADMAP.md` | 수행 계획(마일스톤·순서·미결정 항목) | 루트 |
| `backend/DESIGN.md` | admin BFF *내부* 설계 + `## Commands` | `backend/` |
| `frontend/DESIGN.md` | admin SPA *내부* 설계 + `## Commands` | `frontend/` |
| `deploy/DESIGN.md` | k8s·examples *내부* 설계 + `## Commands` | `deploy/` |
| `packages/common/DESIGN.md` | `runtime_common` *내부* 설계 + `## Commands` | `packages/common/` |
| `services/auth/DESIGN.md` | auth 서비스 *내부* | `services/auth/` |
| `services/deploy-api/DESIGN.md` | deploy-api *내부* | `services/deploy-api/` |
| `services/ext-authz/DESIGN.md` | ext-authz *내부* | `services/ext-authz/` |
| `runtimes/agent-base/DESIGN.md` | agent-base *내부* | `runtimes/agent-base/` |
| `runtimes/mcp-base/DESIGN.md` | mcp-base *내부* | `runtimes/mcp-base/` |

규칙:

- **ARCHITECTURE.md §1 (계약) vs §2 이후 (형태).** §1은 "지켜야 하는 규칙(왜)" — 짧고 단정적. §2 이후는 "그 규칙을 구현하는 모양(어떻게)" — 스키마·필드·이벤트 목록. 규칙이 바뀌면 §1을 먼저 고치고 §2 이후를 따라 고친다. 두 부분을 다른 파일로 쪼개면 동기화 부담만 늘어 단일 문서로 둔다.
- **ARCHITECTURE.md vs `<comp>/DESIGN.md`.** ARCHITECTURE는 컴포넌트 *간*, 서브폴더 DESIGN은 해당 컴포넌트 *내부*. 두 쪽에 같은 내용을 적지 않는다.
- **README.md vs ARCHITECTURE.md / DESIGN.md.** README는 **인간 독자**(저장소 방문자·기여자)용이다. 계약·내부 설계는 README에 복사하지 않고 [ARCHITECTURE.md](ARCHITECTURE.md)·`<comp>/DESIGN.md`로 **링크만** 한다.
- **서브폴더 `README.md`.** `bundles/`, `deploy/examples/`의 leaf 번들·예제, `deploy/examples/tests/e2e/` 등 **배포 가능한 패키지·실행 하네스**에는 README를 둘 수 있다 — 해당 디렉터리 **로컬 사용법만**. 계약·스키마는 ARCHITECTURE/DESIGN 참조. 컴포넌트 루트(`backend/`, `deploy/` 등)에는 README 대신 `DESIGN.md`만.
- 파일이 새로 생기거나 용도가 바뀌면 위 표를 즉시 갱신한다.
- 배포 런북은 `deploy/SETUP.md`, Kustomize 베이스는 `deploy/k8s/base/`, PR/push CI는 `.github/workflows/ci.yml`. 빈 stub을 만들지 않는다.

## 2. 수행 방법 (How we work in this repo)

- 계획·설계·구현 변경은 해당 문서를 먼저(또는 함께) 고친다: 계획 변경 → `ROADMAP.md`, 설계·규칙 변경 → `ARCHITECTURE.md`(또는 해당 컴포넌트의 `DESIGN.md`), 워크플로 변경 → 이 파일.
- 코드가 처음 들어오는 컴포넌트는 그 폴더의 `DESIGN.md`를 함께 만들고, 이 파일의 §1 표 또는 `ARCHITECTURE.md` §1 계약사항을 필요 시 갱신한다.
- 컴포넌트에 첫 코드가 들어오면, 해당 폴더의 `DESIGN.md`에 **`## Commands`** 섹션을 추가해 빌드/실행/테스트 방법을 기록한다. 그 전까지는 비워둔다(존재하지 않는 명령을 만들어 적지 않는다).
- 개발은 TDD 방식으로 진행한다. (코드 스켈레톤 → 테스트 코드 → 기능 구현)
- 한국어/영어 혼용을 허용한다. 한 문서 내 일관성만 지킨다(현재 AGENTS/ARCHITECTURE/ROADMAP/DESIGN은 한국어 본문 + 영어 식별자).

### 개발 환경

- **Python**: 3.12 고정 (`.python-version`).
- **패키지 매니저**: uv — `uv sync --all-packages`. 워크스페이스 멤버는 `pyproject.toml`의 `[tool.uv.workspace].members`.
- **자주 쓰는 명령**: `make sync` / `make lint` / `make fmt` / `make typecheck` / `make test`
  - 이미지 빌드: GitHub Release publish → GHA (`.github/workflows/build-images.yml`)
  - k8s: `make k8s-apply-dev` / `make k8s-rollout-restart`
  - DB: `make db-migrate-all`
  - GHCR pull secret: `GITHUB_USER=... GITHUB_PAT=... make registry-secret`
- **로컬 단일 서비스**: `uv run uvicorn backend.app:app --reload --port 8000` (모듈 경로는 각 `pyproject.toml` wheel target 참고)

### 코드 컨벤션

- `src/` 레이아웃. 패키지명은 하이픈 X, 언더스코어 O (`agent-gateway` → `agent_gateway`).
- 공용 로직은 `packages/common` (`runtime_common.*`). 서비스·런타임 중복 시 여기로 옮긴다.
- `ruff` isort first-party는 루트 `pyproject.toml` — 새 워크스페이스 패키지 추가 시 등록.
- 테스트: `pytest-asyncio`, `asyncio_mode = "auto"`.

### ROADMAP와 DESIGN 동기화

- 작업 전 해당 폴더의 `DESIGN.md`를 확인한다. 설계 반영이 필요하면 작업 전에 수정한다.
- `ROADMAP.md` 할일을 확인하고 진행상황을 업데이트한다.
- 완료된 ROADMAP 항목은 해당 `DESIGN.md`에 합성하고 ROADMAP에서 삭제한다. 남은 작업은 향후 계획으로 이동한다.

## 3. Status

현재 프로젝트는 실 운영 및 개선 단계.
