# 05. Self-Critic & 가드레일

생성된 답변 초안이 정책 규칙을 실제로 지키는지 LLM 스스로 검증·교정하는 `critic_node`와, LLM 출력 스키마 파괴를 방어하는 `validate_and_repair` 가드레일, 그리고 불확실할 때 안전 방향으로 떨어지는 fail-safe 기본값을 기술한다.

관련 문서: [에이전트 그래프](02-agent-graph.md) | [에이전트 계약](03-agent-contracts.md) | [RAG·툴](04-rag-tools.md) | [데이터 모델](06-data-model.md)

---

## 1. Self-Critic 노드 — 왜 필요한가

`generate_node`가 초안을 한 번 출력하면 끝인 구조는 '단발 생성'이다.  
Self-Refine (Madaan 2023)·Reflexion (Shinn 2023)이 보여주듯, 같은 모델로 **생성→비평→재생성** 루프를 돌리는 것만으로도 품질이 유의미하게 오른다. 이것이 `critic_node`의 근거다(Anthropic *Building Effective Agents* evaluator-optimizer 패턴).

> **두 역할의 견제**: `generate_node`(작성자)와 `critic_node`(검증자)가 서로 다른 관점으로 초안을 다루므로, 한 LLM이 세 번 독백하는 구조와 달리 진짜 2-agent 견제가 된다.

---

## 2. 체크리스트 — 4개 항목

| # | 항목 | 판정 기준 | `CriticResult` 필드 |
|---|------|-----------|---------------------|
| ① | 금지 감정표현 | '너무 속상하다', '정말 화가 나다' 등 감정 노출 → 위반 | `has_forbidden_emotion` |
| ② | 500자 초과 | `len(draft_answer) > 500` → 위반 | `exceeds_500_chars` |
| ③ | 과잉약속 | '100% 환불', '즉시 처리 보장' 등 단정적 보상 약속 → 위반 | `has_overpromise` |
| ④ | 악성·firm 톤 불일치 | `sentiment == malicious` 인데 `answer_tone != firm` → 위반 | `tone_mismatch` |

항목 중 **하나라도** 위반이면 `verdict = revise` 반환.  
모두 통과면 `verdict = pass`.  
가드 초과 시 `verdict = block` (→ `fallback_node`).

---

## 3. verdict 흐름도

```
generate_node
     │
     ▼
critic_node ──── 체크리스트 평가
     │
     ├── verdict == pass
     │      ├── route == sensitive AND critic_loops < 2 → [강제 revise, 루프 계속]
     │      └── 그 외 → approval_gate_node
     │
     ├── verdict == revise AND critic_loops < MAX_CRITIC_LOOPS(=2)
     │      └── revise_reason 포함 → generate_node 루프백
     │
     └── verdict == block  OR  critic_loops >= MAX_CRITIC_LOOPS
            └── fallback_node (needs_manual)
```

> **sensitive 경로 강제 2회**: `route == sensitive`이면 `critic_loops >= 2`를 충족해야만 `pass`가 `approval_gate`로 통과된다. 1회 통과는 루프를 계속한다.

---

## 4. Pydantic 계약

```python
class CriticResult(BaseModel):
    verdict: CriticVerdict                # pass | revise | block
    has_forbidden_emotion: bool
    exceeds_500_chars: bool
    has_overpromise: bool
    tone_mismatch: bool
    revise_reason: str                    # 위반 사유 — generate 루프백 프롬프트에 되먹임
```

---

## 5. critic_node 의사코드

```python
def critic_node(state: GraphState) -> GraphState:
    draft   = state["draft_answer"]
    tone    = state["answer_tone"]
    senti   = state["sentiment"]
    route   = state["route"]
    loops   = state["critic_loops"]

    # 체크리스트 평가 (LLM 또는 규칙 혼용)
    raw = llm.invoke(CRITIC_PROMPT.format(
        draft=draft, tone=tone, sentiment=senti
    ))
    result, err = validate_and_repair(raw, CriticResult, state["schema_retries"])
    if result is None:
        state["error_log"].append(f"critic schema fail: {err}")
        result = CriticResult(
            verdict=CriticVerdict.block,
            has_forbidden_emotion=False,
            exceeds_500_chars=False,
            has_overpromise=False,
            tone_mismatch=False,
            revise_reason="schema parse failed"
        )

    state["critic_result"] = result
    state["critic_loops"]  = loops + 1

    # sensitive 강제 2회 — pass라도 루프가 덜 돌았으면 revise로 내림
    if (result.verdict == CriticVerdict.pass_
            and route == RouteDecision.sensitive
            and state["critic_loops"] < 2):
        result.verdict      = CriticVerdict.revise
        result.revise_reason = "sensitive route requires min 2 critic loops"

    return state
```

---

## 6. conditional_edge — critic 분기 함수

```python
def after_critic(state: GraphState) -> str:
    verdict = state["critic_result"].verdict
    loops   = state["critic_loops"]

    if verdict == CriticVerdict.block or loops >= MAX_CRITIC_LOOPS:
        return "fallback"
    if verdict == CriticVerdict.revise:
        return "generate"     # revise_reason 포함 상태로 루프백
    return "approval_gate"    # pass
```

`builder.add_conditional_edges("critic", after_critic, {"generate": "generate", "approval_gate": "approval_gate", "fallback": "fallback"})`

---

## 7. revise 루프백 — generate 재진입 프롬프트

