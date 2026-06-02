# 06. 데이터 모델 & 메모리

이 문서는 리뷰 대응 에이전트 파이프라인에서 사용하는 모든 데이터 구조(Pydantic 스키마, MySQL 테이블, ChromaDB 컬렉션)와 write-back 메모리 전략, FastAPI 엔드포인트 계약을 정의한다. 여기서 확정된 식별자·스키마는 [에이전트 그래프](02-agent-graph.md)와 [에이전트 계약](03-agent-contracts.md)의 단일 진실원천(single source of truth)으로 사용한다.

---

## 1. 열거형(Enums)

```python
from enum import Enum

class Sentiment(str, Enum):
    positive   = "positive"
    negative   = "negative"
    malicious  = "malicious"

class ReviewType(str, Enum):
    delivery_delay   = "delivery_delay"
    foreign_object   = "foreign_object"
    food_taste       = "food_taste"
    food_temperature = "food_temperature"
    unkind_service   = "unkind_service"
    price_complaint  = "price_complaint"
    packaging_defect = "packaging_defect"
    refund_request   = "refund_request"
    praise           = "praise"
    etc              = "etc"

class RiskLevel(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"

class OrderChannel(str, Enum):
    hall     = "hall"
    takeout  = "takeout"
    delivery = "delivery"

class AnswerTone(str, Enum):
    thanks  = "thanks"
    apology = "apology"
    explain = "explain"
    firm    = "firm"

class RouteDecision(str, Enum):
    fast_thanks = "fast_thanks"   # 긍정·저위험 → 해석 생략, 감사 직행
    standard    = "standard"      # 부정·중위험 → 해석+RAG+critic 1회
    sensitive   = "sensitive"     # 악성·고위험 → critic 2회+무조건 게이트

class CriticVerdict(str, Enum):
    pass_   = "pass"    # 통과 → approval_gate 진행
    revise  = "revise"  # 위반 → generate 루프백
    block   = "block"   # 가드 초과 → fallback 강제

class ApprovalStatus(str, Enum):
    auto_approved  = "auto_approved"   # 저위험 자동 승인
    pending        = "pending"         # 사장님 검토 대기
    owner_approved = "owner_approved"  # 사장님 원문 승인
    owner_revised  = "owner_revised"   # 사장님 수정 후 승인 → write-back
    held           = "held"            # 보류

class PipelineStatus(str, Enum):
    running      = "running"
    needs_manual = "needs_manual"  # 분류실패·가드 초과 → 수동 확인
    done         = "done"
    failed       = "failed"

class PolicyField(str, Enum):
    origin          = "origin"
    operating_hours = "operating_hours"
    refund_policy   = "refund_policy"
    hygiene_policy  = "hygiene_policy"
    menu            = "menu"
```

---

## 2. Pydantic 모델

### 2-1. 세부 구조체

```python
from pydantic import BaseModel, Field
from typing import Optional

class Issue(BaseModel):
    """멀티이슈 분해 결과. 복합 리뷰의 각 이슈를 표현."""
    aspect:      str        # 이슈 대상 (예: "배달", "콜라 누락", "치킨 맛")
    sentiment:   Sentiment
    review_type: ReviewType
    risk_level:  RiskLevel

class Interpretation(BaseModel):
    """해석 노드 출력. 핵심 이슈 요약 + 답변 방향."""
    core_issues:          list[str]   # 핵심 이슈 요약 문장 목록
    answer_tone:          AnswerTone
    action_direction:     str         # 사장님 권장 행동 방향
    needs_policy_lookup:  bool        # 원산지·정책 근거 필요 추정 (ReAct 힌트)

class RetrievedCase(BaseModel):
    """RAG 검색 결과 1건."""
    review:       str
    reply:        str
    review_type:  ReviewType
    risk_level:   RiskLevel
    order_channel: OrderChannel
    distance:     float        # 임베딩 거리 (작을수록 유사)
    tags:         list[str]    # 예: ["high_edit"]

class ToolCall(BaseModel):
    """ReAct 루프에서 발생한 툴 호출 기록."""
    thought:   str    # LLM 추론 텍스트
    tool_name: str    # 예: "lookup_store_policy"
    args:      dict
    result:    str    # 툴 반환 요약
    step:      int

class CriticResult(BaseModel):
    """self-critic 노드 평가 결과."""
    verdict:              CriticVerdict
    has_forbidden_emotion: bool   # 금지 감정표현 포함?
    exceeds_500_chars:    bool    # 500자 초과?
    has_overpromise:      bool    # 과잉약속 ("100% 환불") 포함?
    tone_mismatch:        bool    # 악성 리뷰에 firm 톤 미유지?
    revise_reason:        str     # 위반 사유 (generate 루프백 프롬프트에 삽입)
```

