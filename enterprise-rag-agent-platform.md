# Enterprise RAG Agent Platform

> FastAPI + Milvus + vLLM + LangGraph 기반 엔터프라이즈 RAG 에이전트 플랫폼

---

## 프로젝트 개요

기업 문서를 인제스트하고, RAG 기반 검색 + AI 에이전트 워크플로우를 통해
사용자 질문에 답변하는 **엔터프라이즈 AI 플랫폼 백엔드**.

프로덕션 수준의 RAG 파이프라인, 멀티스텝 에이전트 워크플로우, LLM 서빙 인프라를
직접 설계하고 구현하여 엔터프라이즈 AI 시스템의 전체 아키텍처를 경험하는 것을 목표로 함.

### 모듈 구성

| 핵심 영역 | 프로젝트 대응 모듈 |
|---|---|
| LLM 추론 엔진 연동 고성능 API 서버 | `api/` + `llm/` (vLLM/Ollama 연동, 스트리밍, 모델 라우팅) |
| RAG 시스템 고도화 (Chunking + 벡터 DB) | `rag/` (문서 인제스트 파이프라인 + Milvus) |
| AI 에이전트 멀티스텝 워크플로우 | `agent/` (LangGraph 기반 Tool Calling 에이전트) |
| LLMOps 인프라 최적화 | `infra/` (Docker Compose, GPU 모니터링, 오토스케일링 설정) |

---

## 디렉토리 구조

