# 에이전트 I/O 계약

각 LLM 노드의 입력·출력 스키마, JSON 계약, 멀티이슈 분해 구조, 라우터 게이트 결정 로직을 의사코드 수준으로 정의한다. 이 문서를 기준으로 각 노드를 독립 구현하고 스키마 가드레일을 적용한다.

관련 문서: [아키텍처 개요](01-architecture.md) · [에이전트 그래프](02-agent-graph.md) · [RAG·툴 계약](04-rag-tools.md) · [Critic·가드레일](05-critic-guardrails.md) · [데이터 모델](06-data-model.md)

---

## 1. 공통 규칙

| 규칙 | 내용 |
|------|------|
| **JSON 강제** | 모든 LLM 노드 출력은 순수 JSON(마크다운 코드블록 금지). 시스템 프롬프트에 명시. |
| **스키마 검증** | `validate_and_repair(raw_output, Schema, retries_so_far)` 로 pydantic 검증. 실패 시 오류메시지를 되먹여 1회 교정형 재요청. `MAX_SCHEMA_RETRIES` 초과 시 `fallback_node` 행. |
| **enum 도메인** | `Sentiment`, `ReviewType`, `RiskLevel`, `AnswerTone` 등 모든 enum은 허용값 집합으로 강제 검증. 한국어 값 입력 시 거부. |
| **불변 입력** | `review_id`, `review_text`, `store_id`, `order_channel` 은 어떤 노드도 덮어쓰지 않는다. |
| **가드 상수** | `MAX_CRITIC_LOOPS = 2`, `MAX_GEN_RETRIES = 1`, `MAX_SCHEMA_RETRIES = 1` |

---

## 2. 분류 노드 (`classify_node`)

> **역할:** 리뷰 1건을 읽고 멀티이슈 분해(issues 배열) + 대표 sentiment/type/risk 산출. 파이프라인의 진입 노드.

### 2-1. 입력

```python
# GraphState에서 읽는 키
review_text: str        # 원본 리뷰 본문 (불변)
order_channel: OrderChannel  # 홀/포장/배달
schema_retries: int     # 스키마 재시도 누적 (가드용)
```

### 2-2. 시스템 프롬프트 구조 (의사코드)

```
당신은 소상공인 리뷰 분류 전문가입니다.
다음 규칙을 지켜 JSON만 출력하세요(다른 텍스트 금지):

1. 리뷰를 읽고 이슈를 분해합니다. 이슈란 "한 가지 주제에 대한 평가"입니다.
   - 예: "치킨 맛있는데 배달 1시간 늦고 콜라 빠졌어요" → 이슈 3개
2. 각 이슈를 {aspect, sentiment, review_type, risk_level}로 표현합니다.
3. 대표값: issues 중 risk_level이 가장 높은 이슈의 값을 대표로 사용합니다.
   - risk 동점이면 sentiment 우선순위: malicious > negative > positive
4. 분류가 애매하면 is_ambiguous=true, risk_level="medium"으로 설정합니다.

허용 값:
- sentiment: positive | negative | malicious
- review_type: delivery_delay | foreign_object | food_taste | food_temperature |
               unkind_service | price_complaint | packaging_defect |
               refund_request | praise | etc
- risk_level: low | medium | high
```

### 2-3. 출력 스키마 (`ClassificationResult`)

```python
class Issue(BaseModel):
    aspect: str          # 이슈 대상 (예: "배달", "콜라 누락", "치킨 맛")
    sentiment: Sentiment
    review_type: ReviewType
    risk_level: RiskLevel

class ClassificationResult(BaseModel):
    sentiment: Sentiment      # 대표 감정 (issues 중 최고위험)
    review_type: ReviewType   # 대표 유형
    risk_level: RiskLevel     # issues 최고 위험도
    issues: list[Issue]       # 멀티이슈 분해 결과 (최소 1개)
    is_ambiguous: bool        # 애매 시 True → risk=medium + 승인필요
```

### 2-4. 출력 JSON 예시

**단순 긍정 리뷰**
```json
{
  "sentiment": "positive",
  "review_type": "praise",
  "risk_level": "low",
  "issues": [
    {
      "aspect": "음식 전반",
      "sentiment": "positive",
      "review_type": "praise",
      "risk_level": "low"
    }
  ],
  "is_ambiguous": false
}
```

