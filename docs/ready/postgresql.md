# PostgreSQL 핵심 개념

## MVCC (Multi-Version Concurrency Control)

- PostgreSQL의 동시성 제어 핵심 메커니즘.
- 데이터를 수정하면 기존 row를 덮어쓰지 않고, **새 버전의 row를 생성**함.
- 각 트랜잭션은 자기 시작 시점의 스냅샷을 보기 때문에 읽기와 쓰기가 서로 블로킹하지 않음.
- `xmin` (생성 트랜잭션 ID), `xmax` (삭제 트랜잭션 ID) 히든 컬럼으로 버전 관리.

### 예시
```
트랜잭션 A: SELECT * FROM users WHERE id=1;  (xmin=100 버전을 봄)
트랜잭션 B: UPDATE users SET name='new' WHERE id=1;  (xmin=200 새 row 생성, 기존 row의 xmax=200)
트랜잭션 A: SELECT * FROM users WHERE id=1;  (여전히 xmin=100 버전을 봄 - 스냅샷)
```

## VACUUM (바큠)

MVCC 때문에 UPDATE/DELETE 시 이전 버전 row가 남아있음 → **Dead Tuple**.

- **VACUUM**: Dead Tuple이 차지한 공간을 "재사용 가능"으로 표시. OS에 반환하지는 않음.
- **VACUUM FULL**: 테이블을 새로 작성하여 물리적으로 공간 회수. 테이블 잠금 발생 → 프로덕션에서 주의.
- **autovacuum**: 백그라운드에서 자동으로 VACUUM 실행. 기본 활성화.

### autovacuum이 중요한 이유
1. **디스크 팽창 방지**: Dead Tuple이 쌓이면 테이블 크기가 계속 증가.
2. **인덱스 성능 유지**: Dead Tuple이 인덱스에도 남아있어 검색 성능 저하.
3. **Transaction ID Wraparound 방지**: 트랜잭션 ID는 32비트(약 42억). 다 쓰면 DB가 멈춤. VACUUM이 오래된 트랜잭션 ID를 "frozen"으로 표시하여 재활용.

### 모니터링 쿼리
```sql
-- Dead Tuple 확인
SELECT relname, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
```

## 인덱스

### B-tree (기본)
- 등호(`=`), 범위(`<`, `>`, `BETWEEN`), 정렬(`ORDER BY`)에 최적.
- 대부분의 경우 B-tree로 충분.

### GIN (Generalized Inverted Index)
- 배열, JSONB, 전문검색(tsvector)에 사용.
- "이 값을 포함하는 row는?" 질의에 최적.
- JSONB 컬럼에 `@>` 연산자 쓸 때 GIN 인덱스 필수.

### GiST (Generalized Search Tree)
- 기하학적 데이터, 범위 타입, 전문검색.
- **pgvector의 벡터 인덱스**도 GiST 또는 IVFFlat/HNSW 확장으로 구현.

### 부분 인덱스 (Partial Index)
```sql
CREATE INDEX idx_active_users ON users(email) WHERE is_active = true;
```
- 조건을 만족하는 row만 인덱스에 포함 → 크기 절약 + 성능 향상.

## Connection Pooling

- PostgreSQL은 연결당 프로세스를 fork함 → 연결 생성 비용이 큼 (약 1.3MB/연결).
- **PgBouncer**: 외부 커넥션 풀러. 수백~수천 앱 연결을 수십 개 DB 연결로 다중화.
- **SQLAlchemy 내장 풀**: `create_async_engine(pool_size=20, max_overflow=10)`
  - `pool_size`: 항상 유지하는 연결 수
  - `max_overflow`: 풀이 찼을 때 추가로 만들 수 있는 연결 수
  - `pool_timeout`: 연결 대기 최대 시간

## Async Driver: asyncpg

- Python에서 가장 빠른 PostgreSQL async 드라이버.
- Cython + 프로토콜 직접 구현 (libpq를 사용하지 않음).
- prepared statement 자동 캐싱 → 반복 쿼리 성능 향상.
- SQLAlchemy 2.x에서 `create_async_engine("postgresql+asyncpg://...")`로 사용.

## 트랜잭션 격리 수준

| 레벨 | Dirty Read | Non-repeatable Read | Phantom Read |
|---|---|---|---|
| Read Uncommitted | PostgreSQL에서는 Read Committed로 동작 | - | - |
| **Read Committed** (기본) | X | O | O |
| Repeatable Read | X | X | X (PostgreSQL은 snapshot으로 방지) |
| Serializable | X | X | X |

- PostgreSQL의 Repeatable Read는 진짜 스냅샷 격리. Phantom Read도 방지.
- Serializable은 SSI (Serializable Snapshot Isolation) 구현. 충돌 시 트랜잭션을 abort.

## EXPLAIN ANALYZE

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM documents WHERE collection_id = 5;
```

- `Seq Scan`: 풀 테이블 스캔. 인덱스 없거나 selectivity가 낮을 때.
- `Index Scan`: 인덱스 탐색 후 heap에서 row 가져옴.
- `Index Only Scan`: 인덱스만으로 결과 반환 (covering index).
- `Bitmap Index Scan` → `Bitmap Heap Scan`: 여러 인덱스 조건을 OR/AND로 결합.
- `actual time`: 실제 실행 시간 (ms). `rows`: 실제 반환 row 수.