critic이 `revise`를 반환하면 `state["critic_result"]`에 사유가 담긴 채로 `generate_node`로 돌아간다.  
`generate_node`는 이를 프롬프트에 포함한다:

```python
GENERATE_REVISE_SECTION = """
[이전 초안이 다음 이유로 반려되었습니다]
{revise_reason}

위 문제를 수정하여 새 초안을 작성하십시오.
"""
```

---

## 8. 스키마 가드레일 — validate_and_repair

### 8-1. 왜 필요한가

LLM JSON 출력은 trailing comma·한국어 enum 오타·따옴표 오류로 자주 깨진다(피드백 §6 "silent failure").  
`validate_and_repair`는 **파싱 실패 → 오류 되먹임 → 1회 교정 재요청** 흐름으로 이를 방어한다.

### 8-2. 함수 계약

```python
def validate_and_repair(
    raw_output: str,
    schema: type[BaseModel],
    retries_so_far: int
) -> tuple[BaseModel | None, str | None]:
    """
    Returns:
        (검증 통과 객체, None)       — 성공
        (None, 오류메시지)           — 실패 (호출 노드가 fallback 처리)
    """
```

### 8-3. 흐름도

```
LLM 원본 출력 (raw_output)
         │
         ▼
   json.loads() 파싱
         │
    ┌────┴────┐
   실패      성공
    │         │
    │         ▼
    │   schema(**parsed)  ← Pydantic 검증
    │         │
    │    ┌────┴────┐
    │   실패      성공
    │    │         │
    └────┘         ▼
         │     (model, None) 반환 ✓
         │
    retries_so_far >= MAX_SCHEMA_RETRIES?
         ├── Yes → (None, err) 반환 → 호출 노드가 fallback 처리
         └── No  → 오류메시지 + 원본 출력 → LLM 교정 재요청
                         │
                         ▼
                   재귀 1회 (retries+1)
```

### 8-4. 교정 재요청 프롬프트 스니펫

```python
REPAIR_PROMPT = """
다음 JSON 출력이 스키마 검증에 실패했습니다.

[실패 이유]
{error_message}

[직전 출력]
{raw_output}

위 오류를 수정하여 올바른 JSON만 반환하십시오. 허용 enum 값:
sentiment: positive | negative | malicious
risk_level: low | medium | high
...
"""
```

### 8-5. 상수

| 상수 | 권장값 | 설명 |
|------|--------|------|
| `MAX_SCHEMA_RETRIES` | 1 | 교정 재요청 최대 횟수. 초과 시 `fallback_node` |
| `MAX_CRITIC_LOOPS` | 2 | critic→generate 루프 최대 횟수 |
| `MAX_GEN_RETRIES` | 1 | 답변 생성 자체 실패 재시도 (기획서 9페이지 준수) |

---

## 9. fail-safe 기본값

피드백 §9페이지 "예외 처리 모범"에서 도출한 원칙: **불확실성을 항상 안전(사람 검토) 방향으로 보낸다**.

| 상황 | 기본값 | 이유 |
|------|--------|------|
| 분류 결과 `is_ambiguous == True` | `risk_level = medium`, `requires_approval = True` | 최악을 저위험으로 분류하는 오류 방지 |
| RAG `distance > RAG_DISTANCE_THRESHOLD` | `rag_hit = False`, 단독 생성 폴백 | 무관 사례 오염 차단 |
| `gen_retries >= MAX_GEN_RETRIES` | `make_safe_fallback()` 호출, `status = needs_manual` | 빈 초안보다 '정중한 사과 1문장'이 UX 우수 |
| `critic_result.verdict == block` | `fallback_node` → `approval_gate(pending)` | block을 자동 게시로 흘리지 않음 |
| `schema_retries >= MAX_SCHEMA_RETRIES` | `fallback_node`, `error_log` 기록 | silent failure 차단 |

### make_safe_fallback 계약

```python
def make_safe_fallback(
    sentiment: Sentiment,
    review_type: ReviewType
) -> str:
    """
    항상 정중한 1문장 반환 (실패 불가능 설계).
    예: '소중한 의견 감사합니다. 불편을 드린 점 진심으로 사과드리며 빠르게 확인하겠습니다.'
    """
```

---

## 10. 전체 가드레일 레이어 요약

```
[LLM 출력]
    │
    ├─ 1. validate_and_repair()     ← 스키마 파괴 방어 (모든 LLM 노드)
    │
    ├─ 2. critic_node 체크리스트    ← 정책 규칙 집행 (generate 이후)
    │
    ├─ 3. MAX_* 가드 상수           ← 루프 무한반복 방지
    │
    └─ 4. fail-safe 기본값          ← 불확실 → 안전 방향 폴백
```

이 네 레이어가 함께 작동해 '원칙'이 선언에 그치지 않고 **집행되는 규칙**이 된다.

---

## 11. 참고 문헌

- Madaan et al. (2023) *Self-Refine: Iterative Refinement with Self-Feedback* — critic→revise 루프 근거
- Shinn et al. (2023) *Reflexion: Language Agents with Verbal Reinforcement Learning* — 언어적 피드백 메모리 재활용 근거
- Anthropic, Schluntz & Zhang (2024) *Building Effective Agents* — evaluator-optimizer 패턴, workflow vs agent 구분
- LangGraph 공식 문서 — `add_conditional_edges`, `StateGraph` 루프백 구현
