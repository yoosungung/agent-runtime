# ROADMAP

전체 DESIGN.md에서 수집한 미완료 항목. 세부 맥락은 각 컴포넌트 DESIGN.md 참조.

게이트웨이 통합(ext-authz + Envoy로 데이터플레인 일원화) 3단계가 완료되어 agent-gateway·mcp-gateway가 제거됐다. 완료된 내용은 [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md), [deploy/DESIGN.md](deploy/DESIGN.md), [backend/DESIGN.md](backend/DESIGN.md)에 합성됨.

## 향후 계획

### `custom` pool 의미 전환 — admin이 빌드한 base-image를 직접 운영하는 체계

> 현재 `agent-pool-custom` / `mcp-pool-custom`은 다른 pool과 동일한 **bundle 모드**(공용 base-image + 동적 번들 로드)다. 이를 **image 모드**로 의미를 바꾼다 — 플랫폼 운영자(admin)가 자기 코드를 박은 OCI 이미지를 빌드해 등록하면, backend가 K8s Deployment+Service를 동적으로 생성해 그 이미지가 곧 agent/MCP 노드가 된다. 두 체계는 **공존**한다.

#### 두 체계 비교 (목표 상태)

| 측면 | Bundle 모드 (`compiled_graph` / `adk` / `fastmcp` / `mcp_sdk`) | Image 모드 (`custom`) |
|---|---|---|
| 작성자 | end developer (사용자 팀) | platform admin |
| 배포 단위 | tar.gz bundle, S3/OCI registry | Docker image, OCI registry |
| Pool Deployment | kind당 1개, 여러 번들 호스팅 | image당 1개 (admin 등록 시 생성) |
| 코드 적재 | 런타임 BundleLoader (cold-start 1회) | 빌드 타임 — image에 박혀 있음 |
| `runtime_pool` 식별자 | `{kind}:{runtime_kind}` 예 `agent:compiled_graph` | `{kind}:custom:{slug}` 예 `agent:custom:summarizer` |
| Service 이름 | `{kind}-pool-{runtime_kind}` (정적) | `{kind}-pool-custom-{slug}` (동적) |
| warm-registry | 사용 (ring-hash by checksum) | 미사용 — 모든 pod 동일하므로 단순 LB |
| K8s 리소스 | 정적 kustomize | backend가 K8s API로 동적 CRUD |
| `cfg`/`secrets`/`user_meta` | 동일 (deploy-api `/v1/resolve`) | 동일 — image 안의 SDK가 호출 |
| HPA/KEDA | pool-level metric | image-level metric (`service_name`별) |

업계 reference: **Knative ksvc**(image + autoscaling을 CRD 한 단위로 묶는 패턴)에 가장 가깝지만, Knative 의존을 들이는 대신 backend의 admin path가 동일 책임을 직접 진다. **AWS Lambda Container Image**는 poll-based runtime API라 푸시-호출 모델인 우리와 contract가 다르다 — 단, "관리되는 base-image가 있고, 사용자는 거기에 layer를 얹는다"는 발상은 채택한다.

#### Image contract — admin이 만들어야 하는 image의 약속

- **HTTP**: `POST /invoke`, `GET /healthz`, `GET /readyz` (포트 8080). 요청 body는 `{Agent,Mcp}InvokeRequest`와 동일.
- **k8s가 주입할 env**: `RUNTIME_POOL=agent:custom:{slug}`, `DEPLOY_API_URL`, `REDIS_URL`(optional), `POD_*`.
- **principal 전달**: ext-authz가 이미 `x-principal` 헤더를 주입한다 — image는 그걸 신뢰.
- **두 가지 작성법**:
  1. **base-image extend (권장)** — `FROM agents-runtime/agent-base:latest` 후 자기 모듈을 `COPY`하고 `ENV BUNDLED_ENTRYPOINT=mypkg.app:factory`. base-image가 부팅 시 entrypoint를 import해서 factory를 메모리에 박아두고, 이후 `/invoke`는 BundleLoader 우회 + 기존 runner 재사용. → bundle 모드와 동일한 factory 시그니처(`(cfg, secrets) -> NativeObj`)를 그대로 쓰면 된다.
  2. **raw contract** — 임의 언어/프레임워크. 위 HTTP 4개 endpoint와 `cfg` 머지 책임만 본인이 진다. `cfg`/`secrets_ref`는 image가 직접 deploy-api `/v1/resolve`를 호출하거나, ext-authz가 헤더로 첨부(아래 `cfg sidecar` 참조).

