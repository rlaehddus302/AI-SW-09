# 09. 팀 역할 분담 (5인)

> 이 문서는 9조 "리뷰 대응 에이전트"를 **5명이 1.5주 안에** 개발할 때의 역할 분담안입니다.
> 핵심 원칙: **5명 전원이 에이전트(LangGraph 그래프) 개발에 참여**하고, 프론트엔드·백엔드는 각 1명이 **서브로** 빠르게(바이브코딩) 처리합니다.
> 노드/툴 경계는 [02-agent-graph.md](02-agent-graph.md)·[08-implementation-plan.md](08-implementation-plan.md)와 1:1로 맞췄습니다.

---

## 1. 분담 철학

| 원칙 | 의미 |
|------|------|
| **모두가 에이전트 개발자** | 5명 각자가 LangGraph 그래프의 "노드/툴 한 묶음"을 오너로 가진다. 아무도 순수 프론트/백엔드만 하지 않는다. |
| **프론트·백엔드는 서브** | 프론트 1명 + 백엔드 1명이 자기 에이전트 작업에 더해 곁다리로 UI/API를 빠르게(바이브코딩) 만든다. 완성도보다 데모 동작 우선. |
| **수직 슬라이스 오너십** | 각자 "노드 구현 + 그 노드의 Pydantic 모델 + 단위 테스트 + 데모 시나리오"까지 세로로 책임진다. |
| **계약 우선(Contract-first)** | Day 1에 State 스키마·상수([config.py](08-implementation-plan.md))·노드 I/O 계약을 먼저 합의하고 시작한다. 그래야 5명이 병렬로 짜도 안 깨진다. |

> **바이브코딩(vibe coding)**: 설계 문서 없이 Claude Code 등에 빠르게 시켜 동작하는 수준까지 후다닥 만드는 방식. 여기선 프론트/백엔드 서브 작업에만 적용하고, **에이전트 그래프 본체는 이 spec 문서 기반으로** 정확히 만든다.

---

## 2. 그래프를 5개 오너십 블록으로 분할

[02-agent-graph.md](02-agent-graph.md)의 노드/엣지를 서로 겹치지 않는 5개 블록으로 나눴습니다.

```
            ┌──────────────────────────────────────────────────────────┐
   리뷰 ──► │ A. classify ─► classify_router ─► router_node             │  ← 담당 1
            └───────────────┬──────────────────────────────────────────┘
                            │ (risk/유형별 동적 라우팅)
            ┌───────────────▼──────────────────────────────────────────┐
            │ B. interpret ─► retrieve(RAG, ChromaDB)                   │  ← 담당 2
            └───────────────┬──────────────────────────────────────────┘
            ┌───────────────▼──────────────────────────────────────────┐
            │ C. generate (ReAct tool-loop) + lookup_store_policy 툴    │  ← 담당 3
            └───────────────┬──────────────────────────────────────────┘
            ┌───────────────▼──────────────────────────────────────────┐
            │ D. critic ─► (revise 루프백) + validate_and_repair 가드레일│  ← 담당 4
            └───────────────┬──────────────────────────────────────────┘
            ┌───────────────▼──────────────────────────────────────────┐
            │ E. approval_gate (HITL) ─► writeback (write-back 메모리)  │  ← 담당 5
            └──────────────────────────────────────────────────────────┘
```

---

## 3. 역할 분담표

> 이름은 실제 팀원으로 교체하세요. 여기선 R1~R5로 표기합니다.
> 각자 **[메인] 에이전트 블록 1개**를 오너로 갖고, 그 외 **[서브] 횡단 역할** 하나를 맡습니다.

| 담당 | [메인] 에이전트 블록 | 핵심 산출물 (파일) | [서브] 횡단 역할 |
|------|---------------------|-------------------|------------------|
| **R1 — 분류·라우팅 오너** | A. `classify_node` + `classify_router` + `router_node` | `nodes/classify.py`, `nodes/router.py`, 멀티이슈 `issues[]` 분해 | **그래프 통합 리드** — `graph.py`(노드/엣지 배선), `config.py` 상수 SSOT 관리, State 스키마 합의 주도 |
| **R2 — 해석·RAG 오너** | B. `interpret_node` + `retrieve_node` | `nodes/interpret.py`, `nodes/retrieve.py`, ChromaDB 세팅·거리 임계값(0.4) | **백엔드 서브** — FastAPI 서버/엔드포인트 바이브코딩([06 API 계약](06-data-model.md)), 목데이터 적재 |
| **R3 — 생성·툴 오너** | C. `generate_node` (ReAct tool-loop) + `lookup_store_policy` 툴 | `nodes/generate.py`, `tools/policy.py`, MySQL 가게정책 조회 | **프롬프트 엔지니어링 리드** — 톤별 답변 프롬프트, ReAct 힌트(`needs_policy_lookup`) 튜닝 |
| **R4 — 검증·가드레일 오너** | D. `critic_node` (self-critic 루프백) + `validate_and_repair` | `nodes/critic.py`, `tools/guardrails.py`, 금칙·500자·과잉약속 체크리스트 | **QA·평가 리드** — [07-evaluation-kpi.md](07-evaluation-kpi.md) 평가셋(엣지케이스) 구축, 정확도/안전성 KPI 측정 |
| **R5 — 승인·메모리 오너** | E. `approval_gate_node` (HITL) + `writeback_node` | `nodes/approval_gate.py`, `nodes/writeback.py`, `api/approve.py`, 수정본 write-back | **프론트 서브** — React 대시보드 바이브코딩(탭별 리뷰 리스트/초안 확인/승인 버튼), trace 표시 |

---

## 4. 왜 이렇게 나눴나 (블록별 근거)