### 2-2. LLM 노드 입출력 스키마

```python
class ClassificationResult(BaseModel):
    """classify_node 출력. validate_and_repair 대상."""
    sentiment:    Sentiment
    review_type:  ReviewType
    risk_level:   RiskLevel
    issues:       list[Issue] = Field(min_length=1)  # 최소 1개
    is_ambiguous: bool        # 애매 → risk=medium + requires_approval 폴백
```

JSON 예시 (이물질+배달지연 복합 리뷰):
```json
{
  "sentiment": "negative",
  "review_type": "foreign_object",
  "risk_level": "high",
  "is_ambiguous": false,
  "issues": [
    {"aspect": "치킨", "sentiment": "negative", "review_type": "foreign_object", "risk_level": "high"},
    {"aspect": "배달", "sentiment": "negative", "review_type": "delivery_delay",  "risk_level": "medium"}
  ]
}
```

### 2-3. 툴 입출력 스키마

```python
class StorePolicyResult(BaseModel):
    """lookup_store_policy 반환값."""
    found:  bool
    field:  PolicyField
    value:  Optional[str]  # MySQL 미등록 시 None
    source: str            # 예: "mysql.store_policy"

class WriteBackResult(BaseModel):
    """write_back_case 반환값."""
    added:  bool
    doc_id: str
    tags:   list[str]   # owner_edited=True 면 "high_edit" 포함
```

### 2-4. GraphState (LangGraph 상태 전체)

```python
from typing import Optional, TypedDict

# GraphState: TypedDict 정본 — LangGraph 관례, state['key'] 형식으로 접근
class GraphState(TypedDict, total=False):
    # --- 입력 (불변) ---
    review_id:     str
    review_text:   str
    order_channel: OrderChannel
    store_id:      str

    # --- 분류 결과 ---
    sentiment:    Optional[Sentiment]
    review_type:  Optional[ReviewType]
    risk_level:   Optional[RiskLevel]
    issues:       list[Issue]

    # --- 라우팅 ---
    route:        Optional[RouteDecision]
    requires_approval: bool

    # --- 해석 ---
    interpretation: Optional[Interpretation]
    answer_tone:    Optional[AnswerTone]

    # --- RAG ---
    retrieved_cases: list[RetrievedCase]
    rag_hit:         bool

    # --- 생성·검증 ---
    draft_answer:   str
    tool_calls:     list[ToolCall]
    critic_result:  Optional[CriticResult]

    # --- 가드 카운터 ---
    critic_loops:   int
    schema_retries: int
    gen_retries:    int

    # --- 승인 게이트 ---
    approval_status: ApprovalStatus
    final_answer:    Optional[str]
    owner_edited:    bool

    # --- 파이프라인 상태 ---
    status:    PipelineStatus
    error_log: list[str]
```

> **가드 상수** (별도 `config.py`에 정의, 임의 변경 금지):
> ```python
> MAX_CRITIC_LOOPS   = 2   # sensitive 경로는 최소 2회 강제
> MAX_GEN_RETRIES    = 1   # 기획서 준수
> MAX_SCHEMA_RETRIES = 1   # 교정형 재시도 1회
> RAG_DISTANCE_THRESHOLD = 0.4   # 초과 시 단독생성 폴백 (캘리브레이션 후 config.py 관리)
> ```

---

## 3. MySQL 스키마

### 3-1. 가게 정보 테이블