#### 작업 항목

##### 1) 스키마 / 식별자 확장

- [ ] **`runtime_pool` 포맷 확장**: `{kind}:custom:{slug}` 허용. `runtime_common.schemas`에 `parse_runtime_pool` helper 추가 → `(kind, runtime_kind, slug?)` 파싱. 기존 bundle 식별자는 `slug=None`.
- [ ] **`source_meta` 컬럼**: `deploy_mode VARCHAR(16) NOT NULL DEFAULT 'bundle'` (`'bundle'|'image'`), `image_uri VARCHAR(512)`, `image_digest VARCHAR(128)` 추가. 기존 `bundle_uri`/`entrypoint`/`checksum`은 `deploy_mode='image'`에서 NULL 허용. CHECK constraint로 mode별 필수 필드 강제.
- [ ] **migration**: backend `0002_*.sql` — 컬럼 추가 + CHECK + 기존 row backfill `deploy_mode='bundle'`.
- [ ] **deploy-api `/v1/resolve` 응답**: `SourceMeta`에 새 필드 노출. image 모드면 `bundle_uri=None`으로 응답 — 호출자가 mode를 보고 분기.

##### 2) base-image의 image-mode 지원

- [ ] **`BUNDLED_ENTRYPOINT` env**: 셋팅되면 부팅 시 1회 import해 `app.state.bundled_factory`에 보관. BundleLoader 경로 미사용.
- [ ] **invoke 분기**: `bundled_factory`가 있으면 BundleLoader/checksum 캐시 스킵 — `/v1/resolve`는 cfg/user_meta만 가져와서 `instance_cache`에 키 `(image_digest, principal_id, user.updated_at)`로 격리.
- [ ] **registry 미참여**: `RegistryPublisher`를 image 모드에서는 시작하지 않는다 (모든 pod 동일하므로 ring-hash 불필요). ext-authz가 Service URL로 직접 라우팅.
- [ ] **healthz 의미 통일**: bundle/image 양쪽 같은 응답 schema (`{status, kind, mode}`) 유지.

##### 3) ext-authz 라우팅 분기

- [ ] **`*:custom:{slug}` 인식**: `mcp_pool_url`/`agent_pool_url`에 slug 들어오면 `{kind}-pool-custom-{slug}.runtime.svc.cluster.local:8080` derive. envvar 기반 매핑 테이블이 아니라 DNS 규칙으로 derive — admin 등록마다 ext-authz 재시작 안 시키기 위해.
- [ ] **warm-registry 스킵**: image 모드는 `scheduler.pick`을 호출하지 않고 `x-pod-fallback-addr`만 Service URL로 채워서 응답. Lua filter가 fallback path로 그대로 라우팅.
- [ ] **(옵션) cfg sidecar 헤더**: raw-contract image 편의용. ext-authz가 resolve 머지된 `cfg`를 base64-JSON으로 `x-runtime-cfg` 헤더에 실어 invoke로 전달. base-image-extend image는 무시 가능.

##### 4) 동적 K8s 리소스 — backend admin path

- [ ] **`POST /api/admin/custom-images`** (admin only):
  payload `{kind, name, version, image_uri, image_digest, slug, replicas, resources, image_pull_secret?, env?}` →
  (a) `source_meta` INSERT (`deploy_mode='image'`, `runtime_pool=f"{kind}:custom:{slug}"`)
  (b) K8s `Deployment` + `Service` + `ScaledObject` + `PodDisruptionBudget` apply
  (c) 실패 시 source_meta rollback (트랜잭션 outbox 또는 saga).
