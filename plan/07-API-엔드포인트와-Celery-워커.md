# 07. API 엔드포인트와 Celery 비동기 워커

## 목표

사용자 대면 API 엔드포인트를 구현하고, 문서 인제스트 같은 무거운 작업은 Celery 워커로 비동기 처리한다. API 라우터를 체계적으로 구성하고, 각 엔드포인트의 요청/응답 흐름을 명확히 한다.

---

## 7.1 API 라우터 구조 (api/router.py)

```python
from fastapi import APIRouter

api_router = APIRouter()

api_router.include_router(health_router, prefix="/health", tags=["Health"])
api_router.include_router(chat_router, prefix="/chat", tags=["Chat"])
api_router.include_router(documents_router, prefix="/documents", tags=["Documents"])
api_router.include_router(collections_router, prefix="/collections", tags=["Collections"])
api_router.include_router(agents_router, prefix="/agents", tags=["Agents"])
```

모든 엔드포인트는 `/api/v1/` prefix 아래에 위치.

---

## 7.2 Chat API (api/endpoints/chat.py)

### POST /api/v1/chat

가장 핵심적인 엔드포인트. 사용자 질문을 받아 RAG 검색 + LLM 응답을 스트리밍으로 반환.

```python
@router.post("/")
async def chat(
    request: ChatRequest,
    llm_service: LLMService = Depends(get_llm_service),
    retriever: Retriever = Depends(get_retriever),
    memory: ConversationMemory = Depends(get_memory),
    db: AsyncSession = Depends(get_db),
):
    # 1. 대화 히스토리 조회
    history = await memory.get_history(request.session_id)

    # 2. RAG 검색 (컬렉션 지정 시)
    context = []
    sources = []
    if request.collection_id:
        results = await retriever.retrieve(
            query=request.query,
            collection_name=request.collection_name,
        )
        context = [r.text for r in results]
        sources = [{"text": r.text[:200], "score": r.score, "metadata": r.metadata} for r in results]

    # 3. LLM 스트리밍 응답
    async def event_stream():
        full_response = []

        async for token in llm_service.chat_stream(
            query=request.query,
            context=context,
            history=history,
        ):
            full_response.append(token)
            yield {"event": "token", "data": json.dumps({"content": token})}

        # 참조 문서 전송
        if sources:
            yield {"event": "sources", "data": json.dumps({"sources": sources})}

        # 완료
        answer = "".join(full_response)
        yield {"event": "done", "data": json.dumps({"total_length": len(answer)})}

        # 비동기로 저장 (응답 후)
        await memory.add_message(request.session_id, "user", request.query)
        await memory.add_message(request.session_id, "assistant", answer)

    return EventSourceResponse(event_stream())
```

### ChatRequest / ChatResponse 스키마

```python
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    session_id: uuid.UUID = Field(default_factory=uuid4)
    collection_id: uuid.UUID | None = None
    stream: bool = True
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: int = Field(2048, ge=1, le=8192)

class ChatResponse(BaseModel):
    """비스트리밍 응답용"""
    answer: str
    model: str
    sources: list[SourceDocument]
    usage: TokenUsage
    latency_ms: float
    cached: bool = False
```

---

## 7.3 Documents API (api/endpoints/documents.py)

### POST /api/v1/documents/ingest

파일 업로드 → Celery 태스크 발행.

```python
@router.post("/ingest", status_code=202)
async def ingest_document(
    file: UploadFile,
    collection_id: uuid.UUID = Form(...),
    db: AsyncSession = Depends(get_db),
    doc_repo: DocumentRepository = Depends(get_document_repo),
):
    # 1. 파일 타입 검증
    file_type = validate_file_type(file.filename)

    # 2. 파일 임시 저장
    file_path = await save_upload_file(file)

    # 3. DB에 문서 메타데이터 생성 (status=pending)
    document = await doc_repo.create(
        filename=file.filename,
        file_type=file_type,
        file_size=file.size,
        status=DocumentStatus.PENDING,
        collection_id=collection_id,
    )

    # 4. Celery 인제스트 태스크 발행
    task = ingest_document_task.delay(
        document_id=str(document.id),
        file_path=file_path,
        file_type=file_type,
        collection_id=str(collection_id),
    )

    # 5. 태스크 ID 저장
    await doc_repo.update(document.id, celery_task_id=task.id)

    return {
        "document_id": document.id,
        "task_id": task.id,
        "status": "pending",
        "message": "Document ingest task queued",
    }
```

