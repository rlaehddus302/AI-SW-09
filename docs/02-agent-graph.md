# 에이전트 그래프 (노드·엣지·State)

이 문서는 LangGraph로 구현하는 리뷰 대응 에이전트의 전체 그래프 구조를 정의한다. 노드·엣지·State 스키마, conditional_edge 분기 조건, 루프 가드 상수를 의사코드 수준으로 기술해 학생이 바로 코드로 옮길 수 있도록 한다.

관련 문서: [아키텍처 개요](01-architecture.md) · [에이전트 계약](03-agent-contracts.md) · [RAG·도구](04-rag-tools.md) · [Critic·가드레일](05-critic-guardrails.md) · [데이터 모델](06-data-model.md)

---

## 1. 전체 흐름 — ASCII 다이어그램

```
START
  │
  ▼
┌─────────┐   스키마 실패/분류불가
│ classify │──────────────────────────────────────────┐
└─────────┘                                           │
  │ 성공                                               │
  ▼                                                   │
┌────────┐                                            │
│ router │  (규칙 기반 함수, LLM 아님)                 │
└────────┘                                            │
  │                                                   │
  ├─── route == fast_thanks ─────────────────────┐   │
  │                                              │   │
  ├─── route == standard  ──┐                    │   │
  │                         │                    │   │
  └─── route == sensitive ──┤                    │   │
                            ▼                    │   │
                       ┌──────────┐              │   │
                       │ interpret│              │   │
                       └──────────┘              │   │
                            │                    │   │
                            ▼                    │   │
                       ┌──────────┐              │   │
                       │ retrieve │              │   │
                       └──────────┘              │   │
                            │                    │   │
                            └──────┬─────────────┘   │
                                   ▼                  │
                            ┌──────────┐              │
                     ┌─────▶│ generate │◀────┐        │
                     │      └──────────┘     │        │
                     │           │ 성공       │        │
                     │           ▼           │        │
                     │      ┌──────────┐     │        │
                     │      │  critic  │     │ revise │
                     │      └──────────┘     │        │
                     │           │           │        │
                     │  pass     │  revise───┘        │
                     │  ┌────────┘                    │
                     │  │  block                      │
                     │  │   └──────────────────────┐  │
                     │  ▼                          ▼  ▼
                     │ ┌───────────────┐      ┌──────────┐
                     │ │ approval_gate │      │ fallback │
                     │ └───────────────┘      └──────────┘
                     │        │                    │
                     │ auto_  │ owner_approved/    │ 항상
                     │approved│ owner_revised      │ (requires_approval=True)
                     │        ▼                    ▼
                     │  ┌───────────┐    ┌───────────────┐
                     │  │ writeback │    │ approval_gate │
                     │  └───────────┘    │  (pending /   │
                     │        │         │  needs_manual) │
                     │        ▼         └───────────────┘
                     └──────▶END
```

---

## 2. State 스키마 (GraphState)

> **LangGraph State** = 노드 간에 공유되는 단일 딕셔너리. 각 노드는 reads/writes 키만 접근한다.
> **TypedDict 정본**: LangGraph 관례에 따라 `TypedDict`로 선언하고 `state['key']` 형식으로 접근한다. (06-data-model.md SSOT)

