# 08. 인프라: Docker Compose, 모니터링, 테스트

## 목표

전체 서비스를 Docker Compose로 오케스트레이션하고, Prometheus + Grafana로 모니터링을 구성하며, Nginx 리버스 프록시와 테스트 전략을 수립한다.

---

## 8.1 Docker Compose 구성

### 서비스 목록

| 서비스 | 이미지 | 용도 | 포트 |
|--------|--------|------|------|
| api | 커스텀 빌드 | FastAPI 앱 | 8000 |
| celery-worker | 커스텀 빌드 | 인제스트/임베딩 처리 | - |
| postgres | postgres:16 | 메타데이터 DB | 5432 |
| redis | redis:7-alpine | 캐시/큐/세션 | 6379 |
| milvus | milvusdb/milvus:v2.4 | 벡터 DB | 19530 |
| ollama | ollama/ollama | 로컬 LLM + 임베딩 | 11434 |
| nginx | nginx:alpine | 리버스 프록시 | 80, 443 |
| prometheus | prom/prometheus | 메트릭 수집 | 9090 |
| grafana | grafana/grafana | 대시보드 | 3000 |

### Dockerfile (멀티 스테이지 빌드)

```dockerfile
# Stage 1: 빌드
FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN pip install uv && \
    uv sync --frozen --no-dev

# Stage 2: 런타임
FROM python:3.12-slim AS runtime

WORKDIR /app

# 시스템 의존성 (OCR용 tesseract 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### docker-compose.yml 핵심 설정

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      milvus:
        condition: service_started
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/ragplatform
      - REDIS_URL=redis://redis:6379/0
      - MILVUS_HOST=milvus
      - OLLAMA_BASE_URL=http://ollama:11434
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  celery-worker:
    build: .
    command: celery -A src.workers.celery_app worker --loglevel=info --concurrency=2
    depends_on: [redis, milvus, ollama]
    environment: # api와 동일한 환경변수

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ragplatform
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d ragplatform"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  milvus:
    image: milvusdb/milvus:v2.4-latest
    command: ["milvus", "run", "standalone"]
    ports: ["19530:19530"]
    volumes:
      - milvus_data:/var/lib/milvus
    environment:
      ETCD_USE_EMBED: "true"
      COMMON_STORAGETYPE: local

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama_data:/root/.ollama
    # GPU용: docker-compose.gpu.yml에서 deploy.resources.reservations 오버라이드

volumes:
  postgres_data:
  redis_data:
  milvus_data:
  ollama_data:
```

### docker-compose.gpu.yml (GPU 오버라이드)

```yaml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

### 프로덕션 포인트

- `depends_on` + `healthcheck`로 서비스 기동 순서 보장
- 멀티 스테이지 빌드로 이미지 크기 최소화 (빌드 도구 제외)
- `uvicorn --workers 4`: 멀티프로세스로 CPU 코어 활용
- Redis `maxmemory-policy allkeys-lru`: 메모리 초과 시 가장 오래된 키 삭제
- 볼륨으로 데이터 영속성 보장

---

## 8.2 Nginx 리버스 프록시 (infra/nginx/nginx.conf)

```nginx
upstream api_backend {
    server api:8000;
    # 스케일 아웃 시 서버 추가
}

server {
    listen 80;
    server_name localhost;

    # 일반 API
    location /api/ {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;

        # 타임아웃
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
    }

    # SSE 스트리밍 (채팅, 에이전트)
    location ~ ^/api/v1/(chat|agents) {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_http_version 1.1;

        # SSE 필수 설정
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;

        # SSE는 긴 타임아웃 필요
        proxy_read_timeout 300s;
    }

    # 정적 파일 (API 문서 등)
    location /docs {
        proxy_pass http://api_backend;
    }

    # Prometheus 메트릭 (내부망에서만)
    location /metrics {
        proxy_pass http://api_backend;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        deny all;
    }
}
```

---

## 8.3 Prometheus 모니터링 (infra/prometheus/)

### prometheus.yml

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "fastapi"
    static_configs:
      - targets: ["api:8000"]
    metrics_path: /metrics

  - job_name: "redis"
    static_configs:
      - targets: ["redis-exporter:9121"]

  - job_name: "postgres"
    static_configs:
      - targets: ["postgres-exporter:9187"]
```

