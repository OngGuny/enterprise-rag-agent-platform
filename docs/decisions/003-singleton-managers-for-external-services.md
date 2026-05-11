# ADR-003: 외부 서비스 매니저 싱글톤 (Redis / Milvus)

- **상태**: 채택
- **작성일**: 2026-05-06
- **관련 모듈**: `src/core/redis.py`, `src/core/milvus.py`, `src/main.py`(lifespan), `src/api/dependencies.py`

## 맥락

플랫폼은 외부 stateful 서비스에 의존한다.

- **PostgreSQL**: SQLAlchemy 엔진 + 커넥션 풀.
- **Redis**: 캐시(DB 0), Celery 브로커(DB 1), Celery 결과 백엔드(DB 2). 비동기 클라이언트.
- **Milvus**: 벡터 검색. PyMilvus 의 `MilvusClient` (gRPC 기반). 클라이언트는 내부적으로 채널 풀을 갖는다.

이들에 대해 다음을 만족해야 한다.

- 앱 부팅 시 1회 연결, 요청마다 새로 만들지 않음 (gRPC/TCP 핸드쉐이크 비용 회피).
- FastAPI 의 비동기 lifespan 에 정확히 맞물려야 함 — startup 시 connect, shutdown 시 disconnect.
- 앱 코드(API 핸들러 / 워커 태스크 / 에이전트 노드) 가 **동일한 인스턴스에 접근**해야 함.
- 연결이 아직 안 된 상태에서 사용을 시도하면 명시적 에러 (silent None 사용 금지).
- 테스트에서 교체/모킹 가능해야 함.

## 선택지

### A) 클래스 메서드 기반 매니저 + classvar 풀 (선택)
- `RedisManager` / `MilvusManager` 가 `_pool` / `_client` 를 클래스 변수로 보유.
- `connect / get_client / disconnect` 모두 `@classmethod`.
- 장점: 명시적 lifecycle, `get_client()` 시 미연결 상태를 즉시 감지하고 `RuntimeError` 로 fail-fast, lifespan 코드가 한 줄로 깔끔.
- 단점: 클래스 변수 = 전역 상태. 테스트에서 격리하려면 명시적 reset / 모킹 필요.

### B) 모듈 수준 글로벌 변수
- `redis_pool: ConnectionPool | None = None` 같은 모듈 변수에 보관.
- 장점: 가장 단순.
- 단점: 미연결 상태 가드를 함수 단위로 매번 작성해야 함, 네이밍 충돌 위험, IDE 자동완성/타입 추론이 약함.

### C) FastAPI `app.state` 에 부착
- `app.state.redis_pool = pool` 형태.
- 장점: FastAPI 표준 패턴, 테스트에서 앱 인스턴스만 갈아끼우면 격리 자연스러움.
- 단점: 워커(Celery) / 에이전트(LangGraph) / CLI 컨텍스트에는 `app` 객체가 없다. 다른 진입점에서 동일한 자원을 쓰려면 결국 별도 접근 경로가 필요해 추상화가 분기.

### D) DI 컨테이너 (`dependency-injector`, `lagom` 등)
- 장점: 가장 일반적, 강력. 테스트 격리 1급.
- 단점: 학습 곡선과 부가 의존성. 본 프로젝트 규모와 인프라 자원 수에서는 과한 도구.

### E) `lru_cache` 로 감싼 팩토리
- 장점: 단순, 테스트에서 `cache_clear()` 로 리셋.
- 단점: 비동기 connect/disconnect 라이프사이클을 깔끔히 표현하기 어렵다 (lru_cache 는 동기 객체 캐싱).

## 결정

- **클래스 메서드 매니저**(옵션 A) 를 Redis 와 Milvus 에 적용.
- **PostgreSQL 엔진은 모듈 수준 객체**(`src/db/session.py` 의 `engine`, `async_session_factory`) — SQLAlchemy 의 표준 패턴이고, 엔진 자체가 풀과 lifecycle 메서드를 자체 보유하기 때문에 별도 매니저 클래스를 두는 게 오히려 중복이다. lifespan 의 shutdown 에서 `await engine.dispose()` 만 호출.
- FastAPI 의존성은 매니저의 `get_client()` 를 얇게 감싸는 함수(`get_redis`, `get_milvus`)로 노출, `Annotated` alias(`RedisDep`, `MilvusDep`) 로 사용.