```python
from typing import Optional, TypedDict
from langgraph.graph import StateGraph
from pydantic import BaseModel  # 서브 모델(Issue 등)에만 사용

# ── 열거형 ─────────────────────────────────────────────
class Sentiment(str, Enum):      values = ["positive","negative","malicious"]
class ReviewType(str, Enum):     values = ["delivery_delay","foreign_object","food_taste",
                                           "food_temperature","unkind_service","price_complaint",
                                           "packaging_defect","refund_request","praise","etc"]
class RiskLevel(str, Enum):      values = ["low","medium","high"]
class OrderChannel(str, Enum):   values = ["hall","takeout","delivery"]
class AnswerTone(str, Enum):     values = ["thanks","apology","explain","firm"]
class RouteDecision(str, Enum):  values = ["fast_thanks","standard","sensitive"]
class CriticVerdict(str, Enum):  values = ["pass","revise","block"]
class ApprovalStatus(str, Enum): values = ["auto_approved","pending","owner_approved",
                                           "owner_revised","held"]
class PipelineStatus(str, Enum): values = ["running","needs_manual","done","failed"]

# ── 서브 모델 (Pydantic, LLM 입출력 검증용) ────────────
class Issue(BaseModel):
    aspect: str               # 이슈 대상 예: "배달", "콜라 누락"
    sentiment: Sentiment
    review_type: ReviewType
    risk_level: RiskLevel

class Interpretation(BaseModel):
    core_issues: list[str]          # 핵심 이슈 요약
    answer_tone: AnswerTone
    action_direction: str           # 사장님 권장 행동
    needs_policy_lookup: bool       # generate ReAct 힌트

class RetrievedCase(BaseModel):
    review: str
    reply: str
    review_type: ReviewType
    risk_level: RiskLevel
    order_channel: OrderChannel
    distance: float                 # 임베딩 거리(작을수록 유사)
    tags: list[str]                 # 예: ["high_edit"]

class ToolCall(BaseModel):
    thought: str
    tool_name: str
    args: dict
    result: str
    step: int

class CriticResult(BaseModel):
    verdict: CriticVerdict
    has_forbidden_emotion: bool
    exceeds_500_chars: bool
    has_overpromise: bool
    tone_mismatch: bool
    revise_reason: str

# ── 전체 State (TypedDict 정본 — LangGraph 관례, state['key'] 접근) ──
class GraphState(TypedDict, total=False):
    # 입력 (불변)
    review_id: str
    review_text: str
    order_channel: OrderChannel
    store_id: str

    # 분류 출력
    sentiment: Optional[Sentiment]
    review_type: Optional[ReviewType]
    risk_level: Optional[RiskLevel]
    issues: list[Issue]

    # 라우팅
    route: Optional[RouteDecision]
    requires_approval: bool
    answer_tone: Optional[AnswerTone]

    # 해석·검색
    interpretation: Optional[Interpretation]
    retrieved_cases: list[RetrievedCase]
    rag_hit: bool

    # 생성·검증
    draft_answer: str
    tool_calls: list[ToolCall]
    critic_result: Optional[CriticResult]
    critic_loops: int

    # 가드
    schema_retries: int
    gen_retries: int

    # 승인·완료
    approval_status: ApprovalStatus
    final_answer: Optional[str]
    owner_edited: bool

    # 상태·오류
    status: PipelineStatus
    error_log: list[str]
```

---

## 3. 가드 상수

```python
MAX_CRITIC_LOOPS   = 2   # sensitive 경로는 최소 2회 강제
MAX_GEN_RETRIES    = 1   # 답변 생성 재시도 상한
MAX_SCHEMA_RETRIES = 1   # 스키마 교정 재요청 상한
RAG_DISTANCE_THRESHOLD = 0.4  # 이 값 미만만 유사 사례로 인정
```

---

## 4. 노드 의사코드

### 4-1. classify_node — 분류 + 멀티이슈 분해

> **역할:** 원본 리뷰를 읽어 `ClassificationResult`(sentinel/type/risk + issues 배열)를 산출한다. 스키마 가드레일 적용. 애매하면 `risk=medium + requires_approval=True` 폴백(기획서 9p fail-safe).

```python
def classify_node(state: GraphState) -> GraphState:
    raw = call_llm(build_classify_prompt(state["review_text"], state["order_channel"]))
    result, err = validate_and_repair(raw, ClassificationResult, state["schema_retries"])

    if result is None:
        state["error_log"].append(f"classify schema error: {err}")
        state["schema_retries"] += 1
        if state["schema_retries"] >= MAX_SCHEMA_RETRIES:
            # 카운터 소진 → needs_manual 설정
            state["status"] = PipelineStatus.needs_manual
            return state
        # 교정형 재시도: 오류 메시지를 프롬프트에 되먹임
        retry_prompt = build_classify_prompt(state["review_text"], state["order_channel"],
                                             correction_hint=err, previous_output=raw)
        raw2 = call_llm(retry_prompt)
        result, err2 = validate_and_repair(raw2, ClassificationResult, state["schema_retries"])
        if result is None:
            state["status"] = PipelineStatus.needs_manual
            state["error_log"].append(f"classify retry failed: {err2}")
            return state

    # 정상 기록
    state["sentiment"]   = result.sentiment
    state["review_type"] = result.review_type
    state["risk_level"]  = result.risk_level
    state["issues"]      = result.issues

    if result.is_ambiguous:
        state["risk_level"]        = RiskLevel.medium
        state["requires_approval"] = True

    return state


def classify_router(state: GraphState) -> str:
    """conditional_edge 함수: 다음 노드 이름을 문자열로 반환"""
    if state["status"] == PipelineStatus.needs_manual:
        return "fallback"
    return "router"
```

