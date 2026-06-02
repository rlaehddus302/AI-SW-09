# 00 — 제품 개요 & 에이전트 전환

이 문서는 9조 리뷰 대응 에이전트의 제품 정의·페르소나·핵심 가치를 정리하고,  
초기 고정 3단 파이프라인이 어떤 변환을 거쳐 자율 에이전트로 발전했는지 설명한다.

---

## 1. 제품 정의

**리뷰 대응 에이전트**는 소상공인이 받은 고객 리뷰를 위험도·유형별로 자율 분류하고,  
작성한 답변 초안을 스스로 검증·교정한 뒤 사장님의 최종 확인을 거쳐 게시하는 AI 에이전트 서비스다.

> "리뷰 위험도를 스스로 판단해 처리 경로를 바꾸고, 작성한 답변을 스스로 검증·교정한다."
> — Anthropic *Building Effective Agents* 의 routing + evaluator-optimizer 패턴 직접 구현

**기술 스택:** LangGraph · Upstage Solar LLM · ChromaDB · FastAPI · React · MySQL

---

## 2. 핵심 페르소나 — 김사장

| 항목 | 내용 |
|------|------|
| 이름 | 김사장 (30~50대 자영업자, 치킨집 운영) |
| 고통 | 하루 10건 이상 리뷰, 답변 하나에 10~20분 소요. 악성 리뷰에 감정적 대응 후 후회 경험 有 |
| 목표 | 리뷰 답변을 5분 이내에 처리, 악성 리뷰는 잘못 올라가지 않게 확인 후 게시 |
| 수용 조건 | 초안이 70% 이상 그대로 쓸 수 있는 수준, 민감 리뷰는 반드시 내가 확인 |

---

## 3. 핵심 가치 (Why We Build This)

1. **시간 절약** — 리뷰 1건당 처리 시간 10분 → 1분 이내 (자동 분기 + 초안 생성)
2. **감정 보호** — 악성 리뷰에 LLM이 firm 톤 초안을 먼저 제시, 사장님 감정 소모 차단
3. **안전 게시** — 고위험·악성은 무조건 승인 게이트. "자동 게시로 흘리지 않음"이 KPI
4. **성장 메모리** — 사장님 수정본을 ChromaDB에 write-back해 쓸수록 사장님 말투를 학습

---

## 4. 초기 설계 vs. 에이전트 전환

### 4-1. 초기 설계: 고정 3단 파이프라인 (Workflow)

```
START → 분류LLM → 해석LLM → 답변생성LLM → 승인게이트 → END
```

모든 리뷰가 동일한 3단계를 무조건 통과. 경로 분기 없음, 자기검증 없음, 메모리 성장 없음.  
Anthropic *Building Effective Agents* 기준: **workflow** (고정 경로 DAG), 에이전트가 아님.

### 4-2. 에이전트 전환: 추가된 4가지 능력

| 에이전트 능력 | 추가 요소 | 근거 |
|--------------|----------|------|
| **자율 라우팅** | `router_node` + conditional edge (fast_thanks / standard / sensitive) | Anthropic routing 패턴 |
| **도구 사용** | `lookup_store_policy` tool (ReAct 스타일, MySQL 정책 조회) | ReAct (Yao 2022) |
| **자기 검증·교정** | `critic_node` → generate 루프백 (Self-Critic) | Self-Refine (Madaan 2023) |
| **성장 메모리** | `writeback_node` → ChromaDB write-back | Generative Agents (Park 2023) |

---

## 5. 자율성 표 (Autonomy Spectrum)

> *Anthropic Building Effective Agents* 자율성 스펙트럼을 9조 설계에 매핑한 표.

