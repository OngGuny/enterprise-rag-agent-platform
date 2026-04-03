# FastAPI 핵심 개념

## ASGI vs WSGI

- **WSGI** (Web Server Gateway Interface): 동기 처리. 요청 하나당 스레드 하나. Flask, Django.
- **ASGI** (Asynchronous Server Gateway Interface): 비동기 처리. 이벤트 루프 기반. FastAPI, Starlette.
- ASGI는 WebSocket, HTTP/2, SSE 같은 long-lived connection을 네이티브로 지원.
- WSGI에서 동시 1000 요청을 처리하려면 스레드 1000개가 필요하지만, ASGI는 단일 이벤트 루프에서 처리 가능.

## Uvicorn

- ASGI 서버 구현체. `uvloop` (libuv 기반 이벤트 루프) 사용 시 순수 asyncio 대비 2~4배 빠름.
- **Gunicorn + Uvicorn Worker** 조합: Gunicorn이 프로세스 매니저 역할, Uvicorn Worker가 실제 요청 처리.
  ```bash
  gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker
  ```
- 프로덕션에서는 멀티 워커 필수. CPU 코어 수 * 2 + 1이 일반적인 워커 수 공식.

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