---

### 4-2. router_node — 규칙 기반 동적 라우팅

> **역할:** LLM 없이 순수 규칙 함수. `sentiment`/`risk_level`/`issues`를 읽어 처리 경로를 결정한다. Anthropic *Building Effective Agents* routing 패턴.

```python
def router_node(state: GraphState) -> GraphState:
    s = state["sentiment"]
    r = state["risk_level"]
    max_risk = max((i.risk_level for i in state["issues"]), default=r,
                   key=lambda x: ["low","medium","high"].index(x))

    # malicious 최우선
    if s == Sentiment.malicious:
        state["route"]             = RouteDecision.sensitive
        state["answer_tone"]       = AnswerTone.firm
        state["requires_approval"] = True

    # positive 우선 분기: answer_tone=thanks 보존 (03-agent-contracts.md 표 정렬)
    elif s == Sentiment.positive:
        if max_risk == RiskLevel.low:
            state["route"]             = RouteDecision.fast_thanks
            state["answer_tone"]       = AnswerTone.thanks
            state["requires_approval"] = False
        elif max_risk == RiskLevel.high:
            state["route"]             = RouteDecision.sensitive
            state["answer_tone"]       = AnswerTone.thanks   # positive이므로 thanks 유지
            state["requires_approval"] = True
        else:  # medium
            state["route"]             = RouteDecision.standard
            state["answer_tone"]       = AnswerTone.thanks
            # requires_approval은 classify 단계 설정값 유지

    elif max_risk == RiskLevel.high:
        state["route"]             = RouteDecision.sensitive
        state["answer_tone"]       = AnswerTone.apology
        state["requires_approval"] = True

    else:
        # negative + medium/low
        state["route"]       = RouteDecision.standard
        state["answer_tone"] = AnswerTone.apology
        # requires_approval은 classify 단계 설정값 유지

    return state


def route_edge(state: GraphState) -> str:
    """router 뒤 conditional_edge"""
    if state["route"] == RouteDecision.fast_thanks:
        return "generate"      # interpret·retrieve 건너뜀
    return "interpret"         # standard·sensitive 모두
```

---

### 4-3. interpret_node — 핵심 이슈 요약 + 톤 도출

> **역할:** `standard`·`sensitive` 경로에서만 실행. 이슈 요약과 답변 방향을 도출한다. 경량 노드 — 분류에 흡수 가능하나, sensitive 경로에서 톤 결정이 명확히 필요해 별도 유지.

```python
def interpret_node(state: GraphState) -> GraphState:
    prompt = build_interpret_prompt(
        review_text=state["review_text"],
        sentiment=state["sentiment"],
        review_type=state["review_type"],
        risk_level=state["risk_level"],
        issues=state["issues"],
    )
    raw = call_llm(prompt)
    result, err = validate_and_repair(raw, Interpretation, 0)

    if result is None:
        state["error_log"].append(f"interpret fail: {err}")
        # 해석 실패는 치명적이지 않음 — 기본값으로 계속
        state["interpretation"] = None
    else:
        state["interpretation"] = result
        state["answer_tone"]    = result.answer_tone

    return state
```

---

### 4-4. retrieve_node — RAG 검색 + 거리 임계값 필터

> **역할:** ChromaDB에서 `order_channel` 메타 필터 + 임베딩 유사도로 상위 K개 검색 후 `RAG_DISTANCE_THRESHOLD`로 필터링. 통과분 없으면 `rag_hit=False`(단독 생성 폴백). ChromaDB가 항상 top-k를 반환하는 특성상 임계값 없이는 무관 사례가 답변을 오염시킨다.