```sql
CREATE TABLE store (
    store_id     VARCHAR(36)  PRIMARY KEY,  -- UUID
    store_name   VARCHAR(100) NOT NULL,
    owner_id     VARCHAR(36)  NOT NULL,
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- lookup_store_policy 툴이 조회하는 정책 테이블
CREATE TABLE store_policy (
    id         INT          AUTO_INCREMENT PRIMARY KEY,
    store_id   VARCHAR(36)  NOT NULL,
    field      ENUM('origin','operating_hours','refund_policy','hygiene_policy','menu') NOT NULL,
    value      TEXT         NOT NULL,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_store_field (store_id, field),
    FOREIGN KEY (store_id) REFERENCES store(store_id)
);
```

정책 행 예시:
```
store_id | field          | value
---------|----------------|----------------------------------------
s001     | origin         | 닭고기 국내산(브라질산 일부)
s001     | refund_policy  | 수령 당일 이물질 확인 시 전액 환불
s001     | operating_hours| 매일 11:00-22:00 (화요일 휴무)
```

### 3-2. 리뷰 테이블

```sql
CREATE TABLE review (
    review_id     VARCHAR(36)  PRIMARY KEY,
    store_id      VARCHAR(36)  NOT NULL,
    review_text   TEXT         NOT NULL,
    order_channel ENUM('hall','takeout','delivery') NOT NULL,
    platform      VARCHAR(50),              -- 배달의민족, 쿠팡이츠 등
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (store_id) REFERENCES store(store_id)
);

-- 에이전트 처리 결과 저장
CREATE TABLE review_pipeline_result (
    id              INT          AUTO_INCREMENT PRIMARY KEY,
    review_id       VARCHAR(36)  NOT NULL,
    sentiment       ENUM('positive','negative','malicious'),
    review_type     VARCHAR(50),
    risk_level      ENUM('low','medium','high'),
    route           ENUM('fast_thanks','standard','sensitive'),
    draft_answer    TEXT,
    final_answer    TEXT,
    approval_status ENUM('auto_approved','pending','owner_approved','owner_revised','held'),
    owner_edited    TINYINT(1)   DEFAULT 0,
    pipeline_status ENUM('running','needs_manual','done','failed') DEFAULT 'running',
    critic_loops    INT          DEFAULT 0,
    processed_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_id) REFERENCES review(review_id)
);
```

> 1.5주 범위에서 `review_pipeline_result`는 데모용 조회(GET)와 승인 상태 갱신(PATCH)에만 사용한다. ORM은 SQLAlchemy 경량 사용 또는 raw query 허용.

---

## 4. ChromaDB 컬렉션

### 4-1. 컬렉션 구조

```
컬렉션명: review_reply_pairs
  ├─ documents: 리뷰 본문 (임베딩 대상)
  ├─ metadatas: 아래 필드 참조
  └─ ids: doc_id (UUID)
```

메타데이터 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `reply` | str | 확정 답변 본문 |
| `review_type` | str | ReviewType enum 값 |
| `risk_level` | str | RiskLevel enum 값 |
| `order_channel` | str | OrderChannel enum 값 |
| `store_id` | str | 가게별 네임스페이스 분리 키 |
| `owner_edited` | bool | 사장님 수정 여부 |
| `tags` | str | 콤마 구분 태그 (예: `"high_edit"`) |
| `created_at` | str | ISO 8601 |

### 4-2. 검색 쿼리 패턴

```python
# retrieve_node 에서 사용
results = collection.query(
    query_texts=[review_text],
    n_results=3,
    where={
        "order_channel": order_channel.value,
        "store_id": store_id,
    },
)

# 거리 임계값 필터 (RAG_DISTANCE_THRESHOLD = 0.4)
passed = [
    RetrievedCase(
        review=doc,
        reply=meta["reply"],
        review_type=ReviewType(meta["review_type"]),
        risk_level=RiskLevel(meta["risk_level"]),
        order_channel=OrderChannel(meta["order_channel"]),
        distance=dist,
        tags=meta.get("tags", "").split(","),
    )
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )
    if dist <= RAG_DISTANCE_THRESHOLD
]
# passed가 비면 rag_hit=False → 단독 생성 폴백
```