```
enterprise-rag-agent-platform/
│
├── README.md
├── docker-compose.yml          # 전체 서비스 오케스트레이션
├── docker-compose.gpu.yml      # GPU 서빙용 오버라이드
├── .env.example
├── pyproject.toml               # uv 기반 패키지 관리
│
├── docs/                        # 아키텍처 문서 & 의사결정 로그
│   ├── architecture.md          # 전체 아키텍처 다이어그램
│   ├── decisions/               # ADR (Architecture Decision Records)
│   │   ├── 001-why-milvus-over-pgvector.md
│   │   ├── 002-chunking-strategy.md
│   │   ├── 003-model-routing-logic.md
│   │   └── 004-agent-state-machine-design.md
│   └── api-spec.md              # API 명세
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 앱 진입점
│   ├── config.py                # 설정 관리 (pydantic-settings)
│   │
│   ├── api/                     # ⭐ [JD: 고성능 API 서버]
│   │   ├── __init__.py
│   │   ├── router.py            # 라우터 통합
│   │   ├── endpoints/
│   │   │   ├── chat.py          # POST /chat (스트리밍 응답)
│   │   │   ├── documents.py     # 문서 CRUD + 인제스트 트리거
│   │   │   ├── collections.py   # Milvus 컬렉션 관리
│   │   │   ├── agents.py        # 에이전트 실행 엔드포인트
│   │   │   └── health.py        # 헬스체크 + 메트릭
│   │   ├── dependencies.py      # FastAPI DI (DB 세션, Milvus 클라이언트 등)
│   │   ├── middleware.py        # 요청 로깅, Rate Limiting, CORS
│   │   └── schemas/             # Pydantic 요청/응답 모델
│   │       ├── chat.py
│   │       ├── document.py
│   │       └── agent.py
│   │
│   ├── rag/                     # ⭐ [JD: RAG 시스템 고도화]
│   │   ├── __init__.py
│   │   ├── pipeline.py          # 인제스트 오케스트레이터
│   │   │
│   │   ├── extractors/          # 문서 텍스트 추출
│   │   │   ├── base.py          # BaseExtractor 인터페이스
│   │   │   ├── pdf.py           # PDF 텍스트 추출 (pypdf + OCR fallback)
│   │   │   ├── docx.py          # DOCX 추출
│   │   │   ├── pptx.py          # PPTX 추출 (텍스트 + Vision 하이브리드)
│   │   │   └── web.py           # 웹페이지 크롤링 추출
│   │   │
│   │   ├── chunkers/            # 청킹 전략
│   │   │   ├── base.py          # BaseChunker 인터페이스
│   │   │   ├── semantic.py      # 시맨틱 청킹 (헤더/문단 기반)
│   │   │   ├── recursive.py     # RecursiveCharacterTextSplitter 스타일
│   │   │   └── parent_child.py  # Parent-Child 청킹 (검색=child, 컨텍스트=parent)
│   │   │
│   │   ├── embeddings/          # 임베딩 생성
│   │   │   ├── base.py          # BaseEmbedder 인터페이스
│   │   │   ├── openai.py        # OpenAI text-embedding-3-small
│   │   │   └── local.py         # Sentence Transformers / Ollama 임베딩
│   │   │
│   │   ├── vectorstore/         # 벡터 저장소 (Milvus)
│   │   │   ├── milvus_client.py # PyMilvus 래퍼 (연결, 컬렉션 관리)
│   │   │   ├── schema.py        # 컬렉션 스키마 정의 (인덱스 설정 포함)
│   │   │   ├── indexing.py      # HNSW / IVF_FLAT 인덱스 관리
│   │   │   └── search.py        # 벡터 검색 + Hybrid Search (dense + sparse)
│   │   │
│   │   └── retriever.py         # 검색 → Re-ranking → Context 구성
│   │
│   ├── agent/                   # ⭐ [JD: AI 에이전트 워크플로우]
│   │   ├── __init__.py
│   │   ├── graph.py             # LangGraph 상태 머신 정의 (핵심!)
│   │   ├── state.py             # AgentState 정의 (대화 히스토리, 중간 결과 등)
│   │   ├── nodes/               # 그래프 노드 (각 스텝)
│   │   │   ├── query_analyzer.py    # 질문 분석 → 의도 분류
│   │   │   ├── router.py            # 의도에 따른 도구/경로 선택
│   │   │   ├── rag_search.py        # RAG 벡터 검색 수행
│   │   │   ├── web_search.py        # 외부 웹 검색 (Tavily 등)
│   │   │   ├── calculator.py        # 계산/데이터 처리 도구
│   │   │   ├── sql_executor.py      # SQL 쿼리 실행 도구
│   │   │   ├── answer_generator.py  # 최종 답변 생성 (LLM 호출)
│   │   │   └── guardrails.py        # 안전 장치 (최대 스텝, 무한루프 방지)
│   │   │
│   │   ├── tools/               # Tool Calling 인터페이스
│   │   │   ├── registry.py      # 도구 등록 + JSON Schema 생성
│   │   │   ├── base.py          # BaseTool 인터페이스
│   │   │   └── definitions.py   # 각 도구의 Function Calling 스펙 정의
│   │   │
│   │   └── memory.py            # 대화 히스토리 관리 (short-term + long-term)
│   │
│   ├── llm/                     # ⭐ [JD: LLM 추론 엔진 연동]
│   │   ├── __init__.py
│   │   ├── base.py              # BaseLLMClient 인터페이스
│   │   ├── openai_client.py     # OpenAI API 클라이언트
│   │   ├── vllm_client.py       # vLLM 로컬 서빙 클라이언트
│   │   ├── ollama_client.py     # Ollama 클라이언트
│   │   ├── router.py            # ⭐ 태스크별 모델 라우팅 로직
│   │   ├── streaming.py         # SSE 스트리밍 응답 처리
│   │   └── cache.py             # Redis 기반 시맨틱 캐싱
│   │
│   ├── db/                      # 데이터베이스 (메타데이터 관리)
│   │   ├── __init__.py
│   │   ├── session.py           # SQLAlchemy Async 세션 관리
│   │   ├── models/              # ORM 모델
│   │   │   ├── document.py      # 문서 메타데이터
│   │   │   ├── collection.py    # 컬렉션 정보
│   │   │   ├── chat_history.py  # 대화 이력
│   │   │   └── agent_log.py     # 에이전트 실행 로그
│   │   └── repositories/        # 리포지토리 패턴
│   │       ├── document_repo.py
│   │       └── chat_repo.py
│   │
│   ├── core/                    # 공통 유틸리티
│   │   ├── __init__.py
│   │   ├── exceptions.py        # 커스텀 예외
│   │   ├── logging.py           # 구조화 로깅 (structlog)
│   │   ├── rate_limiter.py      # Token Bucket Rate Limiter
│   │   └── circuit_breaker.py   # 서킷 브레이커 패턴
│   │
│   └── workers/                 # 비동기 작업
│       ├── __init__.py
│       ├── celery_app.py        # Celery 설정
│       └── tasks/
│           ├── ingest.py        # 문서 인제스트 백그라운드 태스크
│           └── embed.py         # 임베딩 생성 태스크
│
├── tests/
│   ├── conftest.py
│   ├── test_rag/
│   │   ├── test_chunkers.py
│   │   ├── test_milvus_search.py
│   │   └── test_retriever.py
│   ├── test_agent/
│   │   ├── test_graph.py
│   │   └── test_tool_calling.py
│   └── test_api/
│       ├── test_chat.py
│       └── test_documents.py
│
└── infra/                       # ⭐ [JD: LLMOps 인프라]
    ├── milvus/
    │   └── milvus.yaml          # Milvus standalone 설정
    ├── prometheus/
    │   └── prometheus.yml       # 메트릭 수집 설정
    ├── grafana/
    │   └── dashboards/
    │       ├── api-metrics.json      # API 응답시간, 처리량
    │       └── gpu-metrics.json      # GPU 사용률 (DCGM)
    └── nginx/
        └── nginx.conf           # 리버스 프록시 + 로드밸런싱
```

