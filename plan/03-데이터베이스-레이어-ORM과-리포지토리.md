# 03. 데이터베이스 레이어: ORM 모델과 리포지토리 패턴

## 목표

PostgreSQL에 저장할 메타데이터 모델을 설계하고, 리포지토리 패턴으로 데이터 접근을 추상화한다. Alembic으로 마이그레이션을 관리한다.

---

## 3.1 ORM 모델 설계

### 공통 베이스

```python
class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
```

### Document 모델 (db/models/document.py)

문서 메타데이터를 관리한다. 실제 벡터/텍스트는 Milvus에 저장.

```python
class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "documents"

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20))         # pdf, docx, pptx, web
    file_size: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[DocumentStatus] = mapped_column(
        SQLAlchemyEnum(DocumentStatus),
        default=DocumentStatus.PENDING,
        index=True,
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id"),
        index=True,
    )
    chunk_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
    )
    # 인제스트 처리 정보
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    processing_started_at: Mapped[datetime | None]
    processing_completed_at: Mapped[datetime | None]

    # Relationships
    collection: Mapped["Collection"] = relationship(back_populates="documents")
```

### Collection 모델 (db/models/collection.py)

Milvus 컬렉션과 1:1 매핑되는 논리적 그룹.

```python
class Collection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "collections"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    milvus_collection_name: Mapped[str] = mapped_column(String(200), unique=True)
    embedding_model: Mapped[str] = mapped_column(String(100), default="bge-m3")
    embedding_dim: Mapped[int] = mapped_column(default=1024)
    document_count: Mapped[int] = mapped_column(default=0)
    total_chunks: Mapped[int] = mapped_column(default=0)

    # Relationships
    documents: Mapped[list["Document"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
    )
```

### ChatHistory 모델 (db/models/chat_history.py)

```python
class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class ChatHistory(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "chat_history"

    session_id: Mapped[uuid.UUID] = mapped_column(index=True)
    role: Mapped[ChatRole]
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(100))
    token_count: Mapped[int | None]
    latency_ms: Mapped[float | None]

    # RAG 관련
    retrieved_chunks: Mapped[list[dict] | None] = mapped_column(JSONB)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collections.id"))
```

### AgentLog 모델 (db/models/agent_log.py)

에이전트 실행의 각 스텝을 기록.

```python
class AgentLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agent_logs"

    execution_id: Mapped[uuid.UUID] = mapped_column(index=True)  # 하나의 실행 세션
    step_number: Mapped[int]
    node_name: Mapped[str] = mapped_column(String(100))           # analyze, rag_search, ...
    input_data: Mapped[dict] = mapped_column(JSONB)
    output_data: Mapped[dict] = mapped_column(JSONB)
    tool_calls: Mapped[list[dict] | None] = mapped_column(JSONB)
    duration_ms: Mapped[float]
    token_count: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
```

---

## 3.2 리포지토리 패턴

### Base Repository

```python
class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: uuid.UUID) -> T | None:
        return await self.session.get(self.model, id)

    async def get_many(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: str = "created_at",
        filters: dict | None = None,
    ) -> tuple[list[T], int]:
        """페이지네이션 + 필터링. (items, total_count) 반환."""
        query = select(self.model)
        count_query = select(func.count()).select_from(self.model)

        if filters:
            for field, value in filters.items():
                query = query.where(getattr(self.model, field) == value)
                count_query = count_query.where(getattr(self.model, field) == value)

        total = await self.session.scalar(count_query)
        query = query.order_by(desc(getattr(self.model, order_by)))
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)

        return list(result.scalars().all()), total or 0

    async def create(self, **kwargs) -> T:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()   # ID 할당을 위해 flush (commit은 DI에서)
        return instance

    async def update(self, id: uuid.UUID, **kwargs) -> T | None:
        instance = await self.get_by_id(id)
        if instance is None:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, id: uuid.UUID) -> bool:
        instance = await self.get_by_id(id)
        if instance is None:
            return False
        await self.session.delete(instance)
        return True
```

### DocumentRepository

```python
class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Document)

    async def get_by_collection(
        self, collection_id: uuid.UUID, *, status: DocumentStatus | None = None
    ) -> list[Document]:
        query = select(Document).where(Document.collection_id == collection_id)
        if status:
            query = query.where(Document.status == status)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_status(
        self,
        doc_id: uuid.UUID,
        status: DocumentStatus,
        *,
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> Document | None:
        update_data = {"status": status}
        if status == DocumentStatus.PROCESSING:
            update_data["processing_started_at"] = func.now()
        elif status in (DocumentStatus.COMPLETED, DocumentStatus.FAILED):
            update_data["processing_completed_at"] = func.now()
        if error_message:
            update_data["error_message"] = error_message
        if chunk_count is not None:
            update_data["chunk_count"] = chunk_count
        return await self.update(doc_id, **update_data)
```

### 프로덕션 포인트

- `flush()` vs `commit()`: 리포지토리는 flush만. commit은 요청 경계(DI)에서 한 번만
- Generic BaseRepository로 CRUD 보일러플레이트 제거
- 복잡한 쿼리는 전용 메서드로 (raw SQL도 허용하되 SQLAlchemy `text()` 사용)
- 페이지네이션은 `(items, total)` 튜플 반환 → API 응답에서 `total`, `has_more` 계산 가능

---

## 3.3 Alembic 마이그레이션

### 설정

```
alembic/
├── env.py              # async migration 설정
├── versions/           # 자동 생성 마이그레이션 파일
└── alembic.ini
```

### env.py 핵심 (async)

```python
from sqlalchemy.ext.asyncio import async_engine_from_config

async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
```

### 마이그레이션 전략

- 초기: `alembic revision --autogenerate -m "initial tables"`
- 이후: 모델 변경마다 autogenerate → 수동 검토 → 적용
- 다운그레이드 함수도 반드시 작성 (롤백 가능하도록)

---

## 3.4 Pydantic 스키마 (api/schemas/)

### Document 스키마

```python
class DocumentCreate(BaseModel):
    collection_id: uuid.UUID
    metadata: dict = {}

class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    collection_id: uuid.UUID
    chunk_count: int
    created_at: datetime
    updated_at: datetime

class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    offset: int
    limit: int
    has_more: bool
```

### 프로덕션 포인트

- `from_attributes=True`로 ORM 모델 → Pydantic 자동 변환
- 요청/응답 모델 분리 (Create, Update, Response)
- 리스트 응답은 항상 페이지네이션 메타 포함
- 내부 필드(celery_task_id, error_message 등)는 별도 DetailResponse에서만 노출

---

## 체크리스트

- [ ] db/base.py (Base, UUIDMixin, TimestampMixin)
- [ ] db/models/document.py
- [ ] db/models/collection.py
- [ ] db/models/chat_history.py
- [ ] db/models/agent_log.py
- [ ] db/repositories/base.py (Generic BaseRepository)
- [ ] db/repositories/document_repo.py
- [ ] db/repositories/collection_repo.py
- [ ] db/repositories/chat_repo.py
- [ ] api/schemas/document.py
- [ ] api/schemas/collection.py
- [ ] api/schemas/chat.py
- [ ] api/schemas/agent.py
- [ ] api/schemas/common.py (페이지네이션, 에러 응답)
- [ ] Alembic 초기 설정 + 첫 마이그레이션
