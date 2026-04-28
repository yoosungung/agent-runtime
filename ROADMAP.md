# ROADMAP

전체 DESIGN.md에서 수집한 미완료 항목. 세부 맥락은 각 컴포넌트 DESIGN.md 참조.

게이트웨이 통합(ext-authz + Envoy로 데이터플레인 일원화) 3단계가 완료되어 agent-gateway·mcp-gateway가 제거됐다. 완료된 내용은 [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md), [deploy/DESIGN.md](deploy/DESIGN.md), [backend/DESIGN.md](backend/DESIGN.md)에 합성됨.

Image 모드(`custom` pool 의미 전환) 구현이 완료됐다. 스키마 확장·ext-authz 라우팅 분기·backend K8s admin path·관리 콘솔·정적 매니페스트 정리·테스트가 모두 완료됨. 완료된 내용은 [DESIGN.md](DESIGN.md), [deploy/DESIGN.md](deploy/DESIGN.md), [backend/DESIGN.md](backend/DESIGN.md), [services/ext-authz/DESIGN.md](services/ext-authz/DESIGN.md), [runtimes/agent-base/DESIGN.md](runtimes/agent-base/DESIGN.md), [runtimes/mcp-base/DESIGN.md](runtimes/mcp-base/DESIGN.md)에 합성됨.

## 향후 계획

### Image 모드 Phase 2 (MVP 이후)

- [ ] **CSI Secret Store / Vault Agent Sidecar 도입** (리스크 C): MVP는 `secrets_ref` 헤더 패스스루로 image author가 vault 클라이언트를 직접 작성. Phase 2에서는 admin 등록 시 `secrets_mount: [{name, path, ref}]` 같은 필드를 받아 backend가 K8s 매니페스트에 [Secrets Store CSI](https://secrets-store-csi-driver.sigs.k8s.io/) 또는 Vault Agent sidecar를 주입 → image는 단순히 환경변수/볼륨 파일에서 읽기만 한다. raw contract 철학(SDK 의존 X)과 정합.
- [ ] **유휴 image cold-storage** (리스크 D): backend reconciler가 N일(예: 14일) 호출 없는 `active` image를 감지 → `status='sleep'` + `replicas=0` patch. 첫 invoke 시 ext-authz가 `sleep` 상태를 발견하면 503 + admin 알림 (또는 작은 activator path를 도입해 자동 wake — 별도 결정 필요). 비용 누수 방지.
- [ ] **cfg body fallback** (리스크 A 확장): cfg가 16KB를 초과해야 하는 케이스 발생 시, ext-authz가 헤더 대신 invoke body에 `_meta.cfg` 필드로 주입하는 옵션을 도입. body 변형은 image contract를 깨므로 admin이 명시적 opt-in.
- [ ] **image signature 검증**: cosign + admission webhook. 신뢰 registry 화이트리스트 + 서명 검증.

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
