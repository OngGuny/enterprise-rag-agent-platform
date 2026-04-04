# 04. RAG 파이프라인: 문서 인제스트와 검색

## 목표

문서 업로드부터 벡터 저장까지의 인제스트 파이프라인과, 질문에 대한 하이브리드 검색 + Re-ranking까지의 검색 파이프라인을 프로덕션 레벨로 구현한다.

---

## 4.1 아키텍처 개요

```
인제스트: Upload → Extract → Chunk → Embed → Store (Milvus)
검  색: Query → Embed → Hybrid Search → Re-rank → Context Assembly
```

각 단계를 인터페이스(Base 클래스)로 추상화하여 전략 패턴 적용. 새로운 포맷이나 청킹 전략을 플러그인처럼 추가 가능하게 설계.

---

## 4.2 텍스트 추출기 (rag/extractors/)

### BaseExtractor 인터페이스

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ExtractedDocument:
    text: str
    metadata: dict                    # 페이지 수, 제목, 작성일 등
    pages: list[str] | None = None   # 페이지별 텍스트 (PDF, PPTX)

class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, file_path: str) -> ExtractedDocument:
        """파일에서 텍스트를 추출한다."""
        ...

    @abstractmethod
    def supports(self, file_type: str) -> bool:
        """이 추출기가 해당 파일 타입을 지원하는지."""
        ...
```

### PDFExtractor (rag/extractors/pdf.py)

```python
class PDFExtractor(BaseExtractor):
    """
    PDF 텍스트 추출. pypdf 우선, 텍스트 없으면 OCR 폴백.

    전략:
    1. pypdf로 텍스트 추출 시도
    2. 텍스트가 빈약하면 (글자 수 < threshold) → OCR 폴백
    3. 이미지 기반 PDF → pytesseract 또는 Vision API
    """

    def __init__(self, ocr_threshold: int = 100):
        self.ocr_threshold = ocr_threshold

    async def extract(self, file_path: str) -> ExtractedDocument:
        # 1차: pypdf
        pages = await self._extract_with_pypdf(file_path)

        # 2차: OCR 폴백 (텍스트가 부족한 페이지만)
        for i, page_text in enumerate(pages):
            if len(page_text.strip()) < self.ocr_threshold:
                pages[i] = await self._ocr_page(file_path, i)

        return ExtractedDocument(
            text="\n\n".join(pages),
            metadata={"page_count": len(pages), "extraction_method": "hybrid"},
            pages=pages,
        )
```

### DOCXExtractor, WebExtractor

- DOCX: `python-docx`로 paragraph + table 추출. 스타일(heading level) 보존하여 시맨틱 청킹에 활용
- Web: `httpx` + `beautifulsoup4`로 크롤링. `readability-lxml`으로 본문 추출. robots.txt 존중

### ExtractorFactory (팩토리 패턴)

```python
class ExtractorFactory:
    _extractors: dict[str, BaseExtractor] = {}

    @classmethod
    def register(cls, file_type: str, extractor: BaseExtractor):
        cls._extractors[file_type] = extractor

    @classmethod
    def get_extractor(cls, file_type: str) -> BaseExtractor:
        extractor = cls._extractors.get(file_type)
        if not extractor:
            raise UnsupportedFileTypeError(f"No extractor for: {file_type}")
        return extractor

# 앱 시작 시 등록
ExtractorFactory.register("pdf", PDFExtractor())
ExtractorFactory.register("docx", DOCXExtractor())
ExtractorFactory.register("web", WebExtractor())
```

---

## 4.3 청킹 전략 (rag/chunkers/)

### BaseChunker 인터페이스

```python
@dataclass
class Chunk:
    text: str
    metadata: dict         # 원본 페이지, 위치, parent_id 등
    chunk_index: int
    parent_id: str | None = None  # Parent-Child 관계

class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, document: ExtractedDocument) -> list[Chunk]:
        ...
