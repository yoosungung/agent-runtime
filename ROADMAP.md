# ROADMAP

각 컴포넌트 `DESIGN.md`에서 수집한 미완료 항목. 세부 맥락은 해당 문서 및 [ARCHITECTURE.md](ARCHITECTURE.md) 참조.

## 향후 계획

### Image 모드 Phase 2 (MVP 이후)

- [ ] **CSI Secret Store / Vault Agent Sidecar 도입** (리스크 C): MVP는 `secrets_ref` 헤더 패스스루로 image author가 vault 클라이언트를 직접 작성. Phase 2에서는 admin 등록 시 `secrets_mount: [{name, path, ref}]` 같은 필드를 받아 backend가 K8s 매니페스트에 [Secrets Store CSI](https://secrets-store-csi-driver.sigs.k8s.io/) 또는 Vault Agent sidecar를 주입 → image는 단순히 환경변수/볼륨 파일에서 읽기만 한다. raw contract 철학(SDK 의존 X)과 정합.
- [ ] **유휴 image cold-storage** (리스크 D): backend reconciler가 N일(예: 14일) 호출 없는 `active` image를 감지 → `status='sleep'` + `replicas=0` patch. 첫 invoke 시 ext-authz가 `sleep` 상태를 발견하면 503 + admin 알림 (또는 작은 activator path를 도입해 자동 wake — 별도 결정 필요). 비용 누수 방지.
- [ ] **cfg body fallback** (리스크 A 확장): cfg가 16KB를 초과해야 하는 케이스 발생 시, ext-authz가 헤더 대신 invoke body에 `_meta.cfg` 필드로 주입하는 옵션을 도입. body 변형은 image contract를 깨므로 admin이 명시적 opt-in.
- [ ] **image signature 검증**: cosign + admission webhook. 신뢰 registry 화이트리스트 + 서명 검증.

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
- [ ] **Envoy data plane 확장 (HPA)** — 현재 Envoy replica 2 고정. invoke 트래픽에 따라 Envoy 자체를 수평 확장할 때 검토.
- [ ] **Pool endpoint discovery (EDS)** — *원래 ROADMAP에 “subset LB + EDS”가 한 항목으로 있었으나, 구현·설계 근거 없이 initial commit에만 남아 있던 미완 placeholder였음.* 실제 라우팅은 ext-authz `x-pod-addr` + DFP. warm affinity는 Envoy subset이 아니라 Redis. **현재 pool 규모(~10 pod/pool)에서는 EDS 불필요** — pool pod가 수백 개 이상일 때만 검토. 유래·headless 정리: [deploy/DESIGN.md](deploy/DESIGN.md) “EDS / headless — 유래와 정리”.

### Nice-to-have

- [ ] **VFS grep 고급 검색** — BM25 / vector / graph 기반 grep 대체. 현재는 Postgres `LATERAL unnest` + literal `LIKE` (agent tool loop용 MVP).
- [ ] **VFS glob 최적화** — `pg_trgm`·materialized path index 등. 현재는 scoped `path ~ regex` 전체 스캔.
- [ ] **invoke SSE 슬림화** — agent-pool `astream_events` v2 full payload → BFF 필터 3-hop 제거. token delta만 emit하거나 Envoy SSE passthrough.

- [ ] **frontend: shadcn/ui 초기화** — `components.json` + 최소 컴포넌트(Button, Input, Table, Dialog, Form, Toast, Select). 현재는 Tailwind 직접 사용 ([frontend/DESIGN.md](frontend/DESIGN.md))
- [ ] **frontend: Storybook 컴포넌트 문서화** — `AccessList`, `JsonEditor`, `Paginator` 같은 재사용 컴포넌트 상태별 시각 검수 ([frontend/DESIGN.md](frontend/DESIGN.md))