---

## 코드 흐름 (Data Flow)

### Flow 1: 문서 인제스트 (RAG 파이프라인)

```
[사용자: PDF 업로드]
      │
      ▼
┌─────────────────────────────────────────┐
│  POST /api/v1/documents/ingest          │
│  (api/endpoints/documents.py)           │
│                                         │
│  1. 파일 수신 + 메타데이터 DB 저장      │
│  2. 상태: pending → processing          │
│  3. Celery 태스크 큐에 인제스트 작업 발행│
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  workers/tasks/ingest.py (Celery Worker)│
│                                         │
│  Step 1: Extract (텍스트 추출)          │
│  ┌─────────────────────────────┐        │
│  │ extractors/pdf.py           │        │
│  │  - pypdf로 텍스트 추출      │        │
│  │  - 텍스트 없으면 OCR 폴백   │        │
│  │  - 이미지 → Vision API 분석 │        │
│  └──────────────┬──────────────┘        │
│                 ▼                        │
│  Step 2: Chunk (청킹)                   │
│  ┌─────────────────────────────┐        │
│  │ chunkers/parent_child.py    │        │
│  │  - Parent: 큰 단위 (512 tok)│        │
│  │  - Child: 작은 단위 (128 tok)│       │
│  │  - overlap: 64 tokens       │        │
│  │  - 메타데이터 보존 (페이지 등)│       │
│  └──────────────┬──────────────┘        │
│                 ▼                        │
│  Step 3: Embed (임베딩)                 │
│  ┌─────────────────────────────┐        │
│  │ embeddings/local.py         │        │
│  │  - Ollama (bge-m3) 1024차원 │        │
│  │  - 배치 단위 처리 (32개씩)  │        │
│  └──────────────┬──────────────┘        │
│                 ▼                        │
│  Step 4: Store (Milvus 적재)            │
│  ┌─────────────────────────────┐        │
│  │ vectorstore/milvus_client.py│        │
│  │  - child 벡터 → 검색용 컬렉션│       │
│  │  - parent 텍스트 → 참조 저장│        │
│  │  - HNSW 인덱스 자동 생성    │        │
│  └─────────────────────────────┘        │
│                                         │
│  5. 상태: processing → completed        │
└─────────────────────────────────────────┘
```

**설계 포인트:**
- Parent-Child 청킹 → 검색 정확도(child) + 충분한 컨텍스트(parent)
- Milvus 선택 → 수십만 건 이상에서 pgvector 대비 분산 처리 + 전용 인덱싱
- HNSW vs IVF_FLAT → HNSW는 메모리 더 쓰지만 검색 빠름, IVF는 메모리 효율적
- 배치 임베딩 → 하나씩 하면 네트워크 오버헤드, 32개 배치가 처리량/메모리 밸런스

---

### Flow 2: 채팅 (RAG 검색 + 답변 생성)