```

### RecursiveChunker (rag/chunkers/recursive.py)

```python
class RecursiveChunker(BaseChunker):
    """
    계층적 구분자로 재귀 분할.
    구분자 우선순위: \n\n → \n → . → 공백
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separators: list[str] | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " "]
```

### ParentChildChunker (rag/chunkers/parent_child.py) ⭐

```python
class ParentChildChunker(BaseChunker):
    """
    Parent-Child 청킹 전략.

    - Parent: 큰 청크 (512 tokens) → 최종 컨텍스트로 LLM에 전달
    - Child: 작은 청크 (128 tokens) → Milvus에서 검색에 사용

    검색은 정밀한 child로 하고, 결과는 풍부한 parent로 반환.
    이렇게 하면 검색 정확도와 컨텍스트 충분성을 동시에 확보.
    """

    def __init__(
        self,
        parent_chunk_size: int = 512,
        child_chunk_size: int = 128,
        child_overlap: int = 32,
    ):
        self.parent_chunk_size = parent_chunk_size
        self.child_chunk_size = child_chunk_size
        self.child_overlap = child_overlap

    def chunk(self, document: ExtractedDocument) -> list[Chunk]:
        chunks = []
        # 1. Parent 청크 생성
        parents = self._split_to_parents(document.text)

        for parent_idx, parent_text in enumerate(parents):
            parent_id = f"parent_{parent_idx}"

            # 2. 각 Parent를 Child로 분할
            children = self._split_to_children(parent_text)

            for child_idx, child_text in enumerate(children):
                chunks.append(Chunk(
                    text=child_text,
                    metadata={
                        "parent_text": parent_text,  # parent 원문 보존
                        "parent_id": parent_id,
                        "child_index": child_idx,
                        "page": document.metadata.get("page"),
                    },
                    chunk_index=len(chunks),
                    parent_id=parent_id,
                ))

        return chunks
```

### 프로덕션 포인트

- 토큰 기반 크기 측정: 글자 수가 아닌 tokenizer(tiktoken)로 정확한 토큰 수 계산
- 메타데이터 보존: 원본 파일명, 페이지 번호, 섹션 제목 등을 chunk에 전파
- Parent 텍스트를 Milvus의 별도 필드(또는 PostgreSQL)에 저장하여 검색 후 복원

---

## 4.4 임베딩 생성 (rag/embeddings/)

### BaseEmbedder 인터페이스

```python
class BaseEmbedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 리스트를 임베딩 벡터로 변환. 배치 처리."""
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """단일 쿼리 임베딩. 검색 시 사용."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...
```

### OllamaEmbedder (로컬 bge-m3)

```python
class OllamaEmbedder(BaseEmbedder):
    def __init__(self, model: str = "bge-m3", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """배치 임베딩. Ollama는 단건 API이므로 asyncio.gather로 병렬화."""
        semaphore = asyncio.Semaphore(10)  # 동시 요청 제한

        async def _embed_single(text: str) -> list[float]:
            async with semaphore:
                response = await self._client.post(
                    "/api/embed",
                    json={"model": self.model, "input": text},
                )
                return response.json()["embeddings"][0]

        return await asyncio.gather(*[_embed_single(t) for t in texts])
```

### OpenAIEmbedder

```python
class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self._client = AsyncOpenAI()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """OpenAI 배치 API 사용. 최대 2048개까지 한 번에."""
        response = await self._client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]
```

### 프로덕션 포인트

- 배치 크기 조절: Ollama는 단건이므로 Semaphore로 동시성 제어, OpenAI는 네이티브 배치
- 재시도 로직: 임베딩 서버 일시 장애 시 exponential backoff
- 임베딩 정규화: cosine similarity 사용 시 L2 normalize 여부 확인 (bge-m3는 이미 정규화됨)

---

## 4.5 Milvus 벡터 저장소 (rag/vectorstore/)

### 컬렉션 스키마 (schema.py)

```python
def create_document_schema(dim: int = 1024) -> CollectionSchema:
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="chunk_index", dtype=DataType.INT32),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="parent_text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="metadata", dtype=DataType.JSON),
    ]
    return CollectionSchema(fields=fields, enable_dynamic_field=True)
```

### 인덱스 관리 (indexing.py)

```python
# Dense Vector → HNSW 인덱스
dense_index_params = {
    "index_type": "HNSW",
    "metric_type": "COSINE",
    "params": {
        "M": 16,             # 그래프 연결 수 (높을수록 정확, 메모리 증가)
        "efConstruction": 256,  # 인덱스 빌드 시 탐색 범위
    },
}

# Sparse Vector → SPARSE_INVERTED_INDEX
sparse_index_params = {
    "index_type": "SPARSE_INVERTED_INDEX",
    "metric_type": "IP",
    "params": {"drop_ratio_build": 0.2},  # 빈도 낮은 토큰 20% 제거
}
```

### Hybrid Search (search.py)

```python
async def hybrid_search(
    client: MilvusClient,
    collection_name: str,
    query_dense: list[float],
    query_sparse: dict,           # BM25 sparse vector
    top_k: int = 20,
    filter_expr: str | None = None,
) -> list[SearchResult]:
    """Dense + Sparse Hybrid Search with RRF fusion."""

    dense_req = AnnSearchRequest(
        data=[query_dense],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"ef": 128}},
        limit=top_k,
        expr=filter_expr,
    )

    sparse_req = AnnSearchRequest(
        data=[query_sparse],
        anns_field="sparse_embedding",
        param={"metric_type": "IP"},
        limit=top_k,
        expr=filter_expr,
    )

    results = client.hybrid_search(
        collection_name=collection_name,
        reqs=[dense_req, sparse_req],
        ranker=RRFRanker(k=60),
        limit=top_k,
        output_fields=["text", "parent_text", "metadata", "document_id"],
    )

    return results
```

### BM25 Sparse Vector 생성

```python
from pymilvus.model.sparse import BM25EmbeddingFunction

class BM25Encoder:
    """BM25 sparse vector 생성기."""

    def __init__(self):
        self.bm25_ef = BM25EmbeddingFunction()
        self._fitted = False

    def fit(self, corpus: list[str]):
        """코퍼스로 BM25 모델 학습 (IDF 계산)."""
        self.bm25_ef.fit(corpus)
        self._fitted = True

    def encode(self, texts: list[str]) -> list[dict]:
        """텍스트를 sparse vector로 변환."""
        return self.bm25_ef.encode_documents(texts)

    def encode_query(self, query: str) -> dict:
        return self.bm25_ef.encode_queries([query])[0]
```

### 프로덕션 포인트

- HNSW `ef` 파라미터: 검색 시 탐색 범위. 높을수록 정확하지만 느림. 128이 합리적 기본값
- RRF `k=60`: 순위 결합 파라미터. k가 클수록 하위 순위의 영향이 커짐
- Partition Key: `collection_id`를 partition key로 설정하면 멀티테넌트 시 검색 범위 자동 제한
- BM25 모델은 컬렉션 단위로 fit → 저장 → 로드 (새 문서 추가 시 re-fit 또는 incremental)

---

## 4.6 Retriever + Re-ranking (rag/retriever.py)

### 검색 → Re-ranking → Context 구성

```python
class Retriever:
    def __init__(
        self,
        milvus_client: MilvusClient,
        embedder: BaseEmbedder,
        bm25_encoder: BM25Encoder,
        reranker: CrossEncoderReranker | None = None,
    ):
        self.milvus = milvus_client
        self.embedder = embedder
        self.bm25 = bm25_encoder
        self.reranker = reranker

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5,
        search_k: int = 20,    # Hybrid Search에서 가져올 후보 수
    ) -> list[RetrievalResult]:
        # 1. Query 임베딩
        query_dense = await self.embedder.embed_query(query)
        query_sparse = self.bm25.encode_query(query)

        # 2. Hybrid Search (top search_k)
        candidates = await hybrid_search(
            self.milvus, collection_name, query_dense, query_sparse, top_k=search_k
        )

        # 3. Re-ranking (search_k → top_k)
        if self.reranker:
            candidates = await self.reranker.rerank(query, candidates, top_k=top_k)
        else:
            candidates = candidates[:top_k]

        # 4. Parent 텍스트 복원 (child → parent)
        results = []
        seen_parents = set()
        for candidate in candidates:
            parent_text = candidate.get("parent_text", candidate["text"])
            parent_id = candidate.get("metadata", {}).get("parent_id")

            # 같은 parent의 중복 제거
            if parent_id and parent_id in seen_parents:
                continue
            if parent_id:
                seen_parents.add(parent_id)

            results.append(RetrievalResult(
                text=parent_text,
                score=candidate.score,
                metadata=candidate.get("metadata", {}),
            ))

        return results
```

### Cross-Encoder Re-ranker

```python
class CrossEncoderReranker:
    """
    Cross-Encoder로 (query, document) 쌍의 관련성 점수를 재계산.
    Bi-encoder(임베딩)보다 정확하지만 느림 → top-k 후보에만 적용.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    async def rerank(
        self, query: str, candidates: list[dict], top_k: int = 5
    ) -> list[dict]:
        pairs = [(query, c["text"]) for c in candidates]

        # CPU-bound → run_in_executor
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, self.model.predict, pairs)

        for candidate, score in zip(candidates, scores):
            candidate["rerank_score"] = float(score)

        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        return candidates[:top_k]
