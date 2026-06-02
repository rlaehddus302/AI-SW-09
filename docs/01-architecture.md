# 시스템 아키텍처

이 문서는 리뷰 대응 에이전트의 전체 기술 스택과 계층 구조, 그리고 LangGraph 그래프가 위험도에 따라 경로를 동적으로 분기하는 방식을 설명한다.
상세 노드 계약은 [에이전트 그래프](02-agent-graph.md), 도구 및 RAG 설계는 [RAG·도구](04-rag-tools.md)를 참조한다.

---

## 1. 전체 기술 스택

| 계층 | 기술 | 역할 |
|------|------|------|
| **프론트엔드** | React (SPA) | 리뷰 목록·탭 필터·승인 게이트 UI |
| **백엔드 API** | FastAPI (Python) | REST 엔드포인트, LangGraph 그래프 실행 진입점 |
| **에이전트 런타임** | LangGraph | 상태 그래프(StateGraph), conditional edge, human-in-the-loop |
| **LLM** | Upstage Solar | classify / interpret / generate / critic 노드 |
| **벡터 DB** | ChromaDB | RAG 검색(read) + write-back 메모리(write) |
| **관계형 DB** | MySQL | 가게 정책(원산지·운영시간·환불 정책), 리뷰·답변 이력 |
| **인프라** | EC2 (단일 인스턴스) | 1.5주 범위; 배포 자동화 제외 |

---

## 2. 계층 구조 (ASCII)

```
┌─────────────────────────────────────────────────────────┐
│                   React SPA (브라우저)                   │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────┐ │
│  │ 리뷰 목록    │  │ 승인 게이트 UI │  │ 대시보드 탭 │ │
│  │ (탭: 홀/포장 │  │ (pending →    │  │ (hall/      │ │
│  │  /배달)      │  │  approve/edit) │  │  takeout/   │ │
│  └──────┬───────┘  └───────┬────────┘  │  delivery)  │ │
│         └─────────────────┬┘           └─────────────┘ │
└───────────────────────────┼─────────────────────────────┘
                            │ HTTP (REST)
┌───────────────────────────▼─────────────────────────────┐
│                    FastAPI 백엔드                        │
│  POST /reviews/{id}/process  → 그래프 실행 트리거       │
│  GET  /reviews/{id}/status   → GraphState.status 반환  │
│  POST /reviews/{id}/approve  → approval_status 갱신    │
│  POST /reviews/{id}/edit     → final_answer + writeback │
└───────────────────────────┬─────────────────────────────┘
                            │ LangGraph invoke / stream
┌───────────────────────────▼─────────────────────────────┐
│              LangGraph StateGraph (에이전트 코어)        │
│                                                          │
│  classify → router ─┬─(fast_thanks)──────────────┐      │
│                     ├─(standard)→ interpret →    │      │
│                     │             retrieve →     │      │
│                     └─(sensitive)→ interpret →   │      │
│                                   retrieve →     │      │
│                              generate ←──────────┘      │
│                                  │  ↑ revise loop       │
│                              critic                      │
│                                  │                       │
│                         approval_gate                    │
│                          │           │                   │
│                      writeback      END                  │
│                          │                               │
│                         END                              │
│                                                          │
│  (가드 초과/분류 실패 시 → fallback → approval_gate)     │
└──────────┬───────────────────────────────┬───────────────┘
           │ Solar API 호출                │ ChromaDB / MySQL
┌──────────▼──────────┐       ┌────────────▼──────────────┐
│  Upstage Solar LLM  │       │  ChromaDB                 │
│  - classify_node    │       │  - collection: review_reply_pairs │
│  - interpret_node   │       │    (order_channel 메타)   │
│  - generate_node    │       │  - RAG read (top-k)       │
│  - critic_node      │       │  - write-back (add)       │
└─────────────────────┘       │                           │
                              │  MySQL                    │
                              │  - store_policy 테이블    │
                              │    (lookup_store_policy)  │
                              │  - reviews / answers 이력  │
                              └───────────────────────────┘
```

---

## 3. 위험도별 동적 라우팅 개요

`router_node`는 LLM을 호출하지 않는 **규칙 기반 함수**다.
`classify` 노드가 기록한 `sentiment`, `risk_level`, `issues`를 읽고
LangGraph `conditional_edge`에 반환할 경로 라벨을 결정한다.

```python
# 의사코드 — router_node
def router_node(state: GraphState) -> GraphState:
    s = state["sentiment"]
    r = state["risk_level"]

    if s == Sentiment.positive and r == RiskLevel.low:
        route = RouteDecision.fast_thanks   # 해석·RAG 생략
        tone  = AnswerTone.thanks
    elif s == Sentiment.malicious or r == RiskLevel.high:
        route = RouteDecision.sensitive     # critic 2회 + 무조건 게이트
        tone  = AnswerTone.firm
    else:
        route = RouteDecision.standard      # 해석 + RAG + critic 1회
        tone  = AnswerTone.apology          # interpret_node가 덮어쓸 수 있음

    return {**state, "route": route, "answer_tone": tone,
            "requires_approval": (route == RouteDecision.sensitive)}

# conditional_edge 분기 함수
def route_to_next(state: GraphState) -> str:
    return state["route"].value  # "fast_thanks" | "standard" | "sensitive"
```