```
[사용자: "Q3 프로젝트 현황 보고서에 대해 알려줘"]
      │
      ▼
┌────────────────────────────────────────────┐
│  POST /api/v1/chat                         │
│  (api/endpoints/chat.py)                   │
│                                            │
│  1. Rate Limiter 체크 (Token Bucket)       │
│  2. 시맨틱 캐시 확인 (Redis)               │
│     - 유사 질문이 있으면 캐시 응답 반환    │
│     - 없으면 다음 단계로                   │
└─────────────────┬──────────────────────────┘
                  │ (캐시 미스)
                  ▼
┌────────────────────────────────────────────┐
│  llm/router.py (모델 라우팅)               │
│                                            │
│  질문 분석 → 복잡도 판단                   │
│  - 단순 사실 질문 → small 모델 (mini/qwen) │
│  - 복잡한 분석/비교 → large 모델 (gpt-4o)  │
│  - 코드 생성 → code 모델                   │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────┐
│  rag/retriever.py (검색)                   │
│                                            │
│  Step 1: Query Embedding 생성              │
│  Step 2: Milvus Hybrid Search              │
│    - Dense: 벡터 유사도 (cosine)           │
│    - Sparse: BM25 키워드 매칭              │
│    - RRF (Reciprocal Rank Fusion) 결합     │
│  Step 3: Re-ranking (Cross-encoder)        │
│    - top-20 → 유사도 재계산 → top-5 선정   │
│  Step 4: Parent 텍스트 복원                │
│    - child로 검색 → parent 텍스트 반환     │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────┐
│  llm/streaming.py (답변 생성)              │
│                                            │
│  System Prompt + Context + Question        │
│  → LLM API 호출 (스트리밍)                 │
│  → SSE (Server-Sent Events)로 클라이언트 전송│
│  → 완료 시 Redis 캐시 저장                 │
│  → chat_history DB 저장                    │
└────────────────────────────────────────────┘
```

**설계 포인트:**
- 시맨틱 캐시 → 동일 질문뿐 아니라 유사 질문도 캐시 히트 (임베딩 유사도 기반)
- SSE 선택 → 단방향 스트리밍에는 WebSocket보다 가벼움, HTTP/2 호환
- Re-ranking → 벡터 검색 top-k가 항상 최적이 아님, Cross-encoder로 정밀 재정렬
- Hybrid Search RRF → Dense가 의미적 유사도, Sparse가 키워드 정확도, RRF로 두 장점 결합

---

### Flow 3: AI 에이전트 (멀티스텝 워크플로우)

```
[사용자: "우리 회사 Q3 매출 데이터를 분석하고 경쟁사 동향과 비교해줘"]
      │
      ▼
┌─────────────────────────────────────────────────┐
│  POST /api/v1/agents/execute                    │
│  (api/endpoints/agents.py)                      │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  agent/graph.py — LangGraph 상태 머신           │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │         AgentState (상태 객체)             │  │
│  │  - messages: List[Message]                │  │
│  │  - current_step: int                      │  │
│  │  - tool_results: Dict                     │  │
│  │  - final_answer: Optional[str]            │  │
│  │  - max_steps: int = 10  (가드레일)        │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  [START]                                        │
│     │                                           │
│     ▼                                           │
│  ┌──────────────────┐                           │
│  │ query_analyzer   │  "질문을 분석합니다"       │
│  │                  │  → 의도: [데이터분석,      │
│  │                  │    경쟁사비교]              │
│  │                  │  → 필요한 도구 판단        │
│  └────────┬─────────┘                           │
│           │                                     │
│           ▼                                     │
│  ┌──────────────────┐                           │
│  │ router           │  의도에 따라 분기          │
│  │ (Conditional     │                           │
│  │  Edge)           │  → "데이터분석" → sql 도구 │
│  └────┬───────┬─────┘  → "경쟁사비교" → 웹검색  │
│       │       │                                 │
│       ▼       ▼                                 │
│  ┌────────┐ ┌──────────┐                        │
│  │sql_exec│ │web_search│  (병렬 실행 가능)      │
│  │        │ │          │                        │
│  │Q3 매출 │ │경쟁사    │                        │
│  │데이터  │ │최신 뉴스 │                        │
│  │조회    │ │검색      │                        │
│  └───┬────┘ └────┬─────┘                        │
│      │           │                              │
│      ▼           ▼                              │
│  ┌──────────────────┐                           │
│  │ answer_generator │  도구 결과 종합            │
│  │                  │  → LLM이 비교 분석 수행    │
│  │                  │  → 구조화된 답변 생성      │
│  └────────┬─────────┘                           │
│           │                                     │
│           ▼                                     │
│  ┌──────────────────┐                           │
│  │ guardrails       │  품질 체크                 │
│  │                  │  → 답변이 충분한가?        │
│  │                  │  → 부족하면 → router로 복귀│
│  │                  │  → 충분하면 → END          │
│  └────────┬─────────┘                           │
│           │                                     │
│           ▼                                     │
│        [END] → 최종 답변 반환                   │
│                                                 │
│  ※ 실행 로그: agent_log 테이블에 기록           │
│    (어떤 도구를, 왜, 어떤 결과로 호출했는지)    │
└─────────────────────────────────────────────────┘
```