```python
def retrieve_node(state: GraphState) -> GraphState:
    cases = retrieve_similar_cases(
        review_text=state["review_text"],
        order_channel=state["order_channel"],
        top_k=3,
        distance_threshold=RAG_DISTANCE_THRESHOLD,
    )
    state["retrieved_cases"] = cases
    state["rag_hit"]         = len(cases) > 0
    return state
```

---

### 4-5. generate_node — ReAct 스타일 답변 생성

> **역할:** 해석·RAG·가게정책을 종합해 초안 생성. 작성 중 원산지·환불 등 사실 근거가 필요하면 `lookup_store_policy` tool을 호출하는 ReAct(Yao 2022) tool-loop. critic revise 신호가 들어오면 `revise_reason`을 반영해 재생성.

```python
def generate_node(state: GraphState) -> GraphState:
    revise_hint = ""
    if state["critic_result"] and state["critic_result"].verdict == CriticVerdict.revise:
        revise_hint = state["critic_result"].revise_reason

    prompt = build_generate_prompt(
        review_text=state["review_text"],
        interpretation=state["interpretation"],
        answer_tone=state["answer_tone"],
        retrieved_cases=state["retrieved_cases"],
        rag_hit=state["rag_hit"],
        issues=state["issues"],
        revise_hint=revise_hint,
        prev_tool_calls=state["tool_calls"],
    )

    # ReAct tool-loop (최대 3 스텝)
    draft, tool_calls = react_loop(
        prompt=prompt,
        tools={"lookup_store_policy": lookup_store_policy},
        store_id=state["store_id"],
        max_steps=3,
    )

    if not draft:
        # 빈 출력 or 예외: 카운터 증가 → >= MAX 판정 → needs_manual 설정
        state["gen_retries"] += 1
        if state["gen_retries"] >= MAX_GEN_RETRIES:
            state["error_log"].append("generate: empty output after retry")
            state["status"] = PipelineStatus.needs_manual
            return state
        # 단순 재시도 1회 (교정 힌트 없음)
        draft, tool_calls = react_loop(prompt, tools, state["store_id"], max_steps=3)

    if not draft:
        state["error_log"].append("generate: empty output after retry")
        state["status"] = PipelineStatus.needs_manual
        return state

    state["draft_answer"] = draft
    state["tool_calls"]   = state["tool_calls"] + tool_calls
    return state


def generate_router(state: GraphState) -> str:
    """generate 뒤 conditional_edge"""
    if state["status"] == PipelineStatus.needs_manual:
        return "fallback"
    return "critic"
```

---

### 4-6. critic_node — Self-Critic 검증 루프

> **역할:** 초안을 체크리스트(금지 감정표현 / 500자 초과 / 과잉약속 / firm 톤 유지)로 평가해 `verdict`를 산출. `revise`면 `revise_reason`과 함께 generate 루프백. `sensitive` 경로는 `critic_loops < 2`이면 pass를 차단해 최소 2회 검증을 강제한다. Self-Refine(Madaan 2023)의 축소판.

```python
def critic_node(state: GraphState) -> GraphState:
    prompt = build_critic_prompt(
        draft_answer=state["draft_answer"],
        answer_tone=state["answer_tone"],
        sentiment=state["sentiment"],
        risk_level=state["risk_level"],
    )
    raw    = call_llm(prompt)
    result, err = validate_and_repair(raw, CriticResult, 0)

    if result is None:
        # critic 자체 실패 → 안전을 위해 block 처리
        result = CriticResult(
            verdict=CriticVerdict.block,
            has_forbidden_emotion=False,
            exceeds_500_chars=False,
            has_overpromise=False,
            tone_mismatch=False,
            revise_reason=f"critic schema error: {err}",
        )

    # sensitive 경로 최소 2회 강제
    if (state["route"] == RouteDecision.sensitive
            and result.verdict == CriticVerdict.pass_
            and state["critic_loops"] < 2):
        result = result.copy(update={
            "verdict": CriticVerdict.revise,
            "revise_reason": "sensitive path: critic_loops < 2, forced re-check",
        })

    state["critic_result"]  = result
    state["critic_loops"]  += 1
    return state


def critic_edge(state: GraphState) -> str:
    """critic 뒤 conditional_edge"""
    v = state["critic_result"].verdict
    if v == CriticVerdict.pass_:
        return "approval_gate"
    if v == CriticVerdict.revise and state["critic_loops"] < MAX_CRITIC_LOOPS:
        return "generate"      # 루프백
    return "fallback"          # block 또는 루프 상한 초과
```

