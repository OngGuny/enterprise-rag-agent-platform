# Celery 핵심 개념

## Celery란?

- Python 분산 태스크 큐. 비동기/백그라운드 작업 처리.
- **구성 요소**:
  - **Client (Producer)**: 태스크를 큐에 발행.
  - **Broker**: 메시지 중간 저장소 (Redis, RabbitMQ).
  - **Worker (Consumer)**: 큐에서 태스크를 가져와 실행.
  - **Result Backend**: 태스크 결과 저장 (Redis, DB).

```
Client → Broker (Redis) → Worker → Result Backend
```

## 기본 사용

```python
# tasks.py
from celery import Celery

app = Celery("tasks", broker="redis://localhost:6379/0")

@app.task
def ingest_document(document_id: int):
    # 무거운 작업: 텍스트 추출, 청킹, 임베딩, 벡터 적재
    ...
```

```python
# 태스크 발행 (비동기, 즉시 반환)
result = ingest_document.delay(document_id=42)

# 결과 확인 (필요 시)
result.status   # PENDING, STARTED, SUCCESS, FAILURE
result.get()    # 결과 반환 (블로킹)
```

## delay vs apply_async

```python
# 간단한 발행
ingest_document.delay(42)

# 옵션 지정
ingest_document.apply_async(
    args=[42],
    countdown=60,           # 60초 후 실행
    expires=3600,           # 1시간 후 만료
    queue="high_priority",  # 특정 큐로 라우팅
    retry=True,
    retry_policy={"max_retries": 3, "interval_start": 10}
)
```

## Worker 실행

```bash
# 기본 실행
celery -A src.workers.celery_app worker --loglevel=info

# 동시성 설정
celery -A src.workers.celery_app worker --concurrency=4 --pool=prefork

# 특정 큐만 처리
celery -A src.workers.celery_app worker -Q ingest,embed
```

### Pool 타입

| Pool | 방식 | 적합한 작업 |
|---|---|---|
| `prefork` (기본) | 멀티 프로세스 | CPU 바운드 (임베딩, 파싱) |
| `gevent` / `eventlet` | 그린 스레드 | I/O 바운드 (API 호출, 네트워크) |
| `solo` | 단일 프로세스 | 디버깅 |

## 태스크 체이닝

```python
from celery import chain, group, chord

# chain: 순차 실행 (이전 결과가 다음 입력)
chain(extract.s(doc_id), chunk.s(), embed.s(), store.s())()

# group: 병렬 실행
group(embed.s(chunk_id) for chunk_id in chunk_ids)()

# chord: 병렬 실�� 후 콜백
chord(
    group(embed.s(chunk_id) for chunk_id in chunk_ids),
    store_all.s()  # 모든 임베딩 완료 후 실행
)()
```

### 이 프로젝트에서의 활용
```
문서 업로드 → chain(extract → chunk → embed → store)
대량 문서 → chord(group(embed per chunk), store_all)
```

## 에러 핸들링 & 재시도

```python
@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # 60초 후 재시도
    autoretry_for=(ConnectionError, TimeoutError),  # 자동 재시도 예외
    retry_backoff=True,      # 지수 백오프 (60, 120, 240초)
    retry_jitter=True,       # 랜덤 지터 추가 (재시도 몰림 방지)
)
def embed_chunks(self, chunk_ids: list[int]):
    try:
        ...
    except RateLimitError as e:
        raise self.retry(exc=e, countdown=120)
```

### Acks Late

```python
@app.task(acks_late=True, reject_on_worker_lost=True)
def important_task():
    ...
```

- 기본: 워커가 태스크를 받으면 즉시 ack → 워커가 죽으면 태스크 소실.
- `acks_late=True`: 태스크 완료 후 ack → 워커가 죽으면 다른 워커가 재처리.
- **멱등성(idempotent)** 보장 필수: 같은 태스크가 두 번 실행될 수 있음.

## 모니터링: Flower

```bash
celery -A src.workers.celery_app flower --port=5555
```

- 웹 UI로 태스크 상태, 워커 상태, 큐 길이 실시간 모니터링.
- 태스크 결과 조회, 워커 종료, 태스크 취소 가능.

## Celery vs 대안

| 도구 | 특징 | 적합한 경우 |
|---|---|---|
| **Celery** | 풍부한 기능, 대규모 검증됨 | 복잡한 워크플로우, 프로덕션 |
| **Dramatiq** | 심플, 안정적 | Celery가 과한 경우 |
| **ARQ** | async 네이티브, Redis 전용 | 소규모 async 앱 |
| **BackgroundTasks** | FastAPI 내장 | 간단한 후처리 |