**설계 포인트:**
- LangGraph 선택 → 상태 머신 기반이라 복잡한 분기/루프 표현 가능, LangChain 단선형 체인의 한계 극복
- Tool Calling 구현 → JSON Schema로 도구 정의 → LLM이 호출할 도구 선택 → 실행 → 결과를 다시 LLM에 전달
- 무한루프 방지 → max_steps 제한 + 동일 도구 반복 호출 감지 + 비용 리밋
- MCP 연동 → 외부 시스템(DB, API)을 표준 프로토콜로 연결, 도구 확장성 확보

---

### Flow 4: LLM 모델 라우팅 (비용 최적화)

```
[들어온 요청]
      │
      ▼
┌─────────────────────────────────────────┐
│  llm/router.py                          │
│                                         │
│  1. 질문 복잡도 분류 (규칙 기반 + LLM)  │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ 규칙 기반 Fast Path:            │    │
│  │  - 토큰 수 < 50 → simple       │    │
│  │  - "비교", "분석" 포함 → complex│    │
│  │  - 코드 블록 포함 → code        │    │
│  │  - 판단 불가 → LLM classifier   │    │
│  └─────────────┬───────────────────┘    │
│                │                        │
│                ▼                        │
│  2. 복잡도별 모델 매핑                  │
│                                         │
│  ┌────────────┬─────────────────────┐   │
│  │ simple     │ qwen3-8b (Ollama)   │   │
│  │            │ or gpt-4o-mini      │   │
│  ├────────────┼─────────────────────┤   │
│  │ complex    │ gpt-4o              │   │
│  │            │ or exaone (로컬)    │   │
│  ├────────────┼─────────────────────┤   │
│  │ code       │ codestral (Ollama)  │   │
│  ├────────────┼─────────────────────┤   │
│  │ embedding  │ bge-m3 (로컬)       │   │
│  └────────────┴─────────────────────┘   │
│                                         │
│  3. Circuit Breaker 체크                │
│     - 해당 모델 서버 장애 시 fallback    │
│     - vLLM 다운 → Ollama fallback       │
│     - Ollama도 다운 → OpenAI API        │
│                                         │
│  4. 요청 실행 + 메트릭 기록             │
│     - 응답 시간, 토큰 수, 비용 추정     │
└─────────────────────────────────────────┘
```

**설계 포인트:**
- 규칙 기반 + LLM 하이브리드 → 간단한 건 규칙으로 빠르게, 애매한 건 mini 모델로 분류 (비용 효율)
- 서킷 브레이커 → 장애 서버에 계속 요청하지 않고, 일정 실패율 이상이면 차단 후 fallback
- vLLM vs Ollama → vLLM은 프로덕션급 처리량(continuous batching), Ollama는 개발/소규모 서빙

---

## 핵심 파일별 코드 스케치