- [ ] **`DELETE /api/admin/custom-images/{kind}/{slug}`**: source_meta retire + K8s 리소스 삭제 (orphan 방지).
- [ ] **K8s client**: `kubernetes` async client (in-cluster service account). 매니페스트 템플릿은 backend 패키지에 Jinja 또는 Python dict로 보관 — kustomize 별도 파일 생성 X.
- [ ] **RBAC**: backend SA에 `runtime` namespace 한정 `deployments`/`services`/`scaledobjects.keda.sh`/`poddisruptionbudgets` `create/update/delete/get/list` 권한. 새 Role+RoleBinding 매니페스트 추가.
- [ ] **NetworkPolicy 갱신**: dynamically 생성되는 `agent-pool-custom-*` / `mcp-pool-custom-*` pod도 deploy-api·redis 접근 허용 — selector를 `app: agent-pool` (또는 label `runtime/mode: image`)로 일반화.
- [ ] **drift 감지**: image_digest와 실제 Deployment의 image가 불일치하면 admin UI에 경고. 재배포는 admin 명시 액션으로만.

##### 5) 관리 콘솔 (frontend + backend)

- [ ] **목록**: 기존 source_meta 테이블에 `mode` 칼럼 추가 표시. 두 체계 한 화면.
- [ ] **등록 폼**: image 모드 전용 — image_uri (또는 registry 선택 + repo + tag), digest 자동 조회 옵션, kind, slug, replicas, resources, env, image_pull_secret 선택.
- [ ] **롤아웃 상태**: Deployment status (replicas ready/desired) + 최근 Pod 이벤트 표시.

##### 6) 문서 / 예시

- [ ] **`deploy/examples/custom-image/`** — base-image extend 예제 Dockerfile + factory.py. compiled_graph 번들을 그대로 image로 변환하는 가이드.
- [ ] **루트 DESIGN.md / 각 컴포넌트 DESIGN.md**: 위 결정 합성. `runtime_pool` 포맷, source_meta 스키마 다이어그램, 라우팅 표 갱신.
- [ ] **CLAUDE.md "꼭 알아야 할 내부 계약"**: bundle 모드와 image 모드의 식별자/책임 분리 명시. 새 kind 추가 시 4곳 업데이트 규칙은 bundle에만 적용 — image는 admin 등록 path가 대신.

##### 7) 테스트

- [ ] **단위**: `parse_runtime_pool` parse, source_meta CHECK constraint, ext-authz custom 분기.
- [ ] **integration**: image 모드 e2e — 등록 → Deployment ready → invoke → resolve cfg 반영.
- [ ] **공존**: 같은 cluster에 bundle pool + image pool 동시 운영, ring-hash와 직접 라우팅이 섞이지 않는지 확인.
- [ ] **권한**: 비-admin이 `/api/admin/custom-images` 호출 시 403, K8s SA가 namespace 밖 자원 접근 시 거부.

#### 결정 필요 (작업 시작 전)

- [ ] **multi-version 운영**: 같은 slug의 v1/v2를 동시에 띄울 수 있게 할지(Service alias로 traffic split), 아니면 새 버전이 기존 Deployment의 image tag를 덮어쓸지. 후자가 단순. blue/green 필요 시 slug 자체를 버전 포함으로 약속(`summarizer-v2`).
- [ ] **image signature 검증**: cosign/sigstore. MVP 미포함, nice-to-have.
- [ ] **scale-to-zero 허용 여부**: KEDA의 `minReplicaCount: 0`. cold-start 비용(image pull) 때문에 디폴트 1 권장.
- [ ] **현재 단일 `mcp-pool-custom.yaml` / `agent-pool-custom.yaml` 처리**: image 모드 도입 시 정적 yaml은 예시 제거 또는 "기본 placeholder Deployment(replica 0)"로 유지. 신규 작업 마무리 시점에 재논의.

완료 후 위 내용을 [DESIGN.md](DESIGN.md), [deploy/DESIGN.md](deploy/DESIGN.md), [backend/DESIGN.md](backend/DESIGN.md), [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md), [runtimes/agent-base/DESIGN.md](runtimes/agent-base/DESIGN.md), [runtimes/mcp-base/DESIGN.md](runtimes/mcp-base/DESIGN.md)에 합성하고 ROADMAP에서 삭제.

### factory instance 캐싱 적용 (런타임 경로 통합)

