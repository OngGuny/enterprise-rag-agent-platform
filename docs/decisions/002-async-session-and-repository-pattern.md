# ADR-002: SQLAlchemy AsyncSession + 리포지토리 패턴

- **상태**: 채택
- **작성일**: 2026-05-06
- **관련 모듈**: `src/db/session.py`, `src/db/base.py`, `src/db/repositories/`(예정), `src/api/dependencies.py`

## 맥락

본 플랫폼은 다음 부하 특성을 가진다.

- **HTTP 요청은 거의 모두 IO 바운드**. PostgreSQL 쿼리, Redis 캐시 조회, Milvus 검색, LLM 호출(가장 느림)이 직렬·병렬로 엮인다.
- **요청 시간이 길다**. RAG 한 번이 보통 1~10초, 스트리밍 응답은 더 길다. 동기 워커 기반 요청-스레드 모델로는 동시성을 내기 어렵다.
- **동시성 목표**: 단일 노드에서 수백 동시 요청. 대부분의 시간을 외부 IO 대기에 쓴다 → async 가 적합하다.
- **도메인 복잡도**: 문서·청크·인제스트 잡·에이전트 세션 등 도메인 엔티티가 많고, 동일 엔티티에 대한 쿼리가 여러 호출자(API / Celery 워커 / 에이전트 노드) 에서 발생한다.
- **테스트 가능성**: API 핸들러 / 워커 / 에이전트 노드를 단위·통합 테스트로 모두 커버해야 한다.

## 선택지

### A) SQLAlchemy 2.x AsyncSession + 리포지토리 패턴 (선택)
- API 엔드포인트는 `Annotated[AsyncSession, Depends(get_db)]` 로 세션을 주입받는다.
- 도메인 데이터 접근 로직은 리포지토리(`DocumentRepository`, `ChunkRepository`, ...) 클래스로 분리.
- 장점: ORM 레벨의 풍부한 기능(관계, eager loading, identity map) + async 전면 + 도메인-인프라 분리 + 모킹/대체 용이.
- 단점: 학습 곡선 (특히 `selectinload`, `await session.execute()`, autoflush 동작), `await` 누락 시 침묵하다 폭발할 수 있음.

### B) SQLAlchemy Core (async) + DAO 함수
- ORM 레이어를 제거하고 Core 표현식(SELECT/INSERT/UPDATE) 을 직접 쓰는 방식.
- 장점: ORM 매직이 없어 디버깅 쉬움, 성능 예측 가능.
- 단점: 관계 매핑·관계 쿼리·identity map 을 모두 직접 구현. 도메인 엔티티가 많을수록 보일러플레이트 폭증.

### C) asyncpg 직쿼리 + Pydantic 변환
- 가장 빠름.
- 장점: 단순, 매우 빠름.
- 단점: 마이그레이션·관계·트랜잭션 헬퍼·세션 컨텍스트를 전부 직접 구축해야 함. 본 플랫폼처럼 엔티티가 많은 경우 비용이 너무 크다.

### D) 동기 SQLAlchemy + threadpool
- 장점: SQLAlchemy 의 모든 기능 활용, 학습 곡선 낮음.
- 단점: FastAPI async 코드 안에서 동기 DB 호출은 worker thread 를 점유 → 외부 LLM/벡터 검색을 동시에 await 하는 RAG 시나리오에서 동시성 목표 미달.

## 결정

- **AsyncSession** 을 표준으로 채택. 동기 DB 접근은 마이그레이션(Alembic)·CLI 도구 같은 예외에만 한정.
- **리포지토리 패턴** 으로 도메인 데이터 접근을 분리. API/워커/에이전트는 리포지토리 인터페이스에 의존.
- **세션 수명**은 요청 단위(`get_db_session` 제너레이터). FastAPI Depends 로 주입.
- **트랜잭션 경계**는 세션 제너레이터에서 관리(`yield → commit / except → rollback`).

## 근거

1. **부하 특성과의 정합성**. 요청의 대부분 시간이 IO 대기(특히 LLM·Milvus)이므로, async 기반 동시성이 단일 노드 처리량을 가장 크게 끌어올린다. 동기 SQLAlchemy + threadpool 은 LLM 스트리밍과 함께 쓸 때 스레드 고갈을 유발하기 쉽다.
2. **도메인 표현력**. 문서·청크·메타데이터의 관계, eager loading, 트랜잭션 일관성은 ORM 으로 표현하는 게 가장 깔끔하다. Core/asyncpg 는 단순 CRUD 가 압도적인 서비스에 적합한데, 본 플랫폼은 엔티티가 많고 관계도 풍부하다.
3. **테스트 가능성**. 리포지토리 인터페이스 → 단위 테스트에서는 in-memory/Stub 리포지토리를 주입, 통합 테스트에서는 실제 DB. 핸들러 단위 테스트에서 SQLAlchemy 매직을 다루지 않아도 된다.
4. **트랜잭션 경계 명시화**. `get_db_session` 이 정상 종료 시 commit, 예외 시 rollback 을 책임진다. 핸들러 코드는 트랜잭션을 신경 쓰지 않게 되어 일관된 정책이 강제된다. 실제 구현(`src/db/session.py`):
   ```python
   async def get_db_session():
       async with async_session_factory() as session:
           try:
               yield session
               await session.commit()
           except Exception:
               await session.rollback()
               raise
   ```
5. **풀 설계**. `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True`, `pool_recycle=1800`. 30분 재활용은 PgBouncer/네트워크 NAT 사이드의 idle timeout 을 회피하기 위함. pre-ping 은 stale connection 으로 인한 첫 요청 실패를 막는다.

## 결과

- 모든 API 엔드포인트는 `DbDep`(`Annotated[AsyncSession, Depends(get_db)]`) 로 세션을 받는다 — 이미 헬스체크에서 사용 중.
- 리포지토리는 `src/db/repositories/` 아래 `BaseRepository[ModelT]` 를 상속받아 구현 (Phase 3).
- Celery 워커는 별도의 세션 팩토리(또는 동일 엔진 기반의 별도 세션) 를 가지며 — 워커 코드도 동일한 리포지토리 인터페이스를 사용한다 (Phase 7).
- 마이그레이션은 Alembic 으로 관리 (Phase 3). Alembic 자체는 동기 엔진을 쓰므로 별도 동기 URL 을 만든다.
- 위험과 모니터링:
  - **`await` 누락**: 코드 리뷰와 mypy strict 모드, ruff 의 awaitable 관련 룰로 1차 방어.
  - **세션 누수**: 핸들러가 세션을 backround task 로 넘기는 안티패턴이 발생할 수 있다 — 가이드 문서로 금지하고, 테스트에서 풀 메트릭을 확인.
  - **N+1**: ORM 의 전형적 함정. 리포지토리 메서드는 명시적 `selectinload` / `joinedload` 정책을 갖는다.
- 향후 결정: 리포지토리에서 트랜잭션을 직접 열어야 하는 경우(여러 리포지토리에 걸친 연산) 는 Unit of Work 패턴 도입을 별도 ADR 로 정리.

## 참고

- 관련 ADR: ADR-001 (Milvus 채택, 메타데이터 권위는 PostgreSQL), ADR-003 (싱글톤 매니저 — DB 엔진은 모듈 수준 싱글톤이지만 매니저 클래스가 아닌 이유 포함)
- [SQLAlchemy 2.0 Async ORM](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [FastAPI Async DB Dependencies](https://fastapi.tiangolo.com/tutorial/sql-databases/)
