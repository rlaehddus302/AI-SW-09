# 9조 리뷰 대응 에이전트 — 문서 인덱스 & 설계 철학

이 저장소는 소상공인 리뷰를 **위험도에 따라 스스로 처리 경로를 바꾸고, 작성한 답변을 스스로 검증·교정하는 에이전트**의 설계 문서를 담는다. 고정 분류+생성 파이프라인에서 출발해 자율 라우팅·Self-Critic·Tool Use·Write-back Memory를 더해 에이전트다운 구조로 발전시키는 1.5주 구현 계획을 기록한다.

---

## 문서 목록

| 번호 | 파일 | 내용 |
|------|------|------|
| — | **README.md** (이 파일) | 인덱스 & 설계 철학 |
| 00 | [개요](00-overview.md) | 문제 정의, 목표, 에이전트 vs 파이프라인 구분 |
| 01 | [시스템 아키텍처](01-architecture.md) | 컴포넌트 구성(FastAPI·MySQL·ChromaDB·React), 배포 제외 범위 |
| 02 | [에이전트 그래프](02-agent-graph.md) | LangGraph 노드/엣지/StateGraph 설계, conditional edge 분기 조건 전체 |
| 03 | [에이전트 계약](03-agent-contracts.md) | 노드별 reads/writes, 함수 시그니처, Pydantic 스키마 스케치 |
| 04 | [RAG & 툴](04-rag-tools.md) | ChromaDB 검색·write-back, lookup_store_policy ReAct, 거리 임계값 |
| 05 | [Critic & 가드레일](05-critic-guardrails.md) | Self-Critic 체크리스트, 루프백 조건, 스키마 가드레일 재시도 |
| 06 | [데이터 모델](06-data-model.md) | GraphState 전체 필드, Enum 목록, JSON 예시 |
| 07 | [평가 & KPI](07-evaluation-kpi.md) | 분류정확도·라우팅 안전성·Critic 통과율·응답시간 측정 방법 |
| 08 | [구현 계획](08-implementation-plan.md) | 1.5주 마일스톤, 우선순위, 목데이터 엣지케이스 세트 |

---

## 설계 철학

### "고정 파이프라인"에서 "에이전트"로

피드백의 핵심 지적은 다음 한 문장이다:

> 이름은 '에이전트'지만 실체는 '고정 분류+생성 파이프라인'에 가깝다. 모든 리뷰가 동일한 3단계를 통과하는 결정론적 체인이다.
> — feedback.md, 총평

Anthropic *Building Effective Agents*(Schluntz & Zhang, 2024)는 이 두 구조를 명확히 구분한다.

| 구분 | 정의 | 본 시스템 원형 | 개선 후 |
|------|------|----------------|---------|
| **Workflow** | 고정 DAG, 모든 입력이 동일 경로 | 분류→해석→답변 3단 체인 | — |
| **Agent** | LLM이 상황 따라 경로·툴을 동적 결정 | — | 라우터·Critic·Tool loop |

이 전환을 가능하게 하는 세 개의 레버:

1. **자율 라우팅(Autonomous Routing)** — 분류 결과(sentiment/risk_level)를 `router_node`가 읽어 `fast_thanks / standard / sensitive` 세 경로로 분기한다. LangGraph `conditional_edge` 하나로 구현된다.
2. **Self-Critic 루프(Reflection)** — `critic_node`가 초안을 체크리스트(금지감정·500자·과잉약속·악성 firm 톤)로 평가하고 `revise` 신호를 `generate_node`로 되먹인다. Self-Refine(Madaan et al., 2023) / Reflexion(Shinn et al., 2023)의 축소판.
3. **ReAct Tool Use** — `generate_node`가 원산지·정책 근거 필요 시 `lookup_store_policy` 툴을 호출한다. 정적 프롬프트 주입 대신 동적 조회로 환각을 줄인다(Yao et al., 2022).

### RAG & 승인 게이트 강점 보존

원본 기획의 두 핵심을 그대로 유지한다.

- **RAG** — ChromaDB 유사 사례 검색. `RAG_DISTANCE_THRESHOLD`로 무관 사례 오염을 차단하고, 미통과 시 단독 생성 폴백.
- **승인 게이트(Human-in-the-loop)** — `risk_level=high` / `sentiment=malicious` / 분류 애매 → `requires_approval=True` → 사장님 검토 강제. 악성 리뷰가 자동 게시로 흘러가지 않는 안전성 핵심 KPI.

여기에 **Write-back Memory**를 추가한다. 사장님 확정/수정 답변을 ChromaDB에 재적재해 read-only RAG를 경험 축적형 메모리로 전환한다(Generative Agents, Park et al., 2023). `owner_edited=True`면 `high_edit` 태그로 우선 검색 가중치를 부여한다.

### 과설계 금지 원칙

1.5주 범위를 지키기 위해 다음을 명시적으로 범위 밖으로 뺀다.

- 해석 LLM을 별도 서비스로 분리 — 비용·지연 증가, 라우팅 도입 후 fast_thanks 경로에서 생략 가능
- 리포트 화면 고도화 — 데모 가치 낮음
- 배포(EC2 실환경) — 로컬 실행 기준 데모

---

## 전체 그래프 개요 (ASCII)

```
START
  │
  ▼
[classify] ──(실패/재시도 초과)──────────────────► [fallback]
  │                                                       │
  ▼ (통과)                                                │
[router] ──fast_thanks──► [generate] ◄──────────────────┘
  │                           ▲  │
  │standard/sensitive         │  │(초안 생성 성공)
  ▼                           │  ▼
[interpret]            [critic]  ◄── (revise 루프백)
  │                      │  │
  ▼                      │  └─(pass)──► [approval_gate]
[retrieve]          (block/초과)              │
  │                      │              auto_approved ──► END
  └──────────────► [generate]          owner_approved/revised
                                              │
                                         [writeback] ──► END
                                    held ──► END
```

- `fast_thanks` 경로: `interpret` · `retrieve` 생략, `answer_tone=thanks` 기본값
- `sensitive` 경로: `critic` 최소 2회 통과 후 `approval_gate` 진입
- `fallback` → `approval_gate(pending)` → 사람 검토 강제

---

## 핵심 상수

| 상수 | 권장값 | 역할 |
|------|--------|------|
| `MAX_CRITIC_LOOPS` | 2 | critic→revise 루프 상한 (sensitive는 최소 2회 강제) |
| `MAX_GEN_RETRIES` | 1 | 답변 생성 자체 실패 재시도 상한 |
| `MAX_SCHEMA_RETRIES` | 1 | pydantic 검증 실패 후 교정형 재요청 상한 |
| `RAG_DISTANCE_THRESHOLD` | 0.4 | ChromaDB 거리 임계값 (초과 시 제외) |

---

## 참고 자료

| 자료 | 관련 설계 결정 |
|------|----------------|
| Anthropic, *Building Effective Agents* (2024) | workflow vs agent 구분, routing 패턴, evaluator-optimizer |
| Madaan et al., *Self-Refine* (2023) | Self-Critic 체크리스트 루프 |
| Shinn et al., *Reflexion* (2023) | 언어 피드백 기반 self-correction |
| Yao et al., *ReAct* (2022) | thought→tool 호출 반복, lookup_store_policy |
| Park et al., *Generative Agents* (2023) | write-back memory, 경험 축적 RAG |
| LangGraph Docs (LangChain) | StateGraph, conditional_edge, human-in-the-loop |