`runtime_common.instance_cache.InstanceCache` 와 `runtime_common.providers.{langgraph,adk,fastmcp,mcp_sdk}` 는 정의·테스트 완료 ([packages/common/DESIGN.md](packages/common/DESIGN.md) 합성). 샘플 번들도 새 패턴으로 마이그레이션 완료 ([deploy/examples/](deploy/examples/)). 남은 건 런타임이 캐시를 실제로 경유하게 만드는 것.

- [ ] **agent-base / mcp-base invoke 핸들러 교체** — 현재는 매 invoke 마다 `call_factory(factory, merged_cfg, secrets)` 직접 호출 → `instance_cache.get_or_build(key, builder)` 경유로 변경. 위치: [agent-base/app.py:192](runtimes/agent-base/src/agent_base/app.py#L192), [mcp-base/app.py:144·212·265](runtimes/mcp-base/src/mcp_base/app.py#L144).
  - `app.state.instance_cache: InstanceCache` 를 lifespan 에서 생성, 종료 시 `clear()`.
  - 키는 `make_instance_key(source.checksum, principal_id, user.updated_at)`. user_meta 없으면 `principal_id`/`updated_at` 모두 None — override 없는 모든 principal 이 단일 entry 공유.
  - 적용 후 번들의 무거운 자원 (PG 풀, LLM 클라이언트) 이 cold-start 1회만 만들어진다는 계약이 실제로 성립.
- [ ] **BundleLoader eviction 연동** — checksum 이 BundleLoader LRU 에서 빠질 때 `instance_cache.invalidate_checksum(checksum)` 호출 (재배포된 동일 checksum 의 stale instance 잔존 방지). BundleLoader 에 콜백 hook 또는 publisher pattern 추가 검토.

완료 후 위 내용을 [runtimes/agent-base/DESIGN.md](runtimes/agent-base/DESIGN.md), [runtimes/mcp-base/DESIGN.md](runtimes/mcp-base/DESIGN.md) 에 합성하고 ROADMAP 에서 삭제.

### 설계 결정 필요

- [ ] **api_keys 활성화** — `_verify_api_key`가 `access=[]` 반환해 모든 invoke 403. ACL 방식 셋 중 하나 결정 후 구현:
  - `api_key_resource_access(api_key_id, kind, name)` 테이블 신설 (가장 대칭적)
  - `tenant` 기반 ACL (단순, 세밀도 낮음)
  - API key를 기존 user에 묶어 `user_resource_access` 재사용

  결정 전까지 운영에서 사용 금지. 현재 skeleton만 존재(`POST /v1/api-keys` 발급은 동작, invoke는 항상 403).

- [ ] **chat에서 agent 버전 핀 정책** — `/chat` 드롭다운이 `{name} ({version})`로 표시하지만 페이로드는 `name`만 보내 항상 latest로 라우팅. 두 안 중 택1:
  - (선택 1) `value`를 `${name}@${version}`로 인코딩 → 송신 직전 분해해 페이로드에 `version` 포함. 운영자가 특정 버전 회귀 테스트 가능.
  - (선택 2) chat은 항상 latest 정책으로 못박고 표시에서 version 제거. UI 단순화.

  현재 동작은 (선택 2)에 가깝지만 표시·동작 불일치라 결정 필요.

### 인프라 확장

- [ ] **mTLS/SPIRE 기반 내부 caller 인증** — 현재는 NetworkPolicy로 경계 강제. SPIFFE/SPIRE 도입 시 인증서 CN으로 internal/edge 판단, `grace_sec` 동적 결정 가능.
- [ ] **Envoy HPA / subset LB / EDS** — 현재 Envoy replica 2 고정. 트래픽 기반 HPA + warm pod subset을 Envoy subset LB로 구현 + EndpointSlice 기반 EDS 전환.

### Nice-to-have

- [ ] **frontend: shadcn/ui 초기화** — `components.json` + 최소 컴포넌트(Button, Input, Table, Dialog, Form, Toast, Select). 현재는 Tailwind 직접 사용 ([frontend/DESIGN.md](frontend/DESIGN.md))
- [ ] **frontend: Storybook 컴포넌트 문서화** — `AccessList`, `JsonEditor`, `Paginator` 같은 재사용 컴포넌트 상태별 시각 검수 ([frontend/DESIGN.md](frontend/DESIGN.md))
