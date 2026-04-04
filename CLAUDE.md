# Enterprise RAG Agent Platform

## 프로젝트 개요

FastAPI + Milvus + vLLM + LangGraph 기반 엔터프라이즈 RAG 에이전트 플랫폼.
기업 문서 인제스트, RAG 검색, AI 에이전트 워크플로우를 제공하는 백엔드 시스템.

## 기술 스택

- **Language**: Python 3.13
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
- Python 3.13 문법 사용 (type hints, `list[str]` not `List[str]`)
- async/await 기반 비동기 코드 우선
- 리포지토리 패턴으로 DB 접근 추상화
- 인터페이스(Base 클래스)로 전략 패턴 적용 (extractor, chunker, embedder, llm_client)
- 코드 내 불필요한 주석 지양. 코드 자체가 의도를 드러내도록 작성
- 설계 의도, 기술 채택 근거는 `docs/decisions/` ADR로 문서화

### 커밋 메시지
- 영어로 작성
- 첫 줄은 간결한 요약 (imperative mood)

### 브랜치 전략
- `main` 브랜치에서 직접 작업

## 설계 문서화 규칙

각 모듈/기능 구현 시 `docs/` 디렉토리에 기술 문서를 함께 작성한다.

### 문서 구조

```
docs/
├── architecture.md              # 전체 아키텍처
├── ready/                       # 기술 스택 핵심 개념 레퍼런스
│   ├── fastapi.md
│   ├── postgresql.md
│   ├── milvus.md
│   ├── redis.md
│   ├── sqlalchemy.md
│   ├── langgraph.md
│   ├── llm-serving.md
│   ├── rag-fundamentals.md
│   ├── celery.md
│   ├── docker.md
│   ├── monitoring.md
│   ├── nginx.md
│   └── python-async.md
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
- 코드만으로 설계 의도가 명확하지 않은 경우 반드시 문서화

## 실행 방법

```bash
# 개발 서버
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Docker Compose
docker compose up -d

# 테스트
uv run pytest
```