| 행동 | 유형 | 담당 노드 | 자율성 |
|------|------|----------|--------|
| 리뷰 분류 (sentiment / type / risk) | 자동 실행 | `classify` | LLM 1회 변환 |
| 멀티이슈 분해 (issues 배열) | 자동 실행 | `classify` | LLM 1회 변환 |
| **처리 경로 선택** (fast_thanks / standard / sensitive) | **자율 실행** | `router` | 규칙 함수 → conditional edge 분기 |
| 핵심 이슈 해석 + 톤 결정 | 자동 실행 | `interpret` | LLM 1회 변환 |
| 유사 사례 검색 (RAG) | 자동 실행 | `retrieve` | 거리 임계값 필터 |
| **정책 조회 tool 호출 여부 결정** | **자율 실행** | `generate` | ReAct thought → lookup 호출 |
| 답변 초안 생성 | 자동 실행 | `generate` | LLM 1회 변환 |
| **답변 자기검증 후 재작성 여부 결정** | **자율 실행** | `critic` | verdict → revise 루프백 또는 pass |
| 위험도별 승인 게이트 분기 | 자동 실행 | `approval_gate` | requires_approval 플래그 |
| 사장님 수정본 메모리 적재 | 자동 실행 | `writeback` | ChromaDB add |
| 가드 초과 / 분류 실패 안전 처리 | 자동 실행 | `fallback` | fail-safe 템플릿 + needs_manual |

**굵게** 표시된 3행이 초기 워크플로에 없었던 에이전트 능력이다.

---

## 6. 전체 흐름 요약 (ASCII 다이어그램)

```
START
  │
  ▼
[classify]  ─── 분류 실패 / schema 재시도 초과 ───────────────────┐
  │ 분류 성공                                                       │
  ▼                                                                 │
[router] ──────────────────────────────────────────────────────────┤
  │ fast_thanks          │ standard / sensitive                     │
  ▼                      ▼                                          │
[generate] ◄──── [interpret] → [retrieve] → [generate]            │
  │                                              │                  │
  ▼                                              │                  │
[critic] ◄────────────────────────────────────── ┘                 │
  │ pass (sensitive: loops≥2)    │ revise (loops<MAX)  │ block      │
  ▼                              ▼                     │            │
[approval_gate] ◄──── generate ◄──┘                   └──────────► │
  │ auto_approved / held                                            │
  ▼                                                   [fallback] ◄─┘
 END                                                      │
  ▲                                                       ▼
  │                                               [approval_gate]
  │ owner_approved / owner_revised                       │ pending
  │                                                      ▼
[writeback] ──────────────────────────────────────────► END
```

---

## 7. 핵심 상수 (구현 시 단일 진실원천)

```python
MAX_CRITIC_LOOPS     = 2   # sensitive 경로는 최소 2회 강제
MAX_GEN_RETRIES      = 1   # 기획서 준수 (생성 실패 재시도 1회)
MAX_SCHEMA_RETRIES   = 1   # 교정형 재시도 1회 후 fallback
RAG_DISTANCE_THRESHOLD = 0.4  # ChromaDB 거리 임계값 (미달만 통과)
```

---

## 8. 관련 문서

| 문서 | 내용 |
|------|------|
| [01-architecture.md](01-architecture.md) | 기술 스택·컴포넌트 구성·배포 범위 |
| [02-agent-graph.md](02-agent-graph.md) | LangGraph StateGraph 전체 노드·엣지 정의 |
| [03-agent-contracts.md](03-agent-contracts.md) | 노드별 입출력 계약·프롬프트 스케치 |
| [04-rag-tools.md](04-rag-tools.md) | ChromaDB RAG + lookup_store_policy + write-back |
| [05-critic-guardrails.md](05-critic-guardrails.md) | Self-Critic 체크리스트·가드레일·스키마 검증 |
| [06-data-model.md](06-data-model.md) | GraphState Pydantic 스키마·Enum 전체 정의 |
| [07-evaluation-kpi.md](07-evaluation-kpi.md) | KPI 측정 방법·목데이터 엣지케이스 세트 |
| [08-implementation-plan.md](08-implementation-plan.md) | 1.5주 마일스톤·우선순위 로드맵 |
