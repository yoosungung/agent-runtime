# ROADMAP

각 컴포넌트 `DESIGN.md`에서 수집한 미완료 항목. 세부 맥락은 해당 문서 및 [ARCHITECTURE.md](ARCHITECTURE.md) 참조.

**path-graph 연동** 상세·번호는 [path-graph/ROADMAP.md](../path-graph/ROADMAP.md)가 정본. 아래는 agents-runtime 측만 요약.

## path-graph · Knowledge Pipeline

Admin Console ingest(RAG) MVP 완료. Graph·Wiki downstream 완료. **Knowledge Binding + wiki VFS(PG-2–PG-4) 코드·클러스터 E2E(PG-3) 완료.**

| # | 작업 | 상태 | path-graph ROADMAP |
|---|---|---|---|
| PG-1 | Console GraphRAG BFF + UI | [x] | path-graph 4.5.1–4.5.3 |
| PG-2 | `config.general.knowledge_project_ids[]` + invoke 시 Knowledge Binding resolve | [x] | 3.2.0 |
| PG-3 | VFS `/wiki` mount — binding `wiki.s3_prefix` | [x] | 3.2.1 — [`test_wiki_vfs.sh`](deploy/examples/tests/e2e/test_wiki_vfs.sh) 클러스터 E2E 통과 (2026-07) |
| PG-4 | retrieval — `rag.index_namespace` + `project_id` filter; 복수 project parallel + RRF | [x] | 3.2.0 — `invoke_scoped_retrieval` |
| PG-5 | reconcile CronWorkflow per project (Console 또는 bootstrap) | [x] | 4.4.4 — BFF `pg-reconcile-{tenant}-{project}` 일 1회 upsert; create/delete + startup bootstrap |
| PG-6 | Async agent job API + Argo resume callback | [x] | path-graph 3.2.2 — `POST/GET /v1/agents/jobs`, pool `/jobs` |
| PG-7 | path-graph wheel 의존성 (release URL pin, staging 제거) | [x] | path-graph 1.4.11 — `path-graph==0.1.0` + GitHub Release wheel |
| PG-8 | `path_graph.console` + `pipeline_domain` wrapper; agent-base binding HTTP | [x] | path-graph 1.4.12 — agent-base path-graph wheel 제거 |

**권장 순서**: PG-1 → PG-5 → PG-2 → PG-3 [x] → PG-6. SharePoint Cron delta E2E는 path-graph ROADMAP §관리자 검증 체크리스트.

**D5 수집 동기화** (path-graph 4.1.3·4.1.7): BFF `sync_mode` UI · reconciler `delta_link` persist **코드 완료**. 클러스터 E2E(2.1.7)는 관리자 요청 일괄 처리 시 수행.

## Agent delegate invoke

| # | 작업 | 상태 |
|---|---|---|
| AD-1 | `/v1/agents/invoke-internal` + ext-authz grace + `agent_base.agent_tools` | [x] |
| AD-2 | `chat_selectable` + Chat access-resources 필터 | [x] |
| AD-3 | `delegate_agents[]` config + 등록 ACL 검증 | [x] |
| AD-4 | Hermes `agent_bridge` + bundle 예제 | [x] |

**권장 순서**: AD-1 → AD-3 → AD-2 → AD-4.

## 향후 계획

### Image 모드 Phase 2 (MVP 이후)

- [ ] **CSI Secret Store / Vault Agent Sidecar 도입** (리스크 C): MVP는 `secrets_ref` 헤더 패스스루로 image author가 vault 클라이언트를 직접 작성. Phase 2에서는 admin 등록 시 `secrets_mount: [{name, path, ref}]` 같은 필드를 받아 backend가 K8s 매니페스트에 [Secrets Store CSI](https://secrets-store-csi-driver.sigs.k8s.io/) 또는 Vault Agent sidecar를 주입 → image는 단순히 환경변수/볼륨 파일에서 읽기만 한다. raw contract 철학(SDK 의존 X)과 정합.
- [ ] **유휴 image cold-storage** (리스크 D): backend reconciler가 N일(예: 14일) 호출 없는 `active` image를 감지 → `status='sleep'` + `replicas=0` patch. 첫 invoke 시 ext-authz가 `sleep` 상태를 발견하면 503 + admin 알림 (또는 작은 activator path를 도입해 자동 wake — 별도 결정 필요). 비용 누수 방지.
- [ ] **cfg body fallback** (리스크 A 확장): cfg가 16KB를 초과해야 하는 케이스 발생 시, ext-authz가 헤더 대신 invoke body에 `_meta.cfg` 필드로 주입하는 옵션을 도입. body 변형은 image contract를 깨므로 admin이 명시적 opt-in.
- [ ] **image signature 검증**: cosign + admission webhook. 신뢰 registry 화이트리스트 + 서명 검증.

### 인프라 확장

- [ ] **mTLS/SPIRE 기반 내부 caller 인증** — 현재는 NetworkPolicy로 경계 강제. SPIFFE/SPIRE 도입 시 인증서 CN으로 internal/edge 판단, `grace_sec` 동적 결정 가능.
- [ ] **Envoy data plane 확장 (HPA)** — 현재 Envoy replica 2 고정. invoke 트래픽에 따라 Envoy 자체를 수평 확장할 때 검토.
- [ ] **Pool endpoint discovery (EDS)** — *원래 ROADMAP에 “subset LB + EDS”가 한 항목으로 있었으나, 구현·설계 근거 없이 initial commit에만 남아 있던 미완 placeholder였음.* 실제 라우팅은 ext-authz `x-pod-addr` + DFP. warm affinity는 Envoy subset이 아니라 Redis. **현재 pool 규모(~10 pod/pool)에서는 EDS 불필요** — pool pod가 수백 개 이상일 때만 검토. 유래·headless 정리: [deploy/DESIGN.md](deploy/DESIGN.md) “EDS / headless — 유래와 정리”.

### Nice-to-have

- [ ] **path-graph 버전 bump 자동화** — Renovate 등으로 release wheel pin 갱신 (현재: `check-path-graph-pin` CI)
- [ ] **VFS grep 고급 검색** — BM25 / vector / graph 기반 grep 대체. 현재는 Postgres `LATERAL unnest` + literal `LIKE` (agent tool loop용 MVP).
- [ ] **VFS glob 최적화** — `pg_trgm`·materialized path index 등. 현재는 scoped `path ~ regex` 전체 스캔.
- [ ] **Admin VFS — `/user/` 개인 영역** — `vfs_user_files` 열람·관리 UI, 사용자 선택 + 감사 강화 ([frontend/DESIGN.md](frontend/DESIGN.md) `/vfs` 2단계).
- [ ] **invoke SSE 슬림화** — agent-pool `astream_events` v2 full payload → BFF 필터 3-hop 제거. token delta만 emit하거나 Envoy SSE passthrough.

- [ ] **frontend: shadcn/ui 초기화** — `components.json` + 최소 컴포넌트(Button, Input, Table, Dialog, Form, Toast, Select). 현재는 Tailwind 직접 사용 ([frontend/DESIGN.md](frontend/DESIGN.md))
- [ ] **frontend: Storybook 컴포넌트 문서화** — `AccessList`, `JsonEditor`, `Paginator` 같은 재사용 컴포넌트 상태별 시각 검수 ([frontend/DESIGN.md](frontend/DESIGN.md))