### 핵심 Grafana 대시보드

**API 메트릭 (RED Method):**
- Rate: 초당 요청 수 by endpoint
- Errors: 에러율 (4xx, 5xx) by endpoint
- Duration: P50, P95, P99 응답 시간 by endpoint

**RAG 메트릭:**
- 검색 지연 시간 (Hybrid Search + Re-ranking)
- 캐시 히트율
- 인제스트 처리 시간, 큐 대기 시간

**LLM 메트릭:**
- 모델별 호출 수 + 토큰 사용량
- 서킷 브레이커 상태
- 라우팅 분포 (simple/complex/code 비율)

---

## 8.4 테스트 전략

### 테스트 구조

```
tests/
├── conftest.py              # 공통 fixture (DB, Redis, Milvus mock)
├── unit/
│   ├── test_chunkers.py     # 청킹 로직 단위 테스트
│   ├── test_rate_limiter.py # Token Bucket 알고리즘
│   ├── test_circuit_breaker.py
│   └── test_router.py       # 모델 라우팅 규칙
├── integration/
│   ├── test_rag_pipeline.py # 인제스트 → 검색 통합
│   ├── test_chat_api.py     # Chat API + SSE
│   └── test_agent.py        # 에이전트 실행
└── fixtures/
    ├── sample.pdf
    └── sample.docx
```

### conftest.py 핵심 Fixture

```python
@pytest.fixture
async def db_session():
    """테스트용 DB 세션 (트랜잭션 롤백)."""
    async with async_session_factory() as session:
        async with session.begin():
            yield session
        await session.rollback()

@pytest.fixture
async def api_client(db_session):
    """FastAPI 테스트 클라이언트."""
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()

@pytest.fixture
def mock_llm_client():
    """LLM 클라이언트 Mock."""
    client = AsyncMock(spec=BaseLLMClient)
    client.generate.return_value = LLMResponse(
        content="Test response",
        model="test-model",
        usage=TokenUsage(10, 20, 30),
        latency_ms=100,
        finish_reason="stop",
    )
    return client
```

### 테스트 예시

```python
# test_chunkers.py
class TestParentChildChunker:
    def test_creates_child_chunks_within_parent(self):
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=30)
        doc = ExtractedDocument(text="A" * 200, metadata={})
        chunks = chunker.chunk(doc)

        assert all(chunk.parent_id is not None for chunk in chunks)
        assert all(len(chunk.text) <= 30 * 5 for chunk in chunks)  # 토큰 → 글자 비율

    def test_parent_text_preserved_in_metadata(self):
        ...

# test_chat_api.py
async def test_chat_returns_sse_stream(api_client, mock_llm_client):
    response = await api_client.post(
        "/api/v1/chat",
        json={"query": "테스트 질문", "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
```

---

## 체크리스트

- [ ] Dockerfile (멀티 스테이지)
- [ ] docker-compose.yml (전체 서비스)
- [ ] docker-compose.gpu.yml (GPU 오버라이드)
- [ ] .env.example (환경변수 템플릿)
- [ ] infra/nginx/nginx.conf (SSE 프록시 포함)
- [ ] infra/prometheus/prometheus.yml
- [ ] infra/grafana/dashboards/ (JSON 대시보드)
- [ ] tests/conftest.py (fixture 구성)
- [ ] tests/unit/ (핵심 로직 단위 테스트)
- [ ] tests/integration/ (API + 파이프라인 통합 테스트)
- [ ] Makefile 또는 scripts/ (빌드/테스트/실행 편의 스크립트)
