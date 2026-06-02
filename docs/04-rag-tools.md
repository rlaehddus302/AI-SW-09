# RAG & 정책조회 Tool

이 문서는 리뷰 대응 에이전트의 세 가지 데이터 접근 메커니즘—유사 사례 검색(RAG), 가게 정책 조회 tool, 사장님 확정본 write-back 메모리—의 계약(contract)과 동작 규칙을 정의한다.
전체 노드 흐름은 [에이전트 그래프](02-agent-graph.md)를, 각 노드의 입출력 계약은 [에이전트 계약서](03-agent-contracts.md)를 참조하라.

---

## 1. 전체 데이터 흐름 개요

```
┌─────────────────────────────────────────────────────────────────┐
│  ChromaDB (벡터 DB)               MySQL (관계형 DB)              │
│  ┌─────────────────────┐          ┌──────────────────────┐      │
│  │  review_reply_pairs │          │  store_policy        │      │
│  │  (review, reply,    │◄──write  │  (store_id, field,   │      │
│  │   type, risk,       │  -back   │   value, updated_at) │      │
│  │   channel, tags,    │          └──────────────────────┘      │
│  │   embedding)        │               ▲                        │
│  └─────────┬───────────┘               │ lookup                 │
│            │ similarity search         │                        │
└────────────┼───────────────────────────┼────────────────────────┘
             │                           │
       retrieve_node               generate_node
       (RAG 검색)                  (ReAct tool-loop)
             │                           │
             └────────┬──────────────────┘
                      │
                 draft_answer
```

---

## 2. RAG 유사 사례 검색

### 2-1. ChromaDB 저장 스키마

사전 제작 20~30개 seed pair + write-back으로 누적되는 사례를 단일 컬렉션(`review_reply_pairs`)에 저장한다.

```python
# 컬렉션 메타데이터 필드 (필터 가능)
{
    "review_type": ReviewType,     # 예: "delivery_delay"
    "risk_level": RiskLevel,       # 예: "high"
    "order_channel": OrderChannel, # 예: "delivery"
    "tags": list[str],             # 예: ["high_edit"]
    "source": str,                 # "seed" | "writeback"
}
# document: review 원문
# 별도 메타데이터: reply (답변 본문) — ChromaDB metadata 필드로 저장
```

### 2-2. `retrieve_similar_cases` 툴 계약

```python
def retrieve_similar_cases(
    review_text: str,
    order_channel: OrderChannel,
    top_k: int = 3,
    distance_threshold: float = RAG_DISTANCE_THRESHOLD,  # 기본값 0.4
) -> list[RetrievedCase]:
    """
    1. ChromaDB에서 review_text 임베딩으로 top_k 검색
    2. order_channel 메타데이터 필터 적용
    3. distance < distance_threshold 인 항목만 반환
    4. 통과분 없으면 빈 리스트 반환 → 호출자가 rag_hit=False 처리
    """
```

**반환 타입:**

```python
class RetrievedCase(BaseModel):
    review: str
    reply: str
    review_type: ReviewType
    risk_level: RiskLevel
    order_channel: OrderChannel
    distance: float      # 작을수록 유사 (ChromaDB L2/cosine)
    tags: list[str]      # 예: ["high_edit"]
```

**실패 처리:**
- ChromaDB 연결 실패 → 빈 리스트 반환 + `error_log`에 기록
- `rag_hit = False`로 단독 생성 폴백 (파이프라인 중단 금지)

### 2-3. 거리 임계값(RAG_DISTANCE_THRESHOLD) 필요성

> ChromaDB는 "유사 사례 없음"을 자동으로 반환하지 않는다. `top_k=3`을 요청하면 무관한 사례라도 반드시 3개를 돌려준다. 임계값 없이 사용하면 무관한 사례가 답변을 오염시킨다.

| distance 값 | 해석 | 처리 |
|---|---|---|
| < 0.4 (기본 임계값) | 충분히 유사 | 검색 결과에 포함 |
| ≥ 0.4 | 비유사 (무관) | 제외 |
| 통과분 없음 | RAG 미스 | `rag_hit=False` → 단독 생성 |