> ChromaDB 기본 거리 메트릭은 L2(유클리드). `RAG_DISTANCE_THRESHOLD=0.4`는 초기값이며 캘리브레이션 후 config.py에서 관리 권장. [RAG 도구 상세](04-rag-tools.md) 참조.

---

## 5. Write-back 메모리

사장님이 승인·수정한 답변을 ChromaDB에 재적재해 다음 retrieval에 반영하는 **성장 메모리** 구조다 (Generative Agents 방식).

```
흐름:
  approval_gate (owner_approved / owner_revised)
      │
      ▼
  writeback_node
      │  write_back_case() 호출
      ▼
  ChromaDB.add(document=review_text, metadata={reply, ..., tags})
      │
      ▼
  다음 유사 리뷰 조회 시 이 pair가 few-shot으로 검색됨
```

```python
def write_back_case(
    review_text:  str,
    final_reply:  str,
    review_type:  ReviewType,
    risk_level:   RiskLevel,
    order_channel: OrderChannel,
    owner_edited: bool,
    store_id:     str,
) -> WriteBackResult:
    tags = ["high_edit"] if owner_edited else []
    doc_id = str(uuid4())
    try:
        collection.add(
            documents=[review_text],
            metadatas=[{
                "reply":         final_reply,
                "review_type":   review_type.value,
                "risk_level":    risk_level.value,
                "order_channel": order_channel.value,
                "store_id":      store_id,
                "owner_edited":  owner_edited,
                "tags":          ",".join(tags),
                "created_at":    datetime.utcnow().isoformat(),
            }],
            ids=[doc_id],
        )
        return WriteBackResult(added=True, doc_id=doc_id, tags=tags)
    except Exception as e:
        # ChromaDB 실패 → 파이프라인 done 유지 (메모리 적재 실패가 답변을 막지 않음)
        return WriteBackResult(added=False, doc_id="", tags=[])
```

**`high_edit` 태깅 전략:** `owner_edited=True`인 케이스는 메타데이터 `tags`에 `"high_edit"`을 포함시켜 저장한다. 향후 검색 시 `where={"tags": {"$contains": "high_edit"}}` 필터로 사장님 수정본을 우선 검색하도록 가중할 수 있다. (1.5주 MVP에서는 태깅까지만 구현하고, 검색 가중은 선택 확장)

---

## 6. 스키마 가드레일 — validate_and_repair

LLM 출력(JSON 문자열)을 Pydantic 모델로 검증하고, 실패 시 오류 메시지를 되먹여 1회 재요청한다. silent failure 차단.

```python
import json
from pydantic import ValidationError

def validate_and_repair(
    raw_output:      str,
    schema:          type[BaseModel],
    retries_so_far:  int,
) -> tuple[BaseModel | None, str | None]:
    """
    Returns:
        (검증 통과 객체, None)        — 성공
        (None, 오류메시지)            — 실패 (호출 노드가 재시도 또는 fallback 처리)
    """
    try:
        data = json.loads(raw_output)
        obj  = schema.model_validate(data)
        return obj, None
    except (json.JSONDecodeError, ValidationError) as e:
        err_msg = str(e)
        if retries_so_far >= MAX_SCHEMA_RETRIES:
            return None, f"[SCHEMA_FAIL] 재시도 한도 초과: {err_msg}"
        return None, err_msg   # 호출 노드가 오류메시지를 프롬프트에 붙여 재요청
```

각 LLM 노드에서의 사용 패턴:
```python
# classify_node 예시
raw = llm.invoke(classify_prompt)
obj, err = validate_and_repair(raw, ClassificationResult, state["schema_retries"])
if obj is None:
    if err.startswith("[SCHEMA_FAIL]"):
        # fallback으로 분기
        return {**state, "status": PipelineStatus.needs_manual, "error_log": state["error_log"] + [err]}
    # 교정형 재시도: 오류메시지를 프롬프트에 주입
    repair_prompt = f"{classify_prompt}\n\n[이전 출력]\n{raw}\n[오류]\n{err}\n위 오류를 수정해 다시 출력하세요."
    raw2 = llm.invoke(repair_prompt)
    obj2, err2 = validate_and_repair(raw2, ClassificationResult, state["schema_retries"] + 1)
    if obj2 is None:
        return {**state, "schema_retries": state["schema_retries"] + 1,
                "status": PipelineStatus.needs_manual, "error_log": state["error_log"] + [err2]}
    obj = obj2
```