---

### 4-7. approval_gate_node — Human-in-the-Loop 승인 게이트

> **역할:** `requires_approval`이 False면 자동 승인(`auto_approved`). True면 `pending`으로 사장님 UI에 노출. 사장님이 수정/승인하면 `owner_revised` / `owner_approved` 기록 후 `writeback`으로.

```python
def approval_gate_node(state: GraphState) -> GraphState:
    if not state["requires_approval"]:
        state["approval_status"] = ApprovalStatus.auto_approved
        state["final_answer"]    = state["draft_answer"]
        state["status"]          = PipelineStatus.done
    else:
        # 실제 구현: FastAPI endpoint가 사장님 응답을 기다림(interrupt_before 패턴)
        state["approval_status"] = ApprovalStatus.pending
        # 사장님 응답 수신 후:
        #   final_answer    = owner_text (수정 시) or draft_answer (승인 시)
        #   approval_status = owner_revised / owner_approved
        #   owner_edited    = (owner_text != draft_answer)
        #   status          = done
    return state


def gate_edge(state: GraphState) -> str:
    """approval_gate 뒤 conditional_edge"""
    s = state["approval_status"]
    if s in (ApprovalStatus.owner_approved, ApprovalStatus.owner_revised):
        return "writeback"
    return "END"   # auto_approved 또는 held
```

---

### 4-8. writeback_node — Write-back 메모리 (Generative Agents 성장 메모리)

> **역할:** 사장님 확정/수정본을 (review, final_reply, type, risk, channel) pair로 ChromaDB에 add. `owner_edited=True`면 `high_edit` 태그를 붙여 다음 검색 시 우선 가중. 기존 read-only RAG를 경험 축적형 메모리로 전환(Park 2023).

```python
def writeback_node(state: GraphState) -> GraphState:
    result = write_back_case(
        review_text=state["review_text"],
        final_reply=state["final_answer"],
        review_type=state["review_type"],
        risk_level=state["risk_level"],
        order_channel=state["order_channel"],
        owner_edited=state["owner_edited"],
    )
    if not result.added:
        state["error_log"].append(f"writeback fail: {result}")
        # 메모리 적재 실패가 사용자 답변을 막지 않음 → done 유지
    state["status"] = PipelineStatus.done
    return state
```

---

### 4-9. fallback_node — 안전 폴백

> **역할:** 가드 초과(critic block / gen 재시도 소진 / 스키마 재시도 소진 / 분류 실패) 진입. 빈 초안 대신 '정중한 사과 1문장' 최소 안전 템플릿을 draft로 두고 `needs_manual`로 게이트행. 기획서 9p fail-safe 보강.

```python
def fallback_node(state: GraphState) -> GraphState:
    state["draft_answer"]      = make_safe_fallback(state["sentiment"], state["review_type"])
    state["requires_approval"] = True
    state["approval_status"]   = ApprovalStatus.pending
    state["status"]            = PipelineStatus.needs_manual
    return state
```

---

## 5. 그래프 조립 — LangGraph 의사코드