```

---

## 4.7 인제스트 파이프라인 오케스트레이터 (rag/pipeline.py)

```python
class IngestPipeline:
    """문서 인제스트의 전체 흐름을 오케스트레이션."""

    def __init__(
        self,
        extractor_factory: ExtractorFactory,
        chunker: BaseChunker,
        embedder: BaseEmbedder,
        milvus_client: MilvusClient,
        bm25_encoder: BM25Encoder,
    ):
        ...

    async def ingest(
        self,
        file_path: str,
        file_type: str,
        document_id: str,
        collection_name: str,
    ) -> IngestResult:
        # 1. Extract
        extractor = self.extractor_factory.get_extractor(file_type)
        extracted = await extractor.extract(file_path)

        # 2. Chunk
        chunks = self.chunker.chunk(extracted)

        # 3. Embed (배치)
        texts = [c.text for c in chunks]
        embeddings = []
        for batch in batched(texts, 32):
            batch_embeddings = await self.embedder.embed(batch)
            embeddings.extend(batch_embeddings)

        # 4. BM25 sparse vectors
        sparse_vectors = self.bm25_encoder.encode(texts)

        # 5. Milvus에 적재
        entities = []
        for chunk, embedding, sparse in zip(chunks, embeddings, sparse_vectors):
            entities.append({
                "id": f"{document_id}_{chunk.chunk_index}",
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "parent_text": chunk.metadata.get("parent_text", chunk.text),
                "embedding": embedding,
                "sparse_embedding": sparse,
                "metadata": chunk.metadata,
            })

        await self._batch_insert(collection_name, entities)

        return IngestResult(
            document_id=document_id,
            chunk_count=len(chunks),
            status="completed",
        )
```

---

## 체크리스트

- [ ] rag/extractors/base.py (BaseExtractor + ExtractedDocument)
- [ ] rag/extractors/pdf.py (pypdf + OCR 폴백)
- [ ] rag/extractors/docx.py
- [ ] rag/extractors/web.py
- [ ] rag/extractors/factory.py
- [ ] rag/chunkers/base.py (BaseChunker + Chunk)
- [ ] rag/chunkers/recursive.py
- [ ] rag/chunkers/parent_child.py
- [ ] rag/embeddings/base.py (BaseEmbedder)
- [ ] rag/embeddings/ollama.py (bge-m3)
- [ ] rag/embeddings/openai.py
- [ ] rag/vectorstore/schema.py (Milvus 컬렉션 스키마)
- [ ] rag/vectorstore/indexing.py (HNSW + Sparse 인덱스)
- [ ] rag/vectorstore/search.py (Hybrid Search + RRF)
- [ ] rag/vectorstore/milvus_client.py (클라이언트 래퍼)
- [ ] rag/retriever.py (검색 + Re-ranking + Parent 복원)
- [ ] rag/pipeline.py (인제스트 오케스트레이터)
- [ ] BM25Encoder (fit/encode/save/load)
