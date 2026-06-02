# 08. 1.5주 구현 플랜

이 문서는 feedback 기반 필수 3개 과제(조건부 라우팅·Self-Critic·스키마 가드레일)를 중심으로,
1.5주(약 10일) 안에 '파이프라인'을 '에이전트'로 전환하는 데 필요한 일정·구현 순서·엣지케이스 목데이터 기준을 정의한다.

---

## 전체 일정 개요

```
Day 1-2   기반 세팅          환경·스키마·목데이터
Day 3-4   classify + router  분류 + 조건부 라우팅
Day 5-6   generate + critic  답변 생성 + Self-Critic 루프
Day 7     RAG + tools        retrieve + lookup_store_policy
Day 8     approval + write   승인 게이트 + write-back
Day 9     통합·엣지케이스      전 경로 실행 검증 + 목데이터 엣지케이스
Day 10    발표 준비           데모 시나리오 정리 + KPI 측정
```

---

## Phase 0 — 기반 세팅 (Day 1-2)

### 목표
- 공유 스키마·상수·목데이터 완성 → 이후 노드 개발을 병렬로 진행 가능하게 함

### 0-1. 의존성 및 상수 정의

```python
# config.py
MAX_CRITIC_LOOPS    = 2     # sensitive 경로는 최소 2회 강제
MAX_GEN_RETRIES     = 1     # 기획서 9페이지 준수
MAX_SCHEMA_RETRIES  = 1     # 교정형 재시도 1회
RAG_DISTANCE_THRESHOLD = 0.4   # ChromaDB L2 기준; 초과 시 rag_hit=False (캘리브레이션 후 config.py 관리)
```

### 0-2. Pydantic 모델 정의

[에이전트 계약](03-agent-contracts.md) 및 [데이터 모델](06-data-model.md) 문서의 `GraphState`, `Issue`,
`ClassificationResult`, `CriticResult`, `Interpretation` 등을 `models.py` 한 파일에 구현한다.

```python
# models.py (핵심 발췌 — 전체는 06-data-model.md 참조)
from enum import Enum
from typing import Optional
from pydantic import BaseModel

class Sentiment(str, Enum):
    positive  = "positive"
    negative  = "negative"
    malicious = "malicious"

class RiskLevel(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"

class RouteDecision(str, Enum):
    fast_thanks = "fast_thanks"
    standard    = "standard"
    sensitive   = "sensitive"

class CriticVerdict(str, Enum):
    pass_   = "pass"   # 'pass'는 Python 예약어라 alias 처리
    revise  = "revise"
    block   = "block"

class Issue(BaseModel):
    aspect:      str
    sentiment:   Sentiment
    review_type: ReviewType
    risk_level:  RiskLevel

class GraphState(TypedDict):
    review_id:        str
    review_text:      str
    order_channel:    OrderChannel
    store_id:         str
    sentiment:        Optional[Sentiment]
    review_type:      Optional[ReviewType]
    risk_level:       Optional[RiskLevel]
    issues:           list[Issue]
    route:            Optional[RouteDecision]
    interpretation:   Optional[Interpretation]
    answer_tone:      Optional[AnswerTone]
    retrieved_cases:  list[RetrievedCase]
    rag_hit:          bool
    draft_answer:     str
    tool_calls:       list[ToolCall]
    critic_result:    Optional[CriticResult]
    critic_loops:     int
    schema_retries:   int
    gen_retries:      int
    requires_approval: bool
    approval_status:  ApprovalStatus
    final_answer:     Optional[str]
    owner_edited:     bool
    status:           PipelineStatus
    error_log:        list[str]
```

### 0-3. 목데이터 설계 (엣지케이스 포함)

총 25건. 분류 번호는 `R-001` ~ `R-025`. 카테고리 분포: 긍정5 / 부정단일8 / 부정복합4 / 악성3 / 엣지5 (07-evaluation-kpi.md §2-1 정렬).