```python
from langgraph.graph import StateGraph, END

builder = StateGraph(GraphState)

# ── 노드 등록 ─────────────────────────────────────────
builder.add_node("classify",      classify_node)
builder.add_node("router",        router_node)
builder.add_node("interpret",     interpret_node)
builder.add_node("retrieve",      retrieve_node)
builder.add_node("generate",      generate_node)
builder.add_node("critic",        critic_node)
builder.add_node("approval_gate", approval_gate_node)
builder.add_node("writeback",     writeback_node)
builder.add_node("fallback",      fallback_node)

# ── 진입점 ────────────────────────────────────────────
builder.set_entry_point("classify")

# ── conditional_edge: classify 뒤 ────────────────────
builder.add_conditional_edges("classify", classify_router, {
    "router":   "router",
    "fallback": "fallback",
})

# ── conditional_edge: router 뒤 ──────────────────────
builder.add_conditional_edges("router", route_edge, {
    "generate": "generate",   # fast_thanks 직행
    "interpret": "interpret", # standard·sensitive
})

# ── 고정 엣지 ─────────────────────────────────────────
builder.add_edge("interpret", "retrieve")
builder.add_edge("retrieve",  "generate")

# ── conditional_edge: generate 뒤 ────────────────────
builder.add_conditional_edges("generate", generate_router, {
    "critic":   "critic",
    "fallback": "fallback",
})

# ── conditional_edge: critic 뒤 ──────────────────────
builder.add_conditional_edges("critic", critic_edge, {
    "approval_gate": "approval_gate",
    "generate":      "generate",     # revise 루프백
    "fallback":      "fallback",
})

# ── conditional_edge: approval_gate 뒤 ───────────────
builder.add_conditional_edges("approval_gate", gate_edge, {
    "writeback": "writeback",
    "END":       END,
})

# ── fallback → approval_gate (항상) ──────────────────
builder.add_edge("fallback",  "approval_gate")
builder.add_edge("writeback", END)

graph = builder.compile()
```

---

## 6. 경로별 노드 실행 요약

| 경로 | 실행 노드 순서 | critic 횟수 | 승인 게이트 |
|------|--------------|-------------|------------|
| **fast_thanks** (긍정·저위험) | classify → router → generate → critic(1회) → approval_gate → END | 1 | auto_approved |
| **standard** (부정·중위험) | classify → router → interpret → retrieve → generate → critic(1회) → approval_gate | 1 | risk에 따라 자동/수동 |
| **sensitive** (악성·고위험) | classify → router → interpret → retrieve → generate → critic(≥2회) → approval_gate → writeback | ≥2 | 항상 pending |
| **fallback** (가드 초과/분류 실패) | … → fallback → approval_gate(pending) | - | 항상 pending (needs_manual) |

---

## 7. conditional_edge 분기 조건 요약

| 엣지 함수 | 입력 조건 | 반환(다음 노드) |
|----------|----------|---------------|
| `classify_router` | `status == needs_manual` | `fallback` |
| `classify_router` | 그 외 | `router` |
| `route_edge` | `route == fast_thanks` | `generate` |
| `route_edge` | `route == standard` or `sensitive` | `interpret` |
| `generate_router` | `status == needs_manual` | `fallback` |
| `generate_router` | 그 외 | `critic` |
| `critic_edge` | `verdict == pass` | `approval_gate` |
| `critic_edge` | `verdict == revise AND critic_loops < MAX_CRITIC_LOOPS` | `generate` |
| `critic_edge` | `verdict == block OR critic_loops >= MAX_CRITIC_LOOPS` | `fallback` |
| `gate_edge` | `approval_status in {owner_approved, owner_revised}` | `writeback` |
| `gate_edge` | `approval_status in {auto_approved, held}` | `END` |

---

## 8. 설계 근거 요약

| 설계 결정 | 근거 |
|----------|------|
| 규칙 기반 router → conditional_edge 분기 | Anthropic *Building Effective Agents* — routing 패턴: 고정 DAG(workflow)를 상황 적응형 경로로 전환 |
| critic→generate 루프백 (Self-Critic) | Self-Refine (Madaan 2023): 동일 모델의 비평·재생성 루프만으로 품질 유의미하게 향상 |
| sensitive 경로 critic 최소 2회 강제 | Reflexion (Shinn 2023): 고위험 출력은 단발 검증 불충분, 반복 검증으로 신뢰성 확보 |
| generate ReAct tool-loop | ReAct (Yao 2022): 추론·행동 교차로 외부 사실(원산지·정책) 조회 → 환각 감소 |
| write-back 메모리 | Generative Agents (Park 2023): 확정 답변을 ChromaDB에 적재해 경험 축적형 메모리로 전환 |
| RAG 거리 임계값 | ChromaDB는 항상 top-k 반환 → 임계값 없으면 무관 사례 오염. `distance < RAG_DISTANCE_THRESHOLD`만 통과 |
| 스키마 가드레일 + 교정형 재시도 | 오류 메시지 되먹임 재요청 = reflection 가장 값싼 형태. silent failure 차단 |
| fallback → needs_manual (안전 방향) | 기획서 9p fail-safe: 불확실성은 항상 사람 검토 쪽으로 |