**복합 리뷰** ("치킨은 맛있는데 배달 1시간 늦고 콜라가 빠졌어요")
```json
{
  "sentiment": "negative",
  "review_type": "delivery_delay",
  "risk_level": "medium",
  "issues": [
    {
      "aspect": "치킨 맛",
      "sentiment": "positive",
      "review_type": "praise",
      "risk_level": "low"
    },
    {
      "aspect": "배달 시간",
      "sentiment": "negative",
      "review_type": "delivery_delay",
      "risk_level": "medium"
    },
    {
      "aspect": "콜라 누락",
      "sentiment": "negative",
      "review_type": "packaging_defect",
      "risk_level": "medium"
    }
  ],
  "is_ambiguous": false
}
```

**악성 리뷰** ("이거 먹고 배 아팠음. 원산지 어딘지 공개 안 하면 신고할 거임")
```json
{
  "sentiment": "malicious",
  "review_type": "foreign_object",
  "risk_level": "high",
  "issues": [
    {
      "aspect": "식품 안전",
      "sentiment": "malicious",
      "review_type": "foreign_object",
      "risk_level": "high"
    }
  ],
  "is_ambiguous": false
}
```

### 2-5. 노드 의사코드

```python
def classify_node(state: GraphState) -> dict:
    prompt = build_classify_prompt(state["review_text"], state["order_channel"])
    raw = llm.invoke(prompt)

    result, error = validate_and_repair(raw, ClassificationResult, state["schema_retries"])

    if result is None:
        # 스키마 재시도 소진 → fallback
        return {
            "schema_retries": state["schema_retries"] + 1,
            "error_log": state["error_log"] + [f"classify schema fail: {error}"],
            "status": PipelineStatus.needs_manual,
        }

    # 애매 분류 폴백: risk=medium, 승인 강제
    risk = result.risk_level
    requires_approval = result.is_ambiguous

    return {
        "sentiment": result.sentiment,
        "review_type": result.review_type,
        "risk_level": risk,
        "issues": result.issues,
        "requires_approval": requires_approval,
        "schema_retries": 0,  # 성공 시 리셋
        "status": PipelineStatus.running,
    }
```

### 2-6. conditional_edge (classify → 다음)

```python
def after_classify(state: GraphState) -> str:
    if state["status"] == PipelineStatus.needs_manual:
        return "fallback"
    return "router"
```

---

## 3. 라우터 노드 (`router_node`)

> **역할:** 규칙 기반 함수(LLM 아님). `sentiment`, `risk_level`, `issues`를 읽어 처리 경로(`route`)와 `requires_approval`을 결정한다. Anthropic "Building Effective Agents" routing 패턴.

### 3-1. 라우팅 규칙 테이블

| sentiment | risk_level | route | requires_approval | answer_tone 기본값 |
|-----------|-----------|-------|-------------------|-------------------|
| positive | low | `fast_thanks` | False | `thanks` |
| positive | medium | `standard` | False | `thanks` |
| positive | high | `sensitive` | True | `thanks` |
| negative | low | `standard` | False | `apology` |
| negative | medium | `standard` | False | `apology` |
| negative | high | `sensitive` | True | `apology` |
| malicious | * | `sensitive` | True | `firm` |
| * | * (is_ambiguous) | `standard` | True | `apology` |

> **우선순위:** malicious → positive(thanks 톤 보존) → high risk → is_ambiguous → 나머지 순으로 평가.
> positive는 risk와 무관하게 answer_tone=thanks를 유지한다. positive+high는 드물지만 sensitive 경로로 라우팅하되 톤은 thanks.

### 3-2. 멀티이슈 게이트 결정

```python
def compute_max_risk(issues: list[Issue]) -> RiskLevel:
    """issues 배열 중 가장 높은 위험도를 반환."""
    priority = {RiskLevel.high: 2, RiskLevel.medium: 1, RiskLevel.low: 0}
    return max(issues, key=lambda i: priority[i.risk_level]).risk_level
```

`risk_level`은 `classify_node`에서 이미 `issues` 최고값으로 채워지지만, 라우터는 `issues`를 직접 재확인해 일관성을 보장한다.

### 3-3. 노드 의사코드