---

## 7. FastAPI 엔드포인트

백엔드 인프라는 최소화. 에이전트 로직 호출과 승인 게이트 상태 갱신에 집중한다.

### 7-1. 리뷰 처리 요청

```
POST /reviews/{review_id}/process
```

**Request Body:**
```python
class ProcessReviewRequest(BaseModel):
    review_text:   str
    order_channel: OrderChannel
    store_id:      str
```

**Response:**
```python
class ProcessReviewResponse(BaseModel):
    review_id:       str
    route:           RouteDecision
    draft_answer:    str
    risk_level:      RiskLevel
    requires_approval: bool
    approval_status: ApprovalStatus
    pipeline_status: PipelineStatus
```

동작: `ReviewGraph.run(state)` 호출 → 파이프라인 실행 → `GraphState` 최종값을 위 응답으로 매핑.

---

### 7-2. 승인 게이트 — 사장님 확정

```
PATCH /reviews/{review_id}/approve
```

**Request Body:**
```python
class ApproveReviewRequest(BaseModel):
    action:       Literal["approve", "revise", "hold"]
    final_answer: Optional[str] = None  # action="revise" 시 수정본
```

**Response:**
```python
class ApproveReviewResponse(BaseModel):
    review_id:       str
    approval_status: ApprovalStatus
    final_answer:    Optional[str]
    writeback_done:  bool   # ChromaDB write-back 완료 여부
```

동작:
- `action="approve"` → `approval_status=owner_approved`, `final_answer=draft_answer`
- `action="revise"` → `approval_status=owner_revised`, `final_answer=request.final_answer`, `owner_edited=True`
- `action="hold"` → `approval_status=held`
- `owner_approved` 또는 `owner_revised` 시 `writeback_node` 트리거

---

### 7-3. 대기 중인 리뷰 목록 (대시보드용)

```
GET /reviews/pending?store_id={store_id}&order_channel={channel}
```

**Response:**
```python
class PendingReviewItem(BaseModel):
    review_id:    str
    review_text:  str
    draft_answer: str
    risk_level:   RiskLevel
    review_type:  ReviewType
    order_channel: OrderChannel
    created_at:   str

class PendingReviewListResponse(BaseModel):
    items: list[PendingReviewItem]
    total: int
```

`order_channel` 쿼리 파라미터로 [아키텍처 문서](01-architecture.md)의 대시보드 탭 필터(홀/포장/배달)와 연동한다.

---

## 8. 모델 의존성 요약 다이어그램

```
MySQL
  store ──────────────────── store_policy
    │                             │
    │ store_id                    │ lookup_store_policy()
    │                             ▼
    │                       generate_node (ReAct)
    │
  review ─── review_pipeline_result
    │
    │ review_id, review_text, order_channel
    ▼
GraphState ──────────────────────────────────────────────────────────
  classify_node → ClassificationResult (Issue[], Sentiment, RiskLevel)
      │
  router_node  → route (RouteDecision), answer_tone
      │
  interpret_node → Interpretation
      │
  retrieve_node  → RetrievedCase[] ←── ChromaDB (read)
      │                                    ▲
  generate_node  → draft_answer            │ write_back_case()
      │                                    │
  critic_node    → CriticResult            │
      │                                    │
  approval_gate  → ApprovalStatus ─────────┘ (owner_approved/revised)
      │
  writeback_node → WriteBackResult → ChromaDB (write)
```

---

관련 문서: [에이전트 계약](03-agent-contracts.md) · [RAG & 툴](04-rag-tools.md) · [Critic 가드레일](05-critic-guardrails.md) · [평가 KPI](07-evaluation-kpi.md)