### 1. `src/main.py` — 앱 진입점

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.api.router import api_router
from src.config import settings
from src.db.session import engine
from src.rag.vectorstore.milvus_client import MilvusManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 리소스 초기화
    await MilvusManager.connect()
    # DB 테이블 생성 (개발용)
    yield
    # Shutdown: 리소스 정리
    await MilvusManager.disconnect()
    await engine.dispose()

app = FastAPI(title="Enterprise RAG Agent Platform", lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")
```

### 2. `src/agent/graph.py` — 에이전트 상태 머신

```python
from langgraph.graph import StateGraph, END
from src.agent.state import AgentState
from src.agent.nodes import (
    query_analyzer, router_node,
    rag_search, web_search, sql_executor,
    answer_generator, guardrails
)

def build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node("analyze", query_analyzer)
    graph.add_node("rag_search", rag_search)
    graph.add_node("web_search", web_search)
    graph.add_node("sql_execute", sql_executor)
    graph.add_node("generate", answer_generator)
    graph.add_node("guardrails", guardrails)

    # 엣지 연결
    graph.set_entry_point("analyze")
    graph.add_conditional_edges(
        "analyze",
        router_node,  # 조건 함수: 의도에 따라 다음 노드 결정
        {
            "rag": "rag_search",
            "web": "web_search",
            "sql": "sql_execute",
            "direct": "generate",  # 도구 없이 바로 답변
        }
    )

    # 도구 → 답변 생성
    graph.add_edge("rag_search", "generate")
    graph.add_edge("web_search", "generate")
    graph.add_edge("sql_execute", "generate")

    # 답변 → 가드레일 → 종료 or 재시도
    graph.add_edge("generate", "guardrails")
    graph.add_conditional_edges(
        "guardrails",
        lambda state: "end" if state["is_sufficient"] else "analyze",
        {"end": END, "analyze": "analyze"}
    )

    return graph.compile()
```

### 3. `src/rag/vectorstore/search.py` — Milvus Hybrid Search

```python
from pymilvus import Collection, AnnSearchRequest, RRFRanker

async def hybrid_search(
    collection: Collection,
    query_dense: list[float],  # 밀집 벡터
    query_text: str,           # BM25용 원문
    top_k: int = 20
) -> list[dict]:
    # Dense Search (벡터 유사도)
    dense_req = AnnSearchRequest(
        data=[query_dense],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"ef": 128}},
        limit=top_k
    )

    # Sparse Search (BM25 키워드)
    sparse_req = AnnSearchRequest(
        data=[compute_sparse_vector(query_text)],
        anns_field="sparse_embedding",
        param={"metric_type": "IP"},
        limit=top_k
    )

    # RRF (Reciprocal Rank Fusion) 결합
    results = collection.hybrid_search(
        reqs=[dense_req, sparse_req],
        ranker=RRFRanker(k=60),  # k=60 is common default
        limit=top_k
    )

    return results
```

### 4. `src/llm/cache.py` — 시맨틱 캐시

```python
import hashlib
import numpy as np
from redis.asyncio import Redis

class SemanticCache:
    def __init__(self, redis: Redis, threshold: float = 0.92):
        self.redis = redis
        self.threshold = threshold

    async def get(self, query_embedding: list[float]) -> str | None:
        """유사 질문의 캐시된 응답 반환"""
        cached_keys = await self.redis.keys("cache:emb:*")

        for key in cached_keys:
            cached_emb = np.frombuffer(await self.redis.get(key))
            similarity = cosine_similarity(query_embedding, cached_emb)

            if similarity >= self.threshold:
                answer_key = key.decode().replace("emb:", "ans:")
                return await self.redis.get(answer_key)

        return None  # 캐시 미스

    async def set(self, query_embedding: list[float], answer: str, ttl: int = 3600):
        """응답 캐시 저장"""
        cache_id = hashlib.md5(str(query_embedding[:8]).encode()).hexdigest()
        await self.redis.set(f"cache:emb:{cache_id}", np.array(query_embedding).tobytes(), ex=ttl)
        await self.redis.set(f"cache:ans:{cache_id}", answer, ex=ttl)