## 근거

1. **Lifespan 통합**. `src/main.py` 의 lifespan 이 다음 순서로 실행된다 — 매니저는 이 흐름에 한 줄씩 자연스럽게 들어간다.
   ```python
   await RedisManager.connect(settings.redis_url, settings.redis_max_connections)
   try:
       MilvusManager.connect(settings.milvus_uri)
   except Exception:
       logger.warning("milvus_connection_failed", uri=settings.milvus_uri)
   ...
   yield
   MilvusManager.disconnect()
   await RedisManager.disconnect()
   await engine.dispose()
   ```
2. **Fail-fast**. `get_client()` 가 `_pool is None` 이면 즉시 `RuntimeError` 를 던진다 — 어떤 경로에서든 lifespan 을 우회하면 바로 깨지므로, 부분 부팅 상태에서 silent None 으로 사용되어 nil-pointer 같은 디버깅 불가 에러를 만들지 않는다.
3. **Milvus 부분 실패 흡수**. Milvus 는 부팅 순서에 따라 일시적으로 안 떠 있을 수 있다. 본 플랫폼은 검색 외 기능(인증, 문서 업로드 큐잉) 은 Milvus 없이도 동작 가능해야 하므로, lifespan 에서 `MilvusManager.connect` 실패를 warning 으로 흡수하고 readiness probe 가 503 으로 신호한다. 이는 Milvus 채택(ADR-001) 의 운영 컴포넌트 증가 트레이드오프를 낮추는 장치다.
4. **테스트 가능성**. 매니저는 `_pool` / `_client` 를 직접 참조할 수 있어 테스트에서 모킹 또는 명시적 reset 이 가능. FastAPI Depends 의 `app.dependency_overrides` 로 `get_redis` / `get_milvus` 를 교체하면 핸들러 단위 테스트에서 외부 서비스를 stub 으로 대체.
5. **워커/에이전트 일관성**. Celery 워커도 부팅 시 동일한 `RedisManager.connect` 를 호출하도록 통일하면 코드 베이스 전체가 같은 매니저 추상화를 공유 → `app.state` 방식보다 진입점 비특이성이 좋다.

## 결과

- API 핸들러는 `RedisDep`, `MilvusDep`, `DbDep` 만 알면 된다. 매니저의 존재를 핸들러가 직접 인식할 일 없음.
- Phase 1 readiness 엔드포인트(`/api/v1/health/ready`) 가 세 자원의 ping 을 수행해 503/200 을 분리 — 통합테스트에서 lifespan + 외부 자원 연결을 검증할 진입점이 된다 (Phase 1 통합테스트 참조).
- Celery 워커 부팅(Phase 7) 시 동일한 매니저 connect 를 워커 startup signal 에 연결 → 코드 재사용.
- 위험과 모니터링:
  - **테스트 간 상태 누수**: 클래스 변수 = 전역. conftest 의 fixture 가 앱 lifespan 으로 connect/disconnect 를 감싸는 형태로 격리를 강제한다.
  - **이중 connect**: 같은 매니저에 `connect` 두 번 호출하면 이전 풀을 덮어쓴다 — Phase 2 에서 idempotent 가드를 추가할지 검토. 현 상태는 lifespan 단일 진입점 가정.
  - **Redis 연결 풀 사이즈**: `max_connections=50` 으로 시작. Celery 도 같은 인스턴스를 쓰면 별도 DB 분리(0/1/2)와 별도 풀로 분리 운영 — 캐시 트래픽이 broker 를 굶기지 않게.

## 참고

- 관련 ADR: ADR-001 (Milvus 채택), ADR-002 (AsyncSession — 매니저 vs 모듈 글로벌의 비대칭 결정)
- [PEP 553 — async context managers](https://peps.python.org/pep-0492/)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [redis-py async ConnectionPool](https://redis-py.readthedocs.io/en/stable/connections.html#async-client)