### GET /api/v1/documents/{document_id}

```python
@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    doc_repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentDetailResponse:
    document = await doc_repo.get_by_id(document_id)
    if not document:
        raise NotFoundError(f"Document {document_id} not found")
    return DocumentDetailResponse.model_validate(document)
```

### GET /api/v1/documents

```python
@router.get("/")
async def list_documents(
    collection_id: uuid.UUID | None = None,
    status: DocumentStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    doc_repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentListResponse:
    filters = {}
    if collection_id:
        filters["collection_id"] = collection_id
    if status:
        filters["status"] = status

    items, total = await doc_repo.get_many(offset=offset, limit=limit, filters=filters)

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in items],
        total=total,
        offset=offset,
        limit=limit,
        has_more=(offset + limit) < total,
    )
```

---

## 7.4 Collections API (api/endpoints/collections.py)

### CRUD 엔드포인트

```python
@router.post("/", status_code=201)
async def create_collection(request: CollectionCreate, ...):
    # 1. PostgreSQL에 컬렉션 메타데이터 생성
    # 2. Milvus에 실제 컬렉션 생성 (스키마 + 인덱스)
    ...

@router.get("/")
async def list_collections(...) -> CollectionListResponse:
    ...

@router.get("/{collection_id}")
async def get_collection(collection_id: uuid.UUID, ...) -> CollectionDetailResponse:
    # 문서 수, 청크 수, Milvus 통계 포함
    ...

@router.delete("/{collection_id}", status_code=204)
async def delete_collection(collection_id: uuid.UUID, ...):
    # 1. Milvus 컬렉션 삭제
    # 2. PostgreSQL 메타데이터 삭제 (cascade)
    ...
```

---

## 7.5 Agents API (api/endpoints/agents.py)

### POST /api/v1/agents/execute

```python
@router.post("/execute")
async def execute_agent(
    request: AgentExecuteRequest,
    agent_graph: CompiledGraph = Depends(get_agent_graph),
    memory: ConversationMemory = Depends(get_memory),
):
    execution_id = str(uuid4())

    # 초기 상태
    initial_state = {
        "query": request.query,
        "messages": [],
        "current_step": 0,
        "max_steps": request.max_steps or 10,
        "tool_results": {},
        "tool_call_history": [],
        "collection_name": request.collection_name,
        "execution_id": execution_id,
        "is_sufficient": False,
    }

    # 스트리밍 실행
    if request.stream:
        async def agent_stream():
            async for event in agent_graph.astream(
                initial_state,
                config={"configurable": {"thread_id": request.session_id}},
            ):
                for node_name, node_output in event.items():
                    yield {
                        "event": "step",
                        "data": json.dumps({
                            "node": node_name,
                            "step": node_output.get("current_step"),
                            "output_preview": str(node_output)[:500],
                        }),
                    }

            yield {"event": "done", "data": json.dumps({"execution_id": execution_id})}

        return EventSourceResponse(agent_stream())

    # 비스트리밍 실행
    result = await agent_graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": request.session_id}},
    )

    return AgentExecuteResponse(
        execution_id=execution_id,
        answer=result.get("final_answer", ""),
        steps=result.get("current_step", 0),
        tool_calls=result.get("tool_call_history", []),
        confidence=result.get("confidence_score"),
    )
```

### GET /api/v1/agents/logs/{execution_id}

```python
@router.get("/logs/{execution_id}")
async def get_agent_logs(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[AgentLogResponse]:
    """에이전트 실행의 각 스텝 로그를 조회."""
    logs = await db.execute(
        select(AgentLog)
        .where(AgentLog.execution_id == execution_id)
        .order_by(AgentLog.step_number)
    )
    return [AgentLogResponse.model_validate(log) for log in logs.scalars()]
```

---

## 7.6 Celery 비동기 워커 (workers/)

### Celery 앱 설정 (workers/celery_app.py)