```

---

## docker-compose.yml (전체 인프라)

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    depends_on: [postgres, redis, milvus, ollama]
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/ragplatform
      - REDIS_URL=redis://redis:6379
      - MILVUS_HOST=milvus
      - OLLAMA_BASE_URL=http://ollama:11434

  celery-worker:
    build: .
    command: celery -A src.workers.celery_app worker
    depends_on: [redis, milvus]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: ragplatform
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass

  redis:
    image: redis:7-alpine

  milvus:
    image: milvusdb/milvus:v2.4-latest
    ports: ["19530:19530"]
    volumes:
      - milvus_data:/var/lib/milvus

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama_data:/root/.ollama
    # GPU 사용 시 docker-compose.gpu.yml 오버라이드

  # --- 모니터링 (선택) ---
  prometheus:
    image: prom/prometheus
    volumes:
      - ./infra/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]

volumes:
  milvus_data:
  ollama_data:
```

---

## 구현 순서 (추천 로드맵)

### Phase 1: 기반 구축 (Day 1-2)
- [ ] 프로젝트 초기 세팅 (pyproject.toml, Docker Compose)
- [ ] FastAPI 앱 골격 + 헬스체크 엔드포인트
- [ ] PostgreSQL + SQLAlchemy Async 세션 설정
- [ ] Milvus 연결 + 컬렉션 생성 테스트
- [ ] config.py (pydantic-settings)

### Phase 2: RAG 파이프라인 (Day 3-5)
- [ ] PDF/DOCX Extractor 구현
- [ ] Chunker 구현 (RecursiveCharacter → Parent-Child)
- [ ] Ollama 임베딩 연동 (bge-m3)
- [ ] Milvus 적재 + 벡터 검색 구현
- [ ] Hybrid Search (dense + sparse) 구현
- [ ] Retriever + Re-ranking 구현
- [ ] 인제스트 API 엔드포인트

### Phase 3: LLM 서빙 + 채팅 (Day 6-8)
- [ ] LLM 클라이언트 추상화 (OpenAI / Ollama)
- [ ] 모델 라우팅 로직
- [ ] SSE 스트리밍 응답
- [ ] Chat API 엔드포인트
- [ ] Redis 시맨틱 캐시
- [ ] 서킷 브레이커

### Phase 4: AI 에이전트 (Day 9-12)
- [ ] AgentState 정의
- [ ] LangGraph 상태 머신 구성
- [ ] Tool Calling (Function Calling) 구현
- [ ] 노드 구현: query_analyzer, router, rag_search, web_search
- [ ] answer_generator + guardrails
- [ ] 에이전트 실행 로깅
- [ ] Agent API 엔드포인트

### Phase 5: 인프라 + 마무리 (Day 13-14)
- [ ] Docker Compose 전체 구동 확인
- [ ] Prometheus 메트릭 수집
- [ ] 기본 테스트 코드
- [ ] README + ADR 문서 작성
- [ ] docs/architecture.md 다이어그램

---

## ADR (Architecture Decision Records)

`docs/decisions/` 폴더에 아키텍처 의사결정 기록을 남겨 설계 근거를 문서화.

### 예시: 001-why-milvus-over-pgvector.md

```markdown
# ADR-001: Milvus를 pgvector 대신 선택한 이유

## 상태: 채택

## 맥락
기존 프로젝트에서 pgvector를 사용했으나, 대규모 엔터프라이즈 환경에서
수십만~수백만 건의 벡터를 처리해야 하는 요구사항 발생.

## 결정
Milvus standalone을 벡터 저장소로 채택.

## 이유
1. **인덱스 다양성**: HNSW, IVF_FLAT, IVF_PQ, DiskANN 등 워크로드별 최적 인덱스 선택 가능
2. **Hybrid Search 네이티브 지원**: dense + sparse 벡터 조합 검색을 단일 쿼리로 처리
3. **스케일링**: 분산 배포 시 Query Node / Data Node 분리로 수평 확장
4. **파티셔닝**: Partition Key로 멀티 테넌트 데이터 격리

## 트레이드오프
- pgvector 대비 운영 복잡도 증가 (별도 서비스 관리)
- 소규모 데이터(10만건 이하)에서는 pgvector가 더 간단
- PostgreSQL 조인 쿼리와 분리되므로 메타데이터 조회 시 추가 통신 필요
```