| ID | 리뷰 요약 | 유형 | 위험도 | 기대 route | 엣지케이스 목적 |
|----|----------|------|--------|-----------|----------------|
| R-001 | "맛있어요 또 올게요" | praise | low | fast_thanks | 정상 긍정 |
| R-002 | "배달 30분 늦었어요" | delivery_delay | low | standard | 부정 단일이슈 |
| R-003 | "밥에서 벌레 나왔어요 환불해주세요" | foreign_object + refund_request | high | sensitive | 복합이슈 + 고위험 |
| R-004 | "다신 안 와요 신고할게요" | (malicious) | high | sensitive | 악성 + firm 톤 강제 |
| R-005 | "치킨은 맛있는데 콜라가 빠졌고 배달이 1시간 걸렸어요" | food_taste + delivery_delay | medium | standard | 멀티이슈 분해 검증 |
| R-006 | "" (빈 문자열) | — | — | fallback | 빈 입력 처리 |
| R-007 | "원산지가 어디예요? 국내산인가요?" | etc | low | fast_thanks | lookup_store_policy 트리거 |
| R-008 | "환불 정책이 어떻게 되나요" | refund_request | medium | standard | lookup_store_policy 트리거 |
| R-009 | [500자 초과 장문 불만] | unkind_service | medium | standard | critic 500자 검증 |
| R-010 | "이 새끼들아 다 죽어버려" | (malicious) | high | sensitive | 극단적 악성 + firm 톤 |
| R-011 | "포장이 다 찌그러져서 왔어요 사장님 진짜 최악" | packaging_defect | medium | standard | 부정 감정 포함 |
| R-012 | "좀 비싼 것 같지만 맛은 인정해요" | price_complaint + praise | low | fast_thanks | 복합이슈 + 긍정 우세 |
| R-013 | "음식이 차갑게 왔어요 두 번째예요" | food_temperature | medium | standard | 반복 민원 암시 |
| R-014 | "사장님이 반말하셨어요" | unkind_service | high | sensitive | 인격 침해 → 고위험 |
| R-015 | JSON-깨진 리뷰 형태 (테스트용 프롬프트 인젝션 시도 포함) | — | — | fallback | 스키마 가드레일 검증 |
| R-016 | "맛있고 친절하고 빠르고 포장도 완벽해요" | praise | low | fast_thanks | 모든 항목 긍정 |
| R-017 | "이물질 신고 보건소 갈게요" | foreign_object | high | sensitive | 민원 예고 + 고위험 |
| R-018 | "가격 올린 거 공지도 없이요? 고발할게요" | price_complaint | high | sensitive | 악성 경계 |
| R-019 | "맛있어요" (한 단어) | praise | low | fast_thanks | 최소 입력 |
| R-020 | 사장님 write-back 이후 유사 리뷰 | food_taste | low | standard | write-back 메모리 검증용 |
| R-021 | "배달기사가 너무 불친절했어요" | unkind_service | medium | standard | 부정 단일이슈 (배달원) |
| R-022 | "음식 양이 너무 적어요" | food_taste | low | standard | 부정 단일이슈 (양 불만) |
| R-023 | "포장도 좋고 맛도 있고 배달도 빨라서 완전 만족해요" | praise | low | fast_thanks | 긍정 다중 항목 |
| R-024 | "음식에 머리카락이 있었어요. 게다가 배달도 1시간 넘게 걸렸어요" | foreign_object + delivery_delay | high | sensitive | 부정 복합이슈 + 고위험 |
| R-025 | "어제 주문한 거랑 오늘 주문한 거 맛이 너무 달라요" | food_taste | medium | standard | 일관성 불만 (반복 엣지) |

---

## Phase 1 — 필수① 조건부 라우팅 (Day 3-4)

> Anthropic "Building Effective Agents" routing 패턴. 고정 DAG → autonomous routing 전환의 핵심.

### 1-1. classify_node 구현

**역할:** 리뷰 → `ClassificationResult` (멀티이슈 분해 포함)

