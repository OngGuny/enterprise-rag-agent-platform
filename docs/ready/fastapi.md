# FastAPI 핵심 개념

## ASGI vs WSGI

- **WSGI** (Web Server Gateway Interface): 동기 처리. 요청 하나당 스레드 하나. Flask, Django.
- **ASGI** (Asynchronous Server Gateway Interface): 비동기 처리. 이벤트 루프 기반. FastAPI, Starlette.
- ASGI는 WebSocket, HTTP/2, SSE 같은 long-lived connection을 네이티브로 지원.
- WSGI에서 동시 1000 요청을 처리하려면 스레드 1000개가 필요하지만, ASGI는 단일 이벤트 루프에서 처리 가능.

## ASGI/WSGI 서버 비교

### Uvicorn

- Python ASGI 서버 구현체. 단일 프로세스, 단일 이벤트 루프.
- **uvloop**: libuv(Node.js의 이벤트 루프) 기반 Python 이벤트 루프. 순수 asyncio 대비 2~4배 빠름.
- **httptools**: Node.js의 HTTP 파서를 Python 바인딩. 표준 라이브러리 대비 파싱 속도 향상.

```bash
# 개발
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 프로덕션 (단일 프로세스)
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

- `--reload`: 코드 변경 감지 → 자동 재시작. **개발 전용** (watchfiles 의존).
- `--workers`: Uvicorn 자체 멀티 프로세스 모드 (0.18+). Gunicorn 없이도 멀티 워커 가능.

#### Uvicorn의 한계
- 프로세스 매니저 기능이 기본적: 워커 죽으면 재시작은 하지만, graceful shutdown/reload이 Gunicorn보다 덜 정교.
- 프로덕션에서 더 안정적인 프로세스 관리가 필요하면 Gunicorn과 조합.

### Gunicorn

- Python **WSGI** 서버. 원래 동기 전용이지만, 워커 클래스를 교체하면 ASGI도 처리 가능.
- **Pre-fork 모델**: 마스터 프로세스가 워커 프로세스를 fork하여 관리.

```bash
gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

#### Gunicorn이 하는 일 (프로세스 매니저 역할)
1. **워커 생성/관리**: 지정된 수의 워커 프로세스를 fork.
2. **워커 모니터링**: 워커가 죽으면 자동 재생성.
3. **Graceful reload**: `kill -HUP <pid>` → 새 워커 생성 후 구 워커를 순차 종료. 다운타임 없음.
4. **Graceful shutdown**: `kill -TERM <pid>` → 처리 중인 요청 완료 후 종료.
5. **타임아웃 관리**: `--timeout 30` → 30초 내 응답 없는 워커 강제 종료 (hang 방지).

#### 워커 수 결정
```
워커 수 = CPU 코어 수 * 2 + 1  (Gunicorn 공식 권장)
```
- I/O 바운드 작업이 많으면 코어 수 * 2~4.
- CPU 바운드 작업이 많으면 코어 수 * 1.
- 실제로는 부하 테스트로 최적값을 찾아야 함.

### Gunicorn + Uvicorn Worker 조합

```
                    ┌──────────────────┐
                    │  Gunicorn Master │  (프로세스 매니저)
                    └────────┬─────────┘
                             │ fork
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼───┐ ┌───────▼─────┐ ┌──────▼──────┐
    │ Uvicorn     │ │ Uvicorn     │ │ Uvicorn     │
    │ Worker #1   │ │ Worker #2   │ │ Worker #3   │
    │ (이벤트루프)│ │ (이벤트루프)│ │ (이벤트루프)│
    └─────────────┘ └─────────────┘ └─────────────┘
```

- **Gunicorn**: 프로세스 생성, 모니터링, 시그널 처리, graceful reload.
- **Uvicorn Worker**: 각 프로세스 내에서 ASGI 이벤트 루프 실행, 실제 요청 처리.
- **왜 이 조합인가?**: Uvicorn의 빠른 ASGI 처리 + Gunicorn의 안정적인 프로세스 관리.

### Uvicorn 단독 vs Gunicorn + Uvicorn

| 항목 | Uvicorn 단독 (`--workers`) | Gunicorn + Uvicorn Worker |
|---|---|---|
| 프로세스 관리 | 기본적 | 성숙하고 안정적 |
| Graceful reload | 제한적 | `kill -HUP`으로 무중단 재시작 |
| 설정 유연성 | CLI 옵션 | config 파일, 훅 함수 |
| 의존성 | uvicorn만 | gunicorn + uvicorn |
| 적합한 경우 | 컨테이너 환경 (K8s가 관리) | 베어메탈, VM 직접 배포 |

**Docker/K8s 환경에서는**: 컨테이너 오케스트레이터가 프로세스 관리를 하므로 Uvicorn 단독으로 충분.
각 컨테이너에 워커 1개 → 컨테이너 수로 스케일링하는 것이 K8s 방식.

**VM/베어메탈에서는**: Gunicorn + Uvicorn Worker가 더 안정적.