임계값은 seed pair 20~30개로 캘리브레이션 후 `RAG_DISTANCE_THRESHOLD` 상수로 관리한다. 첫 배포 전 10개 이상의 리뷰로 precision/recall을 확인하고 조정하라.

### 2-4. `retrieve_node` 내부 의사코드

```python
def retrieve_node(state: GraphState) -> dict:
    cases = retrieve_similar_cases(
        review_text=state["review_text"],
        order_channel=state["order_channel"],
        top_k=3,
        distance_threshold=RAG_DISTANCE_THRESHOLD,
    )
    return {
        "retrieved_cases": cases,
        "rag_hit": len(cases) > 0,
    }
```

> `fast_thanks` 경로(긍정·저위험)는 `retrieve_node`를 건너뛰고 `generate_node`에서 감사 템플릿을 바로 생성한다. 비용·지연 절감이 목적이다.

---

## 3. 가게 정책 조회 Tool (ReAct 스타일)

### 3-1. 왜 정적 프롬프트 주입이 아닌가

기존 기획은 원산지·운영시간 등을 프롬프트에 통째로 주입했다(정적 주입). 이 방식은:
- 가게 정책이 바뀌어도 프롬프트를 수동으로 수정해야 한다.
- 사용하지 않는 정보도 항상 컨텍스트를 차지한다.
- LLM이 정책 DB에 없는 정보를 지어낼(환각) 위험이 있다.

`lookup_store_policy`를 tool로 분리하고 ReAct 패턴으로 호출하면:
- LLM이 **필요하다고 판단할 때만** 조회 (동적 조회)
- 조회 결과가 없으면 "해당 정보 미등록"으로 우회 → 환각 차단
- Feedback 요구사항("ReAct식 정책조회 tool")을 직접 구현

> **ReAct(Yao 2022)**: LLM이 추론(Thought)과 행동(Act: tool 호출)을 번갈아 수행하며 외부 사실을 가져오는 에이전트 패턴. 단발 호출과 에이전트를 구분하는 핵심 요소.

### 3-2. `lookup_store_policy` 툴 계약

```python
def lookup_store_policy(
    store_id: str,
    field: PolicyField,
) -> StorePolicyResult:
    """
    MySQL store_policy 테이블에서 store_id + field로 조회.
    조회 성공 시 found=True, value에 실제 값.
    필드 없음 또는 DB 오류 시 found=False, value=None.
    """
```

**`PolicyField` enum:**

| 값 | 의미 | 예시 반환값 |
|---|---|---|
| `origin` | 원산지 정보 | `"닭고기 국내산(브라질산 일부)"` |
| `operating_hours` | 운영 시간 | `"평일 11:00-22:00, 주말 10:00-23:00"` |
| `refund_policy` | 환불 정책 | `"배달 오류 시 전액 환불 가능"` |
| `hygiene_policy` | 위생 정책 | `"HACCP 인증, 월 2회 점검"` |
| `menu` | 메뉴 정보 | `"후라이드·양념·간장 3종, 1마리 18,000원"` |

**반환 타입:**

```python
class StorePolicyResult(BaseModel):
    found: bool
    field: PolicyField
    value: str | None
    source: str  # 예: "mysql.store_policy"
```

**실패 처리 규칙:**

```python
# found=False 반환 시 generate_node 처리 규칙
if not policy_result.found:
    # 환각 금지: 없는 정보를 답변에 지어내지 않는다
    # "해당 정보가 등록되어 있지 않아 확인이 어렵습니다." 문구로 우회
    pass
```

### 3-3. `generate_node` ReAct tool-loop 의사코드