```python
# nodes/classify.py
CLASSIFY_PROMPT = """
당신은 음식점 리뷰 분류 전문가입니다.
리뷰를 읽고 아래 JSON 스키마를 정확히 채워 반환하세요.
이슈가 여러 개라면 issues 배열에 모두 나열하세요(최소 1개).

[리뷰]
{review_text}

[출력 스키마]
{{
  "sentiment": "<positive|negative|malicious>",
  "review_type": "<delivery_delay|foreign_object|food_taste|food_temperature|unkind_service|price_complaint|packaging_defect|refund_request|praise|etc>",
  "risk_level": "<low|medium|high>",
  "issues": [
    {{"aspect": "...", "sentiment": "...", "review_type": "...", "risk_level": "..."}}
  ],
  "is_ambiguous": false
}}
규칙:
- sentiment/review_type/risk_level 은 issues 중 최고위험 이슈 기준
- 악성 리뷰는 sentiment=malicious, review_type=etc, risk_level=high
- 애매하면 is_ambiguous=true, risk_level=medium
"""

def classify_node(state: GraphState) -> GraphState:
    raw = call_llm(CLASSIFY_PROMPT.format(review_text=state["review_text"]))
    result, err = validate_and_repair(raw, ClassificationResult, state["schema_retries"])
    if result is None:
        state["error_log"].append(f"classify schema error: {err}")
        state["schema_retries"] += 1
        if state["schema_retries"] >= MAX_SCHEMA_RETRIES:
            state["status"] = PipelineStatus.needs_manual
            return state
        # 교정형 재시도: 오류 메시지를 프롬프트에 되먹임
        retry_prompt = CLASSIFY_PROMPT.format(review_text=state["review_text"])
        retry_prompt += f"\n\n[직전 출력]\n{raw}\n[오류]\n{err}\n위 오류를 수정해 다시 출력하세요."
        raw2 = call_llm(retry_prompt)
        result, err2 = validate_and_repair(raw2, ClassificationResult, state["schema_retries"])
        if result is None:
            state["status"] = PipelineStatus.needs_manual
            state["error_log"].append(f"classify retry failed: {err2}")
            return state
    # 결과 반영
    state["sentiment"]    = result.sentiment
    state["review_type"]  = result.review_type
    state["risk_level"]   = result.risk_level
    state["issues"]       = result.issues
    if result.is_ambiguous:
        state["requires_approval"] = True
    return state
```

**조건부 엣지:**

```python
def classify_edge(state: GraphState) -> str:
    if state["status"] == PipelineStatus.needs_manual:
        return "fallback"
    return "router"
```

### 1-2. router_node 구현

**역할:** LLM 없음(규칙 함수). `sentiment` + `risk_level` → `route` + `answer_tone` 결정.

```python
# nodes/router.py
def router_node(state: GraphState) -> GraphState:
    s = state["sentiment"]
    r = state["risk_level"]

    # malicious 최우선
    if s == Sentiment.malicious:
        state["route"]             = RouteDecision.sensitive
        state["answer_tone"]       = AnswerTone.firm
        state["requires_approval"] = True

    # positive 우선 분기: answer_tone=thanks 보존 (03-agent-contracts.md 표 정렬)
    elif s == Sentiment.positive:
        if r == RiskLevel.low:
            state["route"]             = RouteDecision.fast_thanks
            state["answer_tone"]       = AnswerTone.thanks
            state["requires_approval"] = False
        elif r == RiskLevel.high:
            state["route"]             = RouteDecision.sensitive
            state["answer_tone"]       = AnswerTone.thanks   # positive이므로 thanks 유지
            state["requires_approval"] = True
        else:  # medium
            state["route"]             = RouteDecision.standard
            state["answer_tone"]       = AnswerTone.thanks
            # requires_approval은 classify 단계 설정값 유지

    elif r == RiskLevel.high:
        state["route"]             = RouteDecision.sensitive
        state["answer_tone"]       = AnswerTone.apology
        state["requires_approval"] = True

    else:  # negative / medium
        state["route"]             = RouteDecision.standard
        state["answer_tone"]       = AnswerTone.apology
        # requires_approval은 classify 단계 설정값 유지

    return state

def router_edge(state: GraphState) -> str:
    """LangGraph conditional_edge 함수."""
    route = state["route"]
    if route == RouteDecision.fast_thanks:
        return "generate"   # interpret·retrieve 생략
    return "interpret"      # standard·sensitive
```

**라우팅 결정 요약표:**

| sentiment | risk_level | route | requires_approval | answer_tone | 경유 노드 |
|-----------|-----------|-------|:-----------------:|-------------|----------|
| positive | low | fast_thanks | False | thanks | generate → critic → gate |
| positive | medium | standard | False | thanks | interpret → retrieve → generate → critic → gate |
| positive | high | sensitive | True | thanks | interpret → retrieve → generate → critic(×2) → gate |
| negative | low/medium | standard | False/True | apology | interpret → retrieve → generate → critic → gate |
| negative | high | sensitive | True | apology | interpret → retrieve → generate → critic(×2) → gate |
| malicious | any | sensitive | True | firm | interpret → retrieve → generate → critic(×2) → gate |

