# hermes-agent 벤더링

upstream [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)를 **항상 최신 main** 기준으로 가져와 패치 적용.

## 디렉터리

```text
vendor/hermes-agent/
  DESIGN.md          # 이 파일
  REVISION           # 마지막 적용 commit SHA (CI가 갱신)
  patches/           # git format-patch 또는 unified diff
    0001-runtime-profile-scope.patch
```

## 워크플로

```bash
./scripts/vendor-hermes.sh           # clone/pull main → apply patches → editable install
./scripts/vendor-hermes.sh --pin abc123  # 특정 SHA (디버그용)
```

`vendor-hermes.sh` 동작:

1. `vendor/hermes-agent/src/`에 shallow clone (`--depth 1`) 또는 pull
2. `patches/*.patch` 순서대로 `git apply` (실패 시 중단)
3. `REVISION` 파일에 `git rev-parse HEAD` 기록
4. `uv pip install -e vendor/hermes-agent/src`

## 패치 원칙

- **최소 diff**: upstream PR 가능한 것은 upstream 먼저.
- **패치 이름**: `NNNN-area-summary.patch`
- **금지**: 대규모 리팩터, 기능 추가를 패치로만 유지 (plugin으로 대체).

## Phase 1 필수 패치 (예정)

| 패치 | 목적 |
|------|------|
| `runtime-profile-scope` | embed 모드에서 `HERMES_HOME` contextvar 공개 API |
| (없을 수 있음) | Postgres session — upstream 지원 시 패치 불필요 |

## Runtime-slim install (예정 — [ROADMAP.md](../../ROADMAP.md) P1)

hermes-base OCI는 **gateway/dashboard/CLI를 실행하지 않는다**. 기본 `pip install -e`는 해당 **Python 패키지·에셋·deps**까지 wheel에 실리므로 이미지가 커진다.

- 설치: core only — `[gateway]` `[web]` `[messaging]` `[all]` **금지**
- Dockerfile: vendor stage `git` 제거, prune 스크립트로 `gateway/`, `hermes_cli/`, `tui_gateway/`, `acp_adapter/` 삭제 후 import 스모크
- 목표: `hermes-agent[runtime]` extra — `run_agent`, `agent/`, `tools/`(선택), SessionDB deps만

## Dockerfile

멀티스테이지:

1. `vendor` stage: `vendor-hermes.sh` 실행
2. `app` stage: `uv sync --package hermes-base`

CI는 매 빌드마다 `main` pull → 패치 → 이미지 태그 = agents-runtime git SHA + hermes REVISION을 label로 기록:

```dockerfile
LABEL org.opencontainers.image.revision="${GIT_SHA}"
LABEL dev.hermes-agent.revision="${HERMES_REVISION}"
```

## 로컬 개발 without vendor

테스트는 `AIAgent`를 mock하여 `ProfileMaterializer`·`/invoke` contract만 검증. 통합 테스트는 vendored install 후 `@pytest.mark.integration`.