```python
def router_node(state: GraphState) -> dict:
    sentiment = state["sentiment"]
    risk = state["risk_level"]
    issues = state["issues"]
    # classify가 is_ambiguous를 requires_approval로 이미 반영

    # malicious 최우선
    if sentiment == Sentiment.malicious:
        return {
            "route": RouteDecision.sensitive,
            "requires_approval": True,
            "answer_tone": AnswerTone.firm,
        }

    # positive 우선 분기: sentiment==positive이면 answer_tone=thanks 보존
    # (표의 positive+high → thanks 행과 일치)
    if sentiment == Sentiment.positive:
        if risk == RiskLevel.low:
            return {
                "route": RouteDecision.fast_thanks,
                "requires_approval": False,
                "answer_tone": AnswerTone.thanks,
            }
        elif risk == RiskLevel.high:
            return {
                "route": RouteDecision.sensitive,
                "requires_approval": True,
                "answer_tone": AnswerTone.thanks,   # positive이므로 thanks 유지
            }
        else:  # medium
            return {
                "route": RouteDecision.standard,
                "requires_approval": state["requires_approval"],
                "answer_tone": AnswerTone.thanks,
            }

    # high risk (negative/기타)
    if risk == RiskLevel.high:
        return {
            "route": RouteDecision.sensitive,
            "requires_approval": True,
            "answer_tone": AnswerTone.apology,
        }

    # 나머지 → standard (apology 톤)
    return {
        "route": RouteDecision.standard,
        "requires_approval": state["requires_approval"],  # classify 단계 승인 여부 유지
        "answer_tone": AnswerTone.apology,
    }
```

### 3-4. conditional_edge (router → 다음)

```python
def after_router(state: GraphState) -> str:
    route = state["route"]
    if route == RouteDecision.fast_thanks:
        return "generate"      # interpret·retrieve 생략
    return "interpret"         # standard·sensitive 모두 interpret → retrieve → generate
```

---

## 4. 해석 노드 (`interpret_node`)

> **역할:** 핵심 이슈 요약 + 답변 방향/톤 도출. `standard`·`sensitive` 경로에서만 실행. `fast_thanks`는 건너뜀.

### 4-1. 입력

```python
review_text: str
sentiment: Sentiment
review_type: ReviewType
risk_level: RiskLevel
issues: list[Issue]
```

### 4-2. 시스템 프롬프트 구조 (의사코드)

```
당신은 리뷰 해석 전문가입니다.
다음 리뷰와 분류 결과를 보고 답변 방향을 JSON으로만 출력하세요.

지침:
- core_issues: 리뷰에서 사장님이 실제로 대응해야 할 이슈를 한 줄씩 요약 (issues 배열 기반)
- answer_tone: thanks | apology | explain | firm 중 하나
  * malicious → firm, negative high risk → apology, 사실 오해 → explain
- action_direction: 사장님이 취해야 할 구체적 행동 방향 (1문장)
- needs_policy_lookup: 원산지·운영시간·환불 정책 근거가 답변에 필요하면 true
```

### 4-3. 출력 스키마 (`Interpretation`)

```python
class Interpretation(BaseModel):
    core_issues: list[str]     # 핵심 이슈 요약 (issues 수와 대응)
    answer_tone: AnswerTone
    action_direction: str      # 사장님 권장 행동 방향 (1문장)
    needs_policy_lookup: bool  # generate ReAct 힌트
```

### 4-4. 출력 JSON 예시

```json
{
  "core_issues": [
    "배달이 1시간 지연됨",
    "콜라 누락으로 고객 불편"
  ],
  "answer_tone": "apology",
  "action_direction": "지연·누락 사유를 확인하고 재발 방지 조치를 안내한다",
  "needs_policy_lookup": false
}
```

---

## 5. 답변 생성 노드 (`generate_node`)

> **역할:** 해석+RAG+가게정보로 초안 생성. ReAct 스타일로 `lookup_store_policy` 툴 호출 가능. critic의 `revise` 신호 받으면 사유를 반영해 재생성.

### 5-1. 입력

```python
review_text: str
interpretation: Interpretation | None   # fast_thanks 경로는 None
answer_tone: AnswerTone
retrieved_cases: list[RetrievedCase]    # RAG 결과 (빈 리스트 가능)
rag_hit: bool
issues: list[Issue]
critic_result: CriticResult | None      # 루프백 시 채워짐
tool_calls: list[ToolCall]              # ReAct 기록 (누적)
gen_retries: int
schema_retries: int
```

### 5-2. ReAct 툴 루프 구조

```
[Thought] 답변 작성 중 원산지/환불 정책이 필요한가?
[Action]  lookup_store_policy(store_id, field="origin")
[Observation] StorePolicyResult{found:True, value:"닭고기 국내산"}
[Thought] 조회 완료. 이제 답변을 작성한다.
[Answer]  {draft_answer: "...닭고기는 국내산을 사용하고 있습니다..."}
```

- 툴 호출은 `interpretation.needs_policy_lookup == True` 이거나 LLM이 자체 판단 시 발동.
- 툴 호출 결과가 `found=False`이면 해당 정보를 답변에서 **언급하지 않음**(환각 금지).
- 툴 루프 최대 3스텝, 초과 시 현재까지 결과로 답변 생성.

### 5-3. 시스템 프롬프트 핵심 규칙