---

## Phase 2 — 필수② Self-Critic 루프 (Day 5-6)

> Self-Refine (Madaan 2023) 축소판. 생성·비평·교정 루프가 단발 호출과 에이전트를 가르는 지점.

### 2-1. generate_node 구현 (ReAct tool-loop 포함)

```python
# nodes/generate.py
GENERATE_PROMPT = """
아래 정보를 바탕으로 사장님 대신 고객 리뷰에 답변하세요.

[리뷰]
{review_text}

[이슈 목록]
{issues_json}

[답변 톤] {answer_tone}
[참고 사례]
{cases_text}

[정책 조회 결과]
{policy_text}

[revise 사유 — 이전 답변의 문제점]
{revise_reason}

규칙:
- 500자 이내
- 감정적 표현(억울하다/화가나다/짜증나다) 금지
- 과잉약속('100% 환불' 등) 금지
- 악성 리뷰(firm 톤)는 감정 없이 사실 중심으로만
- 각 이슈를 한 문장씩 포함
"""

def generate_node(state: GraphState) -> GraphState:
    # ReAct: needs_policy_lookup 힌트 있으면 tool 호출
    policy_text = ""
    if state.get("interpretation") and state["interpretation"].needs_policy_lookup:
        result = lookup_store_policy(state["store_id"], PolicyField.origin)
        state["tool_calls"].append(ToolCall(
            thought="원산지 근거 필요",
            tool_name="lookup_store_policy",
            args={"store_id": state["store_id"], "field": "origin"},
            result=str(result),
            step=len(state["tool_calls"]) + 1
        ))
        if result.found:
            policy_text = f"원산지: {result.value}"

    revise_reason = ""
    if state["critic_result"] and state["critic_result"].verdict == CriticVerdict.revise:
        revise_reason = state["critic_result"].revise_reason

    prompt = GENERATE_PROMPT.format(
        review_text=state["review_text"],
        issues_json=json.dumps([i.dict() for i in state["issues"]], ensure_ascii=False),
        answer_tone=state["answer_tone"],
        cases_text=_format_cases(state["retrieved_cases"]),
        policy_text=policy_text or "조회 없음",
        revise_reason=revise_reason or "없음"
    )

    try:
        draft = call_llm(prompt)
        if not draft.strip():
            raise ValueError("empty output")
        state["draft_answer"] = draft
    except Exception as e:
        state["gen_retries"] += 1
        state["error_log"].append(f"generate failed: {e}")
        if state["gen_retries"] >= MAX_GEN_RETRIES:
            state["status"] = PipelineStatus.needs_manual
    return state
```

### 2-2. critic_node 구현