```python
from celery import Celery

celery_app = Celery(
    "enterprise_rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,              # 완료 후 ack (워커 죽으면 재시도)
    worker_prefetch_multiplier=1,     # 하나씩 가져감 (긴 태스크에 적합)
    task_soft_time_limit=300,         # 5분 소프트 타임아웃
    task_time_limit=600,              # 10분 하드 타임아웃
    task_default_retry_delay=60,      # 재시도 간격 60초
    task_max_retries=3,
)
```

### 인제스트 태스크 (workers/tasks/ingest.py)

```python
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def ingest_document_task(
    self,
    document_id: str,
    file_path: str,
    file_type: str,
    collection_id: str,
):
    """
    문서 인제스트 Celery 태스크.
    Celery는 sync → async 브릿지 필요.
    """
    import asyncio

    async def _run():
        # DB 상태 업데이트: pending → processing
        async with async_session_factory() as session:
            repo = DocumentRepository(session)
            await repo.update_status(document_id, DocumentStatus.PROCESSING)
            await session.commit()

        try:
            # 인제스트 파이프라인 실행
            pipeline = IngestPipeline(...)
            result = await pipeline.ingest(
                file_path=file_path,
                file_type=file_type,
                document_id=document_id,
                collection_name=f"collection_{collection_id}",
            )

            # 성공: DB 상태 업데이트
            async with async_session_factory() as session:
                repo = DocumentRepository(session)
                await repo.update_status(
                    document_id,
                    DocumentStatus.COMPLETED,
                    chunk_count=result.chunk_count,
                )
                await session.commit()

        except Exception as exc:
            # 실패: DB 상태 업데이트 + 재시도
            async with async_session_factory() as session:
                repo = DocumentRepository(session)
                await repo.update_status(
                    document_id,
                    DocumentStatus.FAILED,
                    error_message=str(exc),
                )
                await session.commit()

            # Celery 재시도 (exponential backoff)
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

        finally:
            # 임시 파일 정리
            cleanup_temp_file(file_path)

    asyncio.run(_run())
```

### 임베딩 배치 태스크 (workers/tasks/embed.py)

```python
@celery_app.task(bind=True)
def batch_embed_task(self, texts: list[str], collection_name: str):
    """대량 임베딩 생성 (인제스트 파이프라인의 하위 태스크)."""
    import asyncio

    async def _run():
        embedder = OllamaEmbedder()
        all_embeddings = []

        for batch in batched(texts, 32):
            embeddings = await embedder.embed(batch)
            all_embeddings.extend(embeddings)

            # 진행률 업데이트
            self.update_state(
                state="PROGRESS",
                meta={"current": len(all_embeddings), "total": len(texts)},
            )

        return all_embeddings

    return asyncio.run(_run())
```

### 프로덕션 포인트

- `acks_late=True`: 태스크 완료 후에만 ACK → 워커 crash 시 다른 워커가 재처리
- `worker_prefetch_multiplier=1`: 인제스트는 무거운 작업이므로 하나씩만 가져감
- Celery + asyncio 브릿지: `asyncio.run()`으로 async 코드 실행 (Celery 자체는 sync)
- Exponential backoff 재시도: `countdown=60 * (2 ** retries)` → 1분, 2분, 4분
- `update_state`로 진행률 추적 → API에서 태스크 상태 조회 가능

---

## 체크리스트

- [ ] api/router.py (라우터 통합)
- [ ] api/endpoints/chat.py (SSE 스트리밍 + 비스트리밍)
- [ ] api/endpoints/documents.py (CRUD + 인제스트 트리거)
- [ ] api/endpoints/collections.py (CRUD + Milvus 연동)
- [ ] api/endpoints/agents.py (에이전트 실행 + 로그 조회)
- [ ] api/endpoints/health.py (이미 01에서 생성)
- [ ] workers/celery_app.py (Celery 설정)
- [ ] workers/tasks/ingest.py (문서 인제스트 태스크)
- [ ] workers/tasks/embed.py (배치 임베딩 태스크)
- [ ] 파일 업로드 유틸 (임시 저장, 타입 검증, 정리)
- [ ] API 스키마 최종 검수 (요청/응답 모델)