```
답변 작성 규칙:
1. 500자 이내
2. 금지 감정표현: 억울하다, 황당하다, 사실이 아니다 등 주관적 감정 표현 불가
3. 과잉약속 금지: "100% 환불", "무조건 교환" 등 단정 표현 금지
4. 악성 리뷰(firm 톤): 사실 관계만 서술, 사과 없이 정중하게 단호히
5. 멀티이슈: issues 배열의 각 이슈를 1문장씩 다룰 것
6. RAG 사례(retrieved_cases)가 있으면 참고하되 그대로 복사 금지
7. critic 사유(critic_result.revise_reason)가 있으면 반드시 반영
```

### 5-4. 출력 스키마

```python
class GenerateResult(BaseModel):
    draft_answer: str          # 답변 초안 (500자 이내)
    tool_calls_this_turn: list[ToolCall]  # 이번 생성에서 발생한 툴 호출
```

### 5-5. 출력 JSON 예시

**복합 리뷰 (배달지연 + 누락) — standard 경로**
```json
{
  "draft_answer": "치킨을 맛있게 드셨다니 감사합니다. 배달이 늦어져 많이 불편하셨을 텐데 진심으로 사과드립니다. 콜라가 누락된 점도 확인하였으며, 담당 배달 기사에게 재발 방지를 요청하였습니다.",
  "tool_calls_this_turn": []
}
```

**악성·고위험 — sensitive 경로 (firm 톤)**
```json
{
  "draft_answer": "소중한 의견 감사합니다. 저희 매장은 모든 식재료의 원산지를 법적 기준에 따라 관리하고 있습니다. 불편하신 점은 고객센터를 통해 구체적으로 말씀해 주시면 확인 후 안내드리겠습니다.",
  "tool_calls_this_turn": [
    {
      "thought": "원산지 관련 리뷰이므로 실제 원산지를 조회한다",
      "tool_name": "lookup_store_policy",
      "args": {"store_id": "store_001", "field": "origin"},
      "result": "닭고기 국내산(브라질산 일부)",
      "step": 1
    }
  ]
}
```

### 5-6. 노드 의사코드

```python
def generate_node(state: GraphState) -> dict:
    prompt = build_generate_prompt(state)  # critic_result.revise_reason 포함
    raw = llm.invoke(prompt, tools=[lookup_store_policy])

    result, error = validate_and_repair(raw, GenerateResult, state["schema_retries"])

    if result is None:
        retries = state["schema_retries"] + 1
        if retries >= MAX_SCHEMA_RETRIES:
            return {
                "schema_retries": retries,
                "error_log": state["error_log"] + [f"generate schema fail: {error}"],
                "status": PipelineStatus.needs_manual,
            }
        return {"schema_retries": retries, "error_log": state["error_log"] + [error]}

    if not result.draft_answer.strip():
        # 빈 출력 → gen_retries 카운트
        new_retries = state["gen_retries"] + 1
        if new_retries >= MAX_GEN_RETRIES:
            return {
                "gen_retries": new_retries,
                "error_log": state["error_log"] + ["generate empty output"],
                "status": PipelineStatus.needs_manual,
            }
        return {"gen_retries": new_retries}

    new_tool_calls = state["tool_calls"] + result.tool_calls_this_turn
    return {
        "draft_answer": result.draft_answer,
        "tool_calls": new_tool_calls,
        "gen_retries": 0,
        "schema_retries": 0,
    }
```

### 5-7. conditional_edge (generate → 다음)

```python
def after_generate(state: GraphState) -> str:
    if state["status"] == PipelineStatus.needs_manual:
        return "fallback"
    if state["draft_answer"]:
        return "critic"
    return "fallback"
```

---

## 6. 멀티이슈 분해 흐름 요약

```
리뷰 입력
    │
    ▼
classify_node
    ├─ issues 배열 생성 (각 이슈: {aspect, sentiment, review_type, risk_level})
    ├─ 대표값 = issues 중 최고 risk 이슈의 값
    └─ is_ambiguous → requires_approval=True
    │
    ▼
router_node
    ├─ issues 최고 risk_level로 route·requires_approval 결정
    └─ fast_thanks (low+positive) / standard / sensitive
    │
    ▼
generate_node
    └─ 프롬프트에 issues 배열 전달
       → 각 이슈당 1문장 원칙으로 답변 작성
```

**멀티이슈 예시 (issues 3개 → 답변 3문장)**

| issue.aspect | issue.risk_level | 답변 문장 역할 |
|---|---|---|
| 치킨 맛 (positive/low) | low | 감사 1문장 |
| 배달 시간 (negative/medium) | medium | 사과 1문장 |
| 콜라 누락 (negative/medium) | medium | 재발방지 안내 1문장 |