```python
# nodes/critic.py
CRITIC_PROMPT = """
아래 답변 초안을 체크리스트로 평가하고 JSON으로 반환하세요.

[초안]
{draft_answer}

[맥락]
- 답변 톤: {answer_tone}
- 감정 유형: {sentiment}
- 위험도: {risk_level}

체크리스트:
1. 금지 감정표현 포함? (억울/화/짜증/분노 류)
2. 500자 초과?
3. 과잉약속 포함? ('100% 환불' / '반드시 보상' 등)
4. 악성 리뷰인데 firm 톤 미유지? (사과/공감 과다)

[출력 스키마]
{{
  "verdict": "<pass|revise|block>",
  "has_forbidden_emotion": false,
  "exceeds_500_chars": false,
  "has_overpromise": false,
  "tone_mismatch": false,
  "revise_reason": "위반 사유 (없으면 빈 문자열)"
}}

판정 기준:
- 위반 0개: verdict=pass
- 위반 1~2개: verdict=revise (revise_reason 필수)
- 위반 3개 이상 또는 심각한 단일 위반: verdict=block
"""

def critic_node(state: GraphState) -> GraphState:
    # sensitive 경로는 critic_loops < 2 이면 강제 revise
    raw = call_llm(CRITIC_PROMPT.format(
        draft_answer=state["draft_answer"],
        answer_tone=state["answer_tone"],
        sentiment=state["sentiment"],
        risk_level=state["risk_level"]
    ))
    result, err = validate_and_repair(raw, CriticResult, 0)
    if result is None:
        # 크리틱 파싱 실패 시 안전 처리: revise로 처리
        state["critic_result"] = CriticResult(
            verdict=CriticVerdict.revise,
            has_forbidden_emotion=False, exceeds_500_chars=False,
            has_overpromise=False, tone_mismatch=False,
            revise_reason=f"critic parse error: {err}"
        )
    else:
        # sensitive 경로: 최소 2회 critic 강제
        if (state["route"] == RouteDecision.sensitive
                and state["critic_loops"] < 2
                and result.verdict == CriticVerdict.pass_):
            result.verdict = CriticVerdict.revise
            result.revise_reason = "sensitive 경로 최소 2회 검증 미충족 — 재검토"
        state["critic_result"] = result

    state["critic_loops"] += 1
    return state

def critic_edge(state: GraphState) -> str:
    verdict = state["critic_result"].verdict
    loops   = state["critic_loops"]
    if verdict == CriticVerdict.pass_:
        return "approval_gate"
    if verdict == CriticVerdict.revise and loops < MAX_CRITIC_LOOPS:
        return "generate"   # 루프백
    return "fallback"       # block 또는 루프 초과
```

**critic 루프 흐름:**

```
generate ──► critic ──[pass]──► approval_gate
               │
           [revise, loops < MAX]
               │
               ▼
           generate  (revise_reason 포함 재생성)
               │
             critic  (loops += 1)
               │
           [block or loops >= MAX]
               │
               ▼
           fallback
```

---

## Phase 3 — 필수③ 스키마 가드레일 (Day 3-6, 각 노드에 공통 적용)

> "reflection의 가장 값싼 형태" (feedback 6번). 교정형 재시도로 silent failure 차단.

### 3-1. validate_and_repair 구현

```python
# tools/guardrails.py
from pydantic import ValidationError
import json, re

def validate_and_repair(
    raw_output: str,
    schema: type[BaseModel],
    retries_so_far: int
) -> tuple[BaseModel | None, str | None]:
    """
    LLM 출력을 pydantic 모델로 검증.
    반환: (검증 통과 객체, None) | (None, 오류메시지)
    """
    # JSON 블록 추출 (```json ... ``` 래핑 허용)
    text = raw_output.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()

    try:
        data = json.loads(text)
        obj  = schema(**data)
        return obj, None
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}"
    except ValidationError as e:
        return None, f"Schema validation error: {e}"
```

### 3-2. 노드별 가드레일 적용 패턴

모든 LLM 노드(classify, interpret, generate, critic)에 동일 패턴 적용:

```
1. call_llm(prompt) → raw
2. validate_and_repair(raw, Schema, schema_retries) → (obj, err)
3. err 있으면:
   a. schema_retries += 1
   b. error_log.append(err)
   c. schema_retries < MAX_SCHEMA_RETRIES 이면:
        교정형 재시도 프롬프트 = 원본 + "\n[직전 출력]\n" + raw + "\n[오류]\n" + err
        raw2 = call_llm(교정형 재시도 프롬프트)
        (obj, err2) = validate_and_repair(raw2, Schema, schema_retries)
   d. 여전히 err 이면 → status=needs_manual, fallback 행
4. obj 있으면 state에 반영
```

---

## Phase 4 — RAG + Tools (Day 7)

> [RAG·툴 계약](04-rag-tools.md) 문서 참조. Day 7에 retrieve_node와 lookup_store_policy 연동.

### 4-1. retrieve_node

```python
# nodes/retrieve.py
def retrieve_node(state: GraphState) -> GraphState:
    try:
        cases = retrieve_similar_cases(
            review_text=state["review_text"],
            order_channel=state["order_channel"],
            top_k=3,
            distance_threshold=RAG_DISTANCE_THRESHOLD
        )
        state["retrieved_cases"] = cases
        state["rag_hit"]         = len(cases) > 0
    except Exception as e:
        state["retrieved_cases"] = []
        state["rag_hit"]         = False
        state["error_log"].append(f"retrieve failed: {e}")
        # ChromaDB 장애라도 파이프라인 계속 진행
    return state
```