- **A (R1)** — 진입점이자 "고정 파이프라인 → 동적 라우팅"이라는 이 프로젝트의 1번 차별점([feedback](README.md) #1). 라우팅을 쥔 사람이 그래프 전체 배선까지 보는 게 자연스러워 **그래프 통합 리드**를 겸함.
- **B (R2)** — interpret과 retrieve는 "이슈 요약 → 유사사례 검색"으로 데이터가 직결돼 한 사람이 잡는 게 효율적. RAG가 외부 저장소(ChromaDB)를 다루므로 **백엔드 서브**와 묶음.
- **C (R3)** — generate는 LLM 호출 + ReAct tool-loop라 프롬프트 비중이 가장 큼 → **프롬프트 엔지니어링 리드** 겸직. `lookup_store_policy`(tool use 0→1의 핵심)도 여기 소속.
- **D (R4)** — critic + 가드레일은 "출력을 검증·교정"하는 안전망. 검증 마인드셋이 곧 QA이므로 **QA·평가 리드**를 겸해 KPI 측정까지 일관되게.
- **E (R5)** — 승인 게이트는 사용자(사장님)와 만나는 지점(HITL)이라 UI와 가장 가깝다 → **프론트 서브**와 묶음. write-back 메모리(쓸수록 학습)도 승인 직후 일어나므로 같은 오너.

---

## 5. 1.5주 일정에 매핑 ([08-implementation-plan.md](08-implementation-plan.md) Phase 기준)

| 기간 | 공동 | R1 | R2 | R3 | R4 | R5 |
|------|------|----|----|----|----|----|
| **Day 1–2** (Phase 0) | **전원**: State 스키마·`config.py` 상수·노드 I/O 계약·목데이터 합의 | 그래프 뼈대(`graph.py` stub) | ChromaDB 세팅 + 임베딩 적재 | LLM 호출 래퍼·프롬프트 골격 | `validate_and_repair` 골격 | FastAPI/React 스캐폴드(바이브) |
| **Day 3–4** (Phase 1·3) | 노드 stub 연결 | `classify`+`router` | (백엔드 서브) API 라우트 | generate 초안 | 가드레일 각 노드 적용 | (프론트 서브) 대시보드 골격 |
| **Day 5–6** (Phase 2·3) | self-critic 통합 | 라우팅 분기 테스트 | `interpret`+`retrieve` | `generate` ReAct + `policy` 툴 | `critic` 루프백 완성 | `approval_gate` |
| **Day 7** (Phase 4) | RAG·툴 통합 | 통합 점검 | RAG 거리 임계값 튜닝 | 정책조회 환각 차단 검증 | KPI 측정 시작 | `writeback` 메모리 |
| **Day 8** (Phase 5) | E2E 통합 | 그래프 전체 배선 확정 | 백엔드 마감 | 프롬프트 마감 | 평가셋 전체 돌리기 | 프론트 마감 + trace |
| **Day 9–10** | **전원**: 통합 테스트 · 데모 시나리오 고정 · 발표 준비 | | | | | |

> Phase 번호는 [08-implementation-plan.md](08-implementation-plan.md)와 동일. "공동"은 그날 함께 맞춰야 하는 동기화 지점입니다.

---

## 6. 협업 규칙 (충돌 방지)

1. **파일 오너십**: `nodes/`·`tools/` 아래는 위 표대로 1인 1파일 오너. 남의 파일은 PR 리뷰로만 손댄다.
2. **공유 파일은 R1이 게이트키퍼**: `graph.py`·`config.py`·`models.py`(State/공통 Pydantic)는 변경 시 R1에게 알리고 머지. 상수(`MAX_CRITIC_LOOPS=2`, `RAG_DISTANCE_THRESHOLD=0.4` 등)는 **`config.py` 한 곳에서만** 정의([06-data-model.md](06-data-model.md) SSOT 원칙).
3. **계약 변경 금지선**: 노드 I/O(입력/출력 State 키)는 Day 2 합의 후 임의 변경 금지. 바꿔야 하면 전원 공지.
4. **State는 TypedDict 구독 접근**(`state["key"]`)으로 통일 — 노드마다 접근 방식 섞지 않는다([02-agent-graph.md](02-agent-graph.md)).
5. **바이브코딩 격리**: 프론트(R5)·백엔드(R2)의 빠른 코드는 `frontend/`·`api/`에 격리하고, 에이전트 그래프(`agent/`)는 이 spec 문서 기반으로 정확히 작성한다. 둘을 섞지 않는다.
6. **각자 데모 한 컷 책임**: 자기 블록이 동작함을 보여줄 데모 시나리오 1개씩 준비([07-evaluation-kpi.md](07-evaluation-kpi.md) 시나리오와 연동).

---

## 7. 한 줄 요약

> **5명 모두 에이전트(노드/툴) 오너 + 그 위에 그래프통합/백엔드/프롬프트/QA/프론트 횡단 역할을 1개씩.** 프론트·백엔드는 서브로 후다닥, 에이전트 본체는 spec대로 정확히.

---

## 관련 문서

- [02-agent-graph.md](02-agent-graph.md) — 노드/엣지 정의 (오너십 블록의 근거)
- [08-implementation-plan.md](08-implementation-plan.md) — Phase별 일정 (역할 일정 매핑의 근거)
- [04-rag-tools.md](04-rag-tools.md) — RAG·정책조회 툴 (R2·R3 담당)
- [05-critic-guardrails.md](05-critic-guardrails.md) — critic·가드레일 (R4 담당)
- [07-evaluation-kpi.md](07-evaluation-kpi.md) — 평가셋·KPI (R4 QA 리드 담당)