경로별 처리 단계 요약:

| 경로 | 조건 | 통과 노드 | critic 횟수 | 승인 게이트 |
|------|------|-----------|-------------|-------------|
| `fast_thanks` | positive + low | generate | 1회 (통상 pass) | 자동(auto_approved) |
| `standard` | negative / medium | interpret → retrieve → generate | 1회 | risk에 따라 자동/수동 |
| `sensitive` | malicious / high | interpret → retrieve → generate | **최소 2회 강제** | 무조건 pending |

---

## 4. 데이터 흐름 요약

1. **React → FastAPI**: 사장님이 '처리' 버튼 클릭 → `POST /reviews/{id}/process`
2. **FastAPI → LangGraph**: `graph.invoke(initial_state)` 비동기 실행
3. **classify**: Solar LLM이 `review_text`를 분석 → `ClassificationResult` (pydantic 검증, 실패 시 교정형 재시도)
4. **router**: 규칙 함수가 `route` 결정 → conditional_edge 분기
5. **경로별 실행**: interpret(optional) → retrieve(ChromaDB) → generate(Solar + lookup_store_policy tool) → critic(Solar)
6. **approval_gate**: `requires_approval` 여부에 따라 자동 승인 또는 `status=needs_manual` → React UI 대기
7. **사장님 확정**: `POST /reviews/{id}/approve` 또는 `/edit` → `final_answer` 갱신
8. **writeback**: `owner_approved` / `owner_revised` 시 ChromaDB에 pair add (write-back 메모리)
9. **FastAPI → React**: `status=done`, `final_answer` 반환 → 대시보드 갱신

---

## 5. 컴포넌트별 역할 경계

### 5-1. React (최소 UI)
- 탭 필터: `order_channel` (hall / takeout / delivery)
- 리뷰 카드: `review_text`, `sentiment`, `risk_level`, `draft_answer`, `status`
- 승인 게이트 뷰: `approval_status == pending` 시 수정·승인·보류 버튼 노출
- 1.5주 범위 내 최소화 — 리포트 화면·분석 대시보드는 제외

### 5-2. FastAPI
- `GraphState` 초기화 (`review_id`, `review_text`, `order_channel`, `store_id`)
- LangGraph `invoke` 호출 및 결과 직렬화
- 승인 결과를 MySQL에 기록하고 `writeback_node` 트리거
- 인증·권한 최소화(데모 범위)

### 5-3. LangGraph StateGraph
- 전체 에이전트 흐름의 단일 진실 원천
- 모든 상태(`GraphState`)는 노드 함수가 딕셔너리로 반환 → LangGraph가 병합
- conditional_edge 두 곳: `classify → (router|fallback)`, `critic → (approval_gate|generate|fallback)`
- human-in-the-loop: `approval_gate_node`에서 `interrupt_before` 또는 외부 이벤트 대기

### 5-4. ChromaDB
- 컬렉션 하나, `order_channel` 메타데이터 필드로 필터
- `RAG_DISTANCE_THRESHOLD` 초과분 제거 → `rag_hit=False` 시 단독 생성 폴백
- `write_back_case` 호출 시 `add` — 읽기 전용 few-shot을 경험 축적형 메모리로 전환 (Generative Agents)

### 5-5. MySQL
- `store_policy` 테이블: `store_id`, `field`(PolicyField), `value`
- `lookup_store_policy` 툴이 SELECT 쿼리로 조회
- `reviews` / `answers` 이력 테이블(기획서 기존 설계 유지)

---

## 6. 핵심 상수 (단일 진실 원천)

```python
# config.py
RAG_DISTANCE_THRESHOLD = 0.4   # ChromaDB L2 거리; 초과 시 비유사 판정
MAX_CRITIC_LOOPS       = 2     # critic→generate 루프백 최대 횟수 (SSOT: 06-data-model.md)
MAX_GEN_RETRIES        = 1     # 생성 실패 재시도 (기획서 9p 준수)
MAX_SCHEMA_RETRIES     = 1     # pydantic 검증 실패 교정형 재시도
RAG_TOP_K              = 3     # ChromaDB 초기 검색 개수
```

---

## 7. 연관 문서

| 문서 | 내용 |
|------|------|
| [00-overview.md](00-overview.md) | 프로젝트 전체 개요 및 에이전트 정의 |
| [02-agent-graph.md](02-agent-graph.md) | LangGraph 노드·엣지 상세, GraphState 스키마 |
| [03-agent-contracts.md](03-agent-contracts.md) | 각 노드의 입출력 계약, 프롬프트 스케치 |
| [04-rag-tools.md](04-rag-tools.md) | ChromaDB RAG, lookup_store_policy, write-back 설계 |
| [05-critic-guardrails.md](05-critic-guardrails.md) | self-critic 노드, 스키마 가드레일, 루프 제어 |
| [06-data-model.md](06-data-model.md) | MySQL 스키마, Pydantic 모델, Enum 정의 |
| [07-evaluation-kpi.md](07-evaluation-kpi.md) | 평가셋 구성, KPI 측정 방법 |
| [08-implementation-plan.md](08-implementation-plan.md) | 1.5주 마일스톤, 우선순위, 엣지케이스 목데이터 |