### 4-2. lookup_store_policy (MySQL 조회 툴)

```python
# tools/policy.py
def lookup_store_policy(store_id: str, field: PolicyField) -> StorePolicyResult:
    """
    MySQL store_policy 테이블에서 field 조회.
    실패 또는 미등록이면 found=False, value=None 반환(환각 금지).
    """
    try:
        row = db.execute(
            "SELECT value FROM store_policy WHERE store_id=%s AND field=%s",
            (store_id, field.value)
        ).fetchone()
        if row:
            return StorePolicyResult(found=True, field=field, value=row[0], source="mysql.store_policy")
        return StorePolicyResult(found=False, field=field, value=None, source="mysql.store_policy")
    except Exception as e:
        return StorePolicyResult(found=False, field=field, value=None, source=f"error:{e}")
```

---

## Phase 5 — 승인 게이트 + Write-back (Day 8)

### 5-1. approval_gate_node (human-in-the-loop)

```python
# nodes/approval_gate.py
def approval_gate_node(state: GraphState) -> GraphState:
    if not state["requires_approval"]:
        state["approval_status"] = ApprovalStatus.auto_approved
        state["final_answer"]    = state["draft_answer"]
        state["status"]          = PipelineStatus.done
    else:
        state["approval_status"] = ApprovalStatus.pending
        # FastAPI endpoint가 사장님 액션을 기다림
        # 사장님 승인/수정 결과는 /api/reviews/{id}/approve 로 수신
    return state
```

**사장님 액션 수신 API (FastAPI 최소 구현):**

```python
# api/approve.py
@router.post("/reviews/{review_id}/approve")
def approve_review(review_id: str, body: ApproveRequest):
    """
    body: { "action": "approve"|"revise"|"hold", "final_answer": str|None }
    """
    state = load_state(review_id)
    if body.action == "approve":
        state["approval_status"] = ApprovalStatus.owner_approved
        state["final_answer"]    = state["draft_answer"]
        state["owner_edited"]    = False
    elif body.action == "revise":
        state["approval_status"] = ApprovalStatus.owner_revised
        state["final_answer"]    = body.final_answer
        state["owner_edited"]    = True
    else:
        state["approval_status"] = ApprovalStatus.held
        state["status"]          = PipelineStatus.done
    save_state(review_id, state)
    # writeback_node 트리거
    if state["approval_status"] in (ApprovalStatus.owner_approved, ApprovalStatus.owner_revised):
        run_writeback(state)
    return {"ok": True}
```

### 5-2. writeback_node

```python
# nodes/writeback.py
def writeback_node(state: GraphState) -> GraphState:
    result = write_back_case(
        review_text=state["review_text"],
        final_reply=state["final_answer"],
        review_type=state["review_type"],
        risk_level=state["risk_level"],
        order_channel=state["order_channel"],
        owner_edited=state["owner_edited"]
    )
    if not result.added:
        state["error_log"].append(f"writeback failed: doc_id={result.doc_id}")
        # write-back 실패가 최종 답변을 막으면 안 됨 → done 유지
    state["status"] = PipelineStatus.done
    return state
```

---

## Phase 6 — 통합·엣지케이스 검증 (Day 9)

### 6-1. LangGraph 그래프 조립

```python
# graph.py
from langgraph.graph import StateGraph, END

def build_graph() -> StateGraph:
    g = StateGraph(GraphState)

    g.add_node("classify",      classify_node)
    g.add_node("router",        router_node)
    g.add_node("interpret",     interpret_node)
    g.add_node("retrieve",      retrieve_node)
    g.add_node("generate",      generate_node)
    g.add_node("critic",        critic_node)
    g.add_node("approval_gate", approval_gate_node)
    g.add_node("writeback",     writeback_node)
    g.add_node("fallback",      fallback_node)

    g.set_entry_point("classify")

    g.add_conditional_edges("classify", classify_edge,
        {"router": "router", "fallback": "fallback"})

    g.add_conditional_edges("router", router_edge,
        {"generate": "generate", "interpret": "interpret"})

    g.add_edge("interpret", "retrieve")
    g.add_edge("retrieve",  "generate")

    g.add_conditional_edges("generate", generate_edge,
        {"critic": "critic", "fallback": "fallback"})

    g.add_conditional_edges("critic", critic_edge,
        {"approval_gate": "approval_gate",
         "generate":      "generate",
         "fallback":      "fallback"})

    g.add_conditional_edges("approval_gate", approval_gate_edge,
        {"writeback": "writeback", END: END})

    g.add_edge("fallback",  "approval_gate")
    g.add_edge("writeback", END)

    return g.compile()
```