### Hypercorn (참고)

- 또 다른 ASGI 서버. HTTP/3 (QUIC) 지원이 특징.
- Trio (asyncio 대안 비동기 라이브러리) 백엔드 지원.
- Uvicorn 대비 사용자가 적어 생태계/레퍼런스가 부족.

### Daphne (참고)

- Django Channels 팀이 만든 ASGI 서버.
- Django 프로젝트에서 주로 사용. FastAPI에서는 거의 안 씀.

## 프로덕션 배포 구성 예시

### 1. Docker + Uvicorn (K8s 환경)
```dockerfile
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
# 워커 1개 → K8s HPA로 Pod 수 조절
```

### 2. VM + Gunicorn + Uvicorn + systemd
```ini
# /etc/systemd/system/api.service
[Service]
ExecStart=/app/.venv/bin/gunicorn src.main:app \
    -w 4 \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile -
Restart=always
```

### 3. 전체 스택
```
Internet → Nginx (SSL, 정적파일, Rate Limit)
         → Gunicorn (프로세스 관리)
         → Uvicorn Worker (ASGI 처리)
         → FastAPI (라우팅, 비즈니스 로직)
```

## Lifespan (생명주기)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: DB 연결, 캐시 워밍, ML 모델 로드 등
    await db.connect()
    yield
    # shutdown: 리소스 정리, 연결 종료
    await db.disconnect()
```

- FastAPI 0.93+에서 `@app.on_event("startup")` 대신 `lifespan` 패턴을 권장.
- `yield` 이전 = startup, 이후 = shutdown.
- **왜 lifespan인가?**: `on_event`는 startup에서 생성한 리소스를 shutdown에서 참조하기 어렵고, 테스트에서 모킹하기도 불편. lifespan은 하나의 컨텍스트 매니저로 묶어서 리소스 관리가 깔끔함.

## Dependency Injection (DI)

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

@app.get("/items")
async def read_items(db: AsyncSession = Depends(get_db)):
    ...
```

- `Depends()`로 의존성을 선언적으로 주입. 테스트 시 `app.dependency_overrides`로 쉽게 교체.
- **yield 의존성**: `yield` 이전이 "setup", 이후가 "teardown". DB 세션 관리에 이상적.
- 의존성은 요청 단위로 캐싱됨. 같은 요청 내에서 `Depends(get_db)`를 여러 곳에서 호출해도 세션은 하나.

## Pydantic v2

- Rust 기반 `pydantic-core`로 검증 속도 5~50배 향상.
- `model_validator`, `field_validator` 데코레이터로 커스텀 검증.
- `model_config = ConfigDict(from_attributes=True)` → ORM 모델에서 바로 변환 가능.
- **JSON Schema 자동 생성**: OpenAPI 스펙 + Swagger UI가 자동으로 만들어지는 이유.

## SSE (Server-Sent Events) vs WebSocket

| 항목 | SSE | WebSocket |
|---|---|---|
| 방향 | 서버 → 클라이언트 (단방향) | 양방향 |
| 프로토콜 | HTTP/1.1 or HTTP/2 | 별도 프로토콜 (ws://) |
| 재연결 | 브라우저가 자동 재연결 | 직접 구현 |
| 적합한 경우 | LLM 스트리밍, 알림 | 채팅, 실시간 게임 |

- LLM 응답 스트리밍에는 SSE가 적합. 클라이언트가 서버에 추가 데이터를 보낼 필요 없음.
- FastAPI에서는 `StreamingResponse` + `async generator`로 구현.

## Middleware

요청/응답 파이프라인에 끼워넣는 처리 레이어.

```
Client → CORS → RateLimit → Logging → Router → Handler → Logging → Client
```

- **실행 순서**: 등록 역순으로 실행. 마지막에 등록한 미들웨어가 가장 바깥쪽.
- **CORS**: 브라우저 보안 정책. 프론트엔드와 백엔드 도메인이 다르면 반드시 설정.
- **요청 로깅 미들웨어**: request_id 부여 → structlog로 추적 → 응답 시간 측정.

## Background Tasks vs Celery

- `BackgroundTasks`: 응답 반환 후 같은 프로세스에서 실행. 가벼운 작업 (이메일 발송, 로그 기록).
- **Celery**: 별도 워커 프로세스에서 실행. 무거운 작업 (문서 파싱, 임베딩 생성, 대용량 처리).
- 차이점: BackgroundTasks는 서버가 죽으면 작업도 사라짐. Celery는 Redis/RabbitMQ에 큐잉되어 있어서 워커 재시작 후 재처리 가능.

## Rate Limiting

- **Token Bucket**: 일정 속도로 토큰이 쌓이고, 요청 시 토큰을 소모. 버스트 허용.
- **Sliding Window**: 시간 창 내 요청 수 카운트. 더 정확하지만 구현 복잡.
- API 서버에서는 보통 IP 기반 + API 키 기반 이중 제한.
- Redis를 사용하면 분산 환경에서도 일관된 Rate Limiting 가능.
