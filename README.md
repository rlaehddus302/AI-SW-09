# 리뷰 대응 에이전트

소상공인 음식점 사장님의 리뷰 관리 부담을 줄이기 위한 로컬 데모용 MVP입니다. 리뷰를 주문 유형별로 모아 보고, AI가 긍정/부정/악성 및 위험도를 분류한 뒤 RAG 기반 답변 초안을 생성합니다.

## 범위

- 포함: 가게 등록, 리뷰 대시보드, 리뷰 통계, 배치 분석, 배치 답변 생성, 승인/반려/재생성, WebSocket 진행률
- 제외: 실제 플랫폼 크롤링, 실제 답변 게시, 환불 처리, 로그인/인증, 다중 가게, 배포
- AI 모드: `AI_MODE=auto` 기본값. Upstage API 키가 있으면 실연동, 없으면 deterministic mock으로 동작합니다.

## 로컬 실행

```bash
cp .env.example .env
docker compose up -d mysql
# 또는 Docker Compose 플러그인이 없는 환경:
docker-compose up -d mysql
```

백엔드와 프론트엔드는 각각 하위 디렉터리에서 의존성을 설치한 뒤 실행합니다.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

기본 접속 주소는 `http://localhost:5173`입니다.

## 검증

```bash
PYTHONPATH=backend python -m pytest backend/tests tests -q
cd frontend
npm run lint
npm test
npm run build
npm run test:e2e
```

Docker Desktop 또는 Docker daemon이 실행 중이어야 MySQL 컨테이너 기반 데모를 확인할 수 있습니다. API 키가 없으면 `.env`의 `AI_MODE=auto` 설정으로 mock AI가 사용됩니다.

## Gitflow

- `main`: 안정 브랜치
- `develop`: 통합 개발 브랜치
- `feature/*`: 기능 단위 작업 브랜치

각 기능은 테스트 통과 후 `develop`에 통합합니다.