### 6-2. 엣지케이스 검증 체크리스트

| 케이스 | 목데이터 ID | 검증 포인트 | 기대 결과 |
|--------|-----------|------------|---------|
| 빈 리뷰 입력 | R-006 | classify 스키마 실패 → fallback | status=needs_manual |
| 복합이슈 멀티이슈 분해 | R-005 | issues 배열 2건 이상 | 이슈별 한 문장 답변 |
| 악성 + firm 톤 | R-004, R-010 | critic tone_mismatch=False | route=sensitive, requires_approval=True |
| critic 루프 최대 초과 | R-009(500자 초과 유도) | critic_loops >= MAX_CRITIC_LOOPS | fallback 진입 |
| lookup_store_policy 미등록 | R-007(origin 없음) | found=False | 답변에 '미등록' 우회 문구 |
| RAG miss | distance > threshold | rag_hit=False | 단독 생성, 답변 존재 |
| write-back 이후 재검색 | R-020 | 사장님 확정본이 few-shot으로 검색 | retrieved_cases에 포함 |
| JSON 오류 교정형 재시도 | R-015 | schema_retries=1 후 성공 or fallback | error_log 기록 확인 |
| sensitive 경로 critic 2회 강제 | R-004 | critic_loops==2 후 pass 허용 | approval_gate 진입 |
| 자동 승인 (fast_thanks) | R-001, R-016 | requires_approval=False | auto_approved, writeback 생략 |

---

## Phase 7 — 발표 준비 (Day 10)

### 7-1. 데모 시나리오 (에이전트다움 증명 3장면)

1. **라우팅 분기 시각화** — R-001(fast_thanks 직행)과 R-004(sensitive 경로 critic 2회) 대비
2. **Self-Critic 루프백** — R-009(500자 초과 → revise → 재생성 → pass)
3. **멀티이슈 분해 + write-back** — R-005(복합이슈 분해 → 사장님 수정 → ChromaDB 적재 → R-020 재검색 히트)

### 7-2. KPI 측정 (목데이터 25건 기준)

[평가 KPI](07-evaluation-kpi.md) 문서 기준:

| KPI | 측정 방법 | 목표 |
|-----|---------|------|
| 분류 정확도 | 목데이터 25건 ground truth 라벨 vs classify 출력 | ≥ 80% |
| 라우팅 정확도 | 기대 route vs 실제 route (위 표 참조) | ≥ 90% |
| 악성·고위험 승인게이트 통과율 | sensitive 경로 중 requires_approval=True 비율 | 100% |
| critic 루프 수렴률 | critic_loops 내 pass 도달 비율 | ≥ 85% |
| 스키마 오류 자동교정률 | schema_retries=1 후 성공 비율 | ≥ 80% |
| 답변 500자 준수율 | final_answer len ≤ 500 비율 | 100% |

---

## 의존성 요약

```
Phase 0 (모델·목데이터)
    └─► Phase 1 (classify + router)    ← 필수①
    └─► Phase 3 (스키마 가드레일)       ← 필수③ (Phase 1~2와 동시 진행)
         └─► Phase 2 (generate + critic) ← 필수②
              └─► Phase 4 (RAG + tools)
                   └─► Phase 5 (gate + writeback)
                        └─► Phase 6 (통합 검증)
                             └─► Phase 7 (발표)
```

---

## 관련 문서

- [시스템 개요](00-overview.md)
- [전체 아키텍처](01-architecture.md)
- [에이전트 그래프](02-agent-graph.md)
- [에이전트 계약](03-agent-contracts.md)
- [RAG·툴 계약](04-rag-tools.md)
- [Critic·가드레일](05-critic-guardrails.md)
- [데이터 모델](06-data-model.md)
- [평가 KPI](07-evaluation-kpi.md)
