# Tests

## 통합테스트 — Phase 1

`tests/integration/` 의 테스트들은 Postgres / Redis / Milvus 가 localhost 에서 떠 있다고 가정한다(ADR-001 / ADR-003 의 운영 모델과 동일).

### 사전 준비

```bash
# 1) 의존 인프라 기동
docker compose up -d postgres redis milvus

# 2) 컨테이너가 ready 가 될 때까지 대기 (10~30초)
docker compose ps
```

### 실행

```bash
# 전체 테스트
uv run pytest

# 통합테스트만
uv run pytest -m integration

# 통합테스트 제외
uv run pytest -m "not integration"

# 한 파일만
uv run pytest tests/integration/test_health.py -v
```

### 환경 격리

`tests/conftest.py` 가 `os.environ` 을 직접 덮어쓴다.

| 변수 | 테스트 값 | 이유 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/ragplatform` | docker-compose 의 호스트 포트 |
| `REDIS_URL` | `redis://localhost:6379/15` | DB 인덱스 15 — 캐시(0) / Celery(1, 2) 와 분리 |
| `MILVUS_URI` | `http://localhost:19530` | docker-compose 의 호스트 포트 |
| `MILVUS_DEFAULT_COLLECTION` | `test_documents` | 운영 컬렉션과 충돌 방지 |
| `LOG_LEVEL` | `WARNING` | 테스트 로그 노이즈 감소 |

`get_settings()` 는 `lru_cache` 로 캐시되므로, 환경 주입은 반드시 `src.*` import **이전** 에 일어나야 한다 — `conftest.py` 의 모듈 최상단에서 처리한다.

### 픽스처 카탈로그

| 픽스처 | 스코프 | 무엇을 주는가 |
|---|---|---|
| `app_with_lifespan` | function | FastAPI 앱 + lifespan 으로 부팅됨 (Redis/Milvus connect) |
| `client` | function | `httpx.AsyncClient(ASGITransport)` — `app_with_lifespan` 위에서 실행 |
| `db_session` | function | `async_session_factory()` 로 만든 `AsyncSession`, 종료 시 rollback |

함수 스코프를 쓰는 이유는 각 테스트마다 매니저 connect/disconnect 를 한 번씩 더 거치게 만들어, lifespan 의 idempotency / 누수 회귀를 자연스럽게 잡기 위함이다.

### 실패 트러블슈팅

- **`Connection refused` (Postgres / Redis / Milvus)**: docker compose 가 떠 있는지 확인. `docker compose ps` 로 health 확인.
- **`Milvus not connected` RuntimeError**: 부팅 직후 Milvus 가 ready 가 되기 전에 테스트가 시작됐을 가능성. 30초 대기 후 재시도.
- **포트 충돌**: 호스트의 5432/6379/19530 이 다른 프로세스에 점유되어 있을 수 있다. `docker compose down` 후 다른 Postgres/Redis 인스턴스 종료.