```python
def generate_node(state: GraphState) -> dict:
    tool_calls: list[ToolCall] = list(state["tool_calls"])
    step = len(tool_calls)
    MAX_TOOL_STEPS = 3  # 무한 루프 방지

    # critic revise 루프백이면 사유를 프롬프트에 되먹임
    revise_hint = ""
    if state["critic_result"] and state["critic_result"].verdict == CriticVerdict.revise:
        revise_hint = f"\n[교정 요청] {state['critic_result'].revise_reason}"

    prompt = build_generate_prompt(state, revise_hint)

    while step < MAX_TOOL_STEPS:
        raw = call_llm(prompt)
        parsed = parse_react_output(raw)  # {"thought":..., "action":..., "answer":...}

        if parsed.get("action"):
            # tool 호출 필요
            tool_name = parsed["action"]["tool"]
            args = parsed["action"]["args"]

            if tool_name == "lookup_store_policy":
                result = lookup_store_policy(**args)
            else:
                result = StorePolicyResult(found=False, field=args.get("field", "menu"), value=None, source="unknown")

            tc = ToolCall(
                thought=parsed["thought"],
                tool_name=tool_name,
                args=args,
                result=str(result),
                step=step,
            )
            tool_calls.append(tc)
            # tool 결과를 프롬프트에 추가하고 다음 단계
            prompt = append_tool_result(prompt, tc)
            step += 1

        elif parsed.get("answer"):
            # 최종 답변 생성 완료
            draft = parsed["answer"]
            validated, err = validate_and_repair(draft, str, state["schema_retries"])
            if err:
                # 교정형 재시도
                return handle_schema_error(state, err, tool_calls)
            return {"draft_answer": draft, "tool_calls": tool_calls}

        else:
            break  # 파싱 실패 → 아래 실패 처리

    # MAX_TOOL_STEPS 초과 또는 파싱 실패
    return handle_gen_failure(state, tool_calls)
```

**ToolCall 기록 스키마:**

```python
class ToolCall(BaseModel):
    thought: str   # LLM 추론 과정 ("원산지 정보가 필요하므로 조회한다")
    tool_name: str # "lookup_store_policy"
    args: dict     # {"store_id": "store_001", "field": "origin"}
    result: str    # 툴 반환 요약
    step: int      # 0-based 단계 번호
```

### 3-4. ReAct 출력 형식 (LLM 프롬프트 계약)

```
Thought: 이 리뷰에서 원산지 정보가 필요하다.
Action: lookup_store_policy(store_id="store_001", field="origin")
Observation: found=True, value="닭고기 국내산(브라질산 일부)"
Thought: 원산지 정보를 확인했으므로 답변에 반영한다.
Answer: 안녕하세요. 사용하시는 닭고기는 국내산(일부 브라질산)을 사용하고 있습니다. ...
```

---

## 4. Write-back 메모리 (성장형 RAG)

### 4-1. 왜 write-back이 필요한가

> **Generative Agents(Park 2023)**: 경험을 memory stream에 축적하고 이후 행동에 반영하는 에이전트 메모리 구조. 단순 검색(read-only)이 아니라 경험이 누적될수록 행동이 개선되는 살아있는 메모리.

기본 RAG는 seed pair 20~30개를 평생 읽기만 한다. 사장님이 초안을 수정·확정한 답변을 write-back하면:
- 쓸수록 **사장님 말투와 정책을 학습**하는 검색 결과
- `high_edit` 태깅으로 수정폭이 큰 케이스를 우선 검색 (문제 패턴 집중)
- 임베딩 add 한 줄 수준의 low-effort 변경

### 4-2. write-back 발동 조건

```
approval_status in {owner_approved, owner_revised}
    └─ writeback_node 실행
       └─ write_back_case(...) 호출

approval_status == auto_approved
    └─ writeback_node 건너뜀 (END 직행)
    └─ 이유: 자동 승인 답변은 아직 사장님 검증 미완료
```

### 4-3. `write_back_case` 툴 계약

```python
def write_back_case(
    review_text: str,
    final_reply: str,
    review_type: ReviewType,
    risk_level: RiskLevel,
    order_channel: OrderChannel,
    owner_edited: bool,
) -> WriteBackResult:
    """
    ChromaDB review_reply_pairs 컬렉션에 새 document 추가.
    owner_edited=True이면 tags에 "high_edit" 포함.
    """
```

**반환 타입:**

