# SQLAlchemy 핵심 개념

## SQLAlchemy 2.x 변화

- 1.x → 2.x에서 가장 큰 변화: **네이티브 async 지원** + **새로운 쿼리 스타일**.
- `select(User).where(User.id == 1)` 스타일 (1.x의 `session.query(User).filter(...)` 대신).
- Type hint 기반 모델 정의: `Mapped[str]`, `mapped_column()`.

## AsyncSession

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine("postgresql+asyncpg://...", pool_size=20)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

### expire_on_commit=False가 중요한 이유
- 기본값은 `True`: 커밋 후 모든 속성이 "expired" 상태 → 다음 접근 시 DB 재조회.
- async에서는 expired 속성 접근이 **암묵적 I/O를 발생시켜 오류** (이벤트 루프에서 동기 I/O 불가).
- `False`로 설정하면 커밋 후에도 메모리에 있는 값을 그대로 사용.

## Unit of Work 패턴

SQLAlchemy Session은 Unit of Work 패턴을 구현:

1. 객체를 `session.add()` → Identity Map에 등록
2. 속성 변경을 자동 추적 (dirty check)
3. `session.commit()` 시 변경된 것만 모아서 최소한의 SQL 실행
4. 실패 시 `session.rollback()`으로 전체 원복

### Identity Map
- 같은 세션 내에서 같은 PK의 객체는 항상 같은 Python 인스턴스.
- `session.get(User, 1)` 두 번 호출해도 `SELECT`는 한 번만 실행.

## Relationship & Lazy Loading

```python
class Document(Base):
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")

class Chunk(Base):
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    document: Mapped["Document"] = relationship(back_populates="chunks")
```

### Lazy Loading 전략
| 전략 | 설명 | async 호환 |
|---|---|---|
| `lazy="select"` (기본) | 접근 시 SELECT 실행 | X (암묵적 I/O) |
| `lazy="joined"` | JOIN으로 함께 로드 | O |
| `lazy="selectin"` | `SELECT ... WHERE id IN (...)` | O (async 권장) |
| `lazy="subquery"` | 서브쿼리로 로드 | O |
| `lazy="raise"` | 접근 시 에러 발생 | O (실수 방지용) |

- **async에서는 `selectin` 또는 `joined` 필수**. 기본 `select`는 암묵적 I/O로 에러.
- 또는 쿼리에서 명시적으로 `options(selectinload(Document.chunks))`.

## Alembic (마이그레이션)

```bash
alembic init alembic          # 초기 설정
alembic revision --autogenerate -m "add documents table"  # 마이그레이션 생성
alembic upgrade head          # 적용
alembic downgrade -1          # 롤백
```

- `--autogenerate`: 모델과 DB 상태를 비교하여 자동으로 마이그레이션 스크립트 생성.
- 자동 감지 가능: 테이블/컬럼 추가/삭제, 타입 변경, 인덱스 추가.
- 자동 감지 불가: 컬럼 이름 변경 (삭제+추가로 인식), 데이터 마이그레이션.

## Repository 패턴

```python
class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, doc_id: int) -> Document | None:
        return await self.session.get(Document, doc_id)

    async def create(self, doc: Document) -> Document:
        self.session.add(doc)
        await self.session.flush()  # ID 생성, 아직 커밋은 아님
        return doc
```

### flush vs commit
- `flush()`: SQL을 DB에 전송하지만 트랜잭션은 열려있음. auto-increment ID를 받아올 때 사용.
- `commit()`: 트랜잭션 확정. 이후 롤백 불가.
- 패턴: 서비스 레이어에서 `commit()`, 리포지토리에서는 `flush()`만.