---

## 7. 스키마 가드레일 + 교정형 재시도

```python
def validate_and_repair(
    raw_output: str,
    schema: type[BaseModel],
    retries_so_far: int
) -> tuple[BaseModel | None, str | None]:
    """
    1. JSON 파싱 시도
    2. pydantic 검증 (enum 도메인 강제)
    3. 실패 시 오류메시지 반환 → 호출 노드가 오류를 프롬프트에 되먹여 재요청
    4. retries_so_far >= MAX_SCHEMA_RETRIES → (None, error) 반환 (fallback 트리거)
    """
    try:
        data = json.loads(raw_output)
        validated = schema.model_validate(data)
        return validated, None
    except (json.JSONDecodeError, ValidationError) as e:
        error_msg = f"스키마 오류: {str(e)}\n직전 출력:\n{raw_output[:300]}"
        return None, error_msg
```

**교정형 재요청 프롬프트 패턴:**
```
이전 출력이 스키마 검증에 실패했습니다.
오류: {error_msg}

위 오류를 수정하여 올바른 JSON을 다시 출력하세요.
허용 값: sentiment = positive | negative | malicious
```

---

## 8. 노드별 Reads/Writes 요약표

| 노드 | 읽는 State 키 | 쓰는 State 키 |
|------|--------------|--------------|
| `classify` | `review_text`, `order_channel`, `schema_retries` | `sentiment`, `review_type`, `risk_level`, `issues`, `requires_approval`, `schema_retries`, `error_log`, `status` |
| `router` | `sentiment`, `risk_level`, `issues` | `route`, `requires_approval`, `answer_tone` |
| `interpret` | `review_text`, `sentiment`, `review_type`, `risk_level`, `issues` | `interpretation`, `answer_tone`, `error_log` |
| `retrieve` | `review_text`, `order_channel`, `review_type`, `issues` | `retrieved_cases`, `rag_hit` |
| `generate` | `review_text`, `interpretation`, `answer_tone`, `retrieved_cases`, `rag_hit`, `issues`, `critic_result`, `tool_calls`, `gen_retries`, `schema_retries` | `draft_answer`, `tool_calls`, `gen_retries`, `schema_retries`, `error_log`, `status` |
| `critic` | `draft_answer`, `answer_tone`, `sentiment`, `risk_level`, `route`, `critic_loops` | `critic_result`, `critic_loops` |
| `approval_gate` | `draft_answer`, `requires_approval`, `risk_level`, `sentiment` | `approval_status`, `final_answer`, `owner_edited`, `status` |
| `writeback` | `review_text`, `final_answer`, `review_type`, `risk_level`, `order_channel`, `owner_edited`, `approval_status` | `status` |
| `fallback` | `error_log`, `sentiment`, `review_type` | `draft_answer`, `requires_approval`, `status`, `approval_status` |

---

## 9. conditional_edge 분기 조건 전체 목록

| from | 조건 | to |
|------|------|----|
| `classify` | `status != needs_manual` | `router` |
| `classify` | `status == needs_manual` (스키마 실패 소진) | `fallback` |
| `router` | `route == fast_thanks` | `generate` |
| `router` | `route in {standard, sensitive}` | `interpret` |
| `interpret` | 항상 | `retrieve` |
| `retrieve` | 항상 | `generate` |
| `generate` | 초안 생성 성공 | `critic` |
| `generate` | `gen_retries >= MAX_GEN_RETRIES OR schema_retries >= MAX_SCHEMA_RETRIES` | `fallback` |
| `critic` | `verdict == pass AND (route != sensitive OR critic_loops >= 2)` | `approval_gate` |
| `critic` | `verdict == revise AND critic_loops < MAX_CRITIC_LOOPS` | `generate` |
| `critic` | `verdict == block OR critic_loops >= MAX_CRITIC_LOOPS` | `fallback` |
| `approval_gate` | `approval_status in {owner_approved, owner_revised}` | `writeback` |
| `approval_gate` | `approval_status in {auto_approved, held}` | `END` |
| `fallback` | 항상 | `approval_gate` |
| `writeback` | 항상 | `END` |

> `sensitive` 경로 critic 강제 2회: `verdict == pass`이더라도 `critic_loops < 2`이면 `generate`로 루프백. 이는 `revise`와 동일한 엣지를 타되, `critic_node` 내부에서 `verdict`를 `revise`로 강제 재설정하거나, conditional_edge 조건에서 `route == sensitive AND critic_loops < 2 → generate`를 추가로 처리한다.