```python
class WriteBackResult(BaseModel):
    added: bool
    doc_id: str
    tags: list[str]  # owner_edited=True면 ["high_edit"] 포함
```

**`high_edit` 가중치 메커니즘:**

```python
# retrieve_similar_cases 내부에서 high_edit 케이스 우선 처리
# ChromaDB 메타데이터 필터로 high_edit 있는 항목을 top_k에 먼저 포함
# (정확한 구현: high_edit 항목의 distance에 보정값 -0.05 적용 또는 별도 쿼리 후 merge)
```

**실패 처리:**
- ChromaDB add 실패 → `added=False` + `error_log` 기록
- 파이프라인은 `done` 유지 (메모리 적재 실패가 사용자 답변을 막지 않음)

### 4-4. `writeback_node` 의사코드

```python
def writeback_node(state: GraphState) -> dict:
    if state["final_answer"] is None:
        return {"status": PipelineStatus.failed, "error_log": state["error_log"] + ["writeback: final_answer is None"]}

    result = write_back_case(
        review_text=state["review_text"],
        final_reply=state["final_answer"],
        review_type=state["review_type"],
        risk_level=state["risk_level"],
        order_channel=state["order_channel"],
        owner_edited=state["owner_edited"],
    )

    if not result.added:
        # 실패해도 파이프라인은 완료 처리
        return {
            "status": PipelineStatus.done,
            "error_log": state["error_log"] + ["writeback: ChromaDB add failed"],
        }

    return {"status": PipelineStatus.done}
```

---

## 5. 스키마 가드레일 (`validate_and_repair`)

모든 LLM 노드 출력은 pydantic 검증을 거친다. 검증 실패 시 오류 메시지를 되먹여 1회 교정형 재요청을 보낸다.

```python
def validate_and_repair(
    raw_output: str,
    schema: type[BaseModel],
    retries_so_far: int,
) -> tuple[BaseModel | None, str | None]:
    """
    성공: (검증된 객체, None)
    실패: (None, 오류메시지)  →  호출 노드가 재요청 또는 fallback 처리
    """
```

**교정형 재요청 프롬프트 패턴:**

```
[이전 출력]
{raw_output}

[오류]
{error_message}

위 JSON에 오류가 있습니다. 오류를 수정해 올바른 JSON만 반환하세요.
허용되는 sentiment 값: positive, negative, malicious
허용되는 risk_level 값: low, medium, high
```

**가드 조건:**

| 조건 | 처리 |
|---|---|
| `retries_so_far < MAX_SCHEMA_RETRIES` | 교정형 재요청 1회 |
| `retries_so_far >= MAX_SCHEMA_RETRIES` | `(None, 오류)` 반환 → 호출 노드가 `fallback_node`로 |

> `MAX_SCHEMA_RETRIES = 1` — 재시도 1회 초과 시 수동 확인이 더 안전하다.

---

## 6. 상수 정리

```python
# rag_tools.py 또는 config.py 상단에 선언
RAG_DISTANCE_THRESHOLD = 0.4   # ChromaDB L2 거리 임계값 (캘리브레이션 후 조정)
MAX_SCHEMA_RETRIES = 1          # 스키마 검증 교정 재시도 최대 횟수
MAX_GEN_RETRIES = 1             # 답변 생성 실패 재시도 최대 횟수
MAX_TOOL_STEPS = 3              # ReAct tool-loop 최대 단계 수
```

---

## 7. 관련 문서

| 문서 | 내용 |
|---|---|
| [아키텍처 개요](01-architecture.md) | 전체 시스템 구성 및 기술 스택 |
| [에이전트 그래프](02-agent-graph.md) | LangGraph 노드/엣지/conditional_edge 정의 |
| [에이전트 계약서](03-agent-contracts.md) | 각 노드의 reads/writes/실패처리 계약 |
| [Critic & 가드레일](05-critic-guardrails.md) | self-critic 체크리스트 및 루프백 조건 |
| [데이터 모델](06-data-model.md) | GraphState 전체 스키마 및 Pydantic 모델 |
