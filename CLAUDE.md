# Enterprise RAG Agent Platform

## 프로젝트 개요

FastAPI + Milvus + vLLM + LangGraph 기반 엔터프라이즈 RAG 에이전트 플랫폼.
기업 문서 인제스트, RAG 검색, AI 에이전트 워크플로우를 제공하는 백엔드 시스템.

## 기술 스택

- **Language**: Python 3.12
- **Framework**: FastAPI + Uvicorn (ASGI)
- **ORM**: SQLAlchemy 2.x (AsyncSession)
- **Vector DB**: Milvus (PyMilvus)
- **Database**: PostgreSQL (asyncpg)
- **Cache**: Redis (redis-py async)
- **Task Queue**: Celery + Redis broker
- **LLM**: vLLM, Ollama, OpenAI API
- **Agent**: LangGraph
- **Embedding**: BGE-M3 (local), OpenAI text-embedding-3-small
- **Config**: pydantic-settings
- **Logging**: structlog
- **Infra**: Docker Compose, Nginx, Prometheus, Grafana
- **Package Manager**: uv

## 프로젝트 구조

```
src/
├── main.py          # FastAPI 앱 진입점 (lifespan)
├── config.py        # pydantic-settings 기반 설정
├── api/             # API 레이어 (endpoints, schemas, middleware)
├── rag/             # RAG 파이프라인 (extractors, chunkers, embeddings, vectorstore, retriever)
├── agent/           # LangGraph 에이전트 (graph, state, nodes, tools, memory)
├── llm/             # LLM 클라이언트 (router, streaming, cache, circuit_breaker)
├── db/              # SQLAlchemy 모델 + 리포지토리
├── core/            # 공통 유틸 (exceptions, logging, rate_limiter, circuit_breaker)
└── workers/         # Celery 비동기 태스크
```

## 개발 컨벤션

### 코드 스타일
- Python 3.12 문법 사용 (type hints, `list[str]` not `List[str]`)
- async/await 기반 비동기 코드 우선
- 리포지토리 패턴으로 DB 접근 추상화
- 인터페이스(Base 클래스)로 전략 패턴 적용 (extractor, chunker, embedder, llm_client)

### 커밋 메시지
- 영어로 작성
- 첫 줄은 간결한 요약 (imperative mood)

### 브랜치 전략
- `main` 브랜치에서 직접 작업

## 면접 대비 문서화 규칙

각 모듈/기능 구현 시 `docs/` 디렉토리에 기술 문서를 함께 작성한다.
이 문서는 면접에서 "왜 이렇게 구현했는가"에 답할 수 있는 수준이어야 한다.

### 문서 구조

```
docs/
├── architecture.md              # 전체 아키텍처
├── ready/                       # 기술 스택 핵심 개념 레퍼런스 (면접 대비)
│   ├── fastapi.md               # ASGI, Lifespan, DI, SSE, Middleware
│   ├── postgresql.md            # MVCC, VACUUM, 인덱스, Connection Pooling
│   ├── milvus.md                # 벡터 인덱스(HNSW/IVF), Hybrid Search, RRF
│   ├── redis.md                 # 자료구조, Persistence, Eviction, Pub/Sub
│   ├── sqlalchemy.md            # AsyncSession, Unit of Work, Lazy Loading
│   ├── langgraph.md             # State, Node, Edge, Tool Calling, Checkpoint
│   ├── llm-serving.md           # vLLM(PagedAttention), Ollama, 모델 라우팅, 서킷 브레이커
│   ├── rag-fundamentals.md      # 임베딩, 청킹, Re-ranking, 평가 지표
│   ├── celery.md                # 태스크 큐, Worker Pool, 체이닝, 재시도
│   ├── docker.md                # 레이어 캐싱, Compose, Volume, Override
│   ├── monitoring.md            # Prometheus 메트릭 타입, Grafana, RED 메서드
│   ├── nginx.md                 # 리버스 프록시, 로드 밸런싱, SSE 프록시
│   └── python-async.md          # asyncio, GIL, gather, Semaphore, ABC/Protocol
└── decisions/                   # ADR (Architecture Decision Records)
    ├── 001-why-milvus-over-pgvector.md
    ├── 002-chunking-strategy.md
    └── ...
```

### ADR 작성 형식

```markdown
# ADR-NNN: {제목}

## 상태
채택 / 검토 중 / 대체됨

## 맥락
어떤 문제를 해결해야 했는가?

## 선택지
- A) {옵션A} — 장점 / 단점
- B) {옵션B} — 장점 / 단점

## 결정
무엇을 선택했는가?

## 근거
왜 이 선택을 했는가? (트레이드오프, 제약조건, 벤치마크 등)

## 결과
이 결정으로 인해 달라지는 것은?
```

### 문서 작성 타이밍
- 기술적 선택이 발생할 때마다 ADR 작성
- 모듈 구현 완료 시 해당 모듈의 설계 의도 문서화
- "왜?"에 대한 답이 코드만으로 명확하지 않은 경우 반드시 문서화

## 실행 방법

```bash
# 개발 서버
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Docker Compose
docker compose up -d

# 테스트
uv run pytest
```
