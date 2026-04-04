# 05. LLM 서빙: 모델 라우팅, 캐시, 스트리밍

## 목표

여러 LLM 백엔드(vLLM, Ollama, OpenAI)를 추상화하고, 질문 복잡도 기반 모델 라우팅, 시맨틱 캐시, SSE 스트리밍, 서킷 브레이커 기반 fallback을 구현한다.

---

## 5.1 LLM 클라이언트 추상화 (llm/base.py)

### BaseLLMClient 인터페이스

```python
@dataclass
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage            # prompt_tokens, completion_tokens, total_tokens
    latency_ms: float
    finish_reason: str           # stop, length, tool_calls

@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class BaseLLMClient(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """SSE 스트리밍용 토큰 단위 yield."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...
```

### OpenAIClient (llm/openai_client.py)

```python
class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, default_model: str = "gpt-4o-mini"):
        self._client = AsyncOpenAI(api_key=api_key)
        self.default_model = default_model

    async def generate(self, messages, *, model=None, **kwargs) -> LLMResponse:
        start = time.perf_counter()
        response = await self._client.chat.completions.create(
            model=model or self.default_model,
            messages=messages,
            **kwargs,
        )
        latency = (time.perf_counter() - start) * 1000

        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage=TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            ),
            latency_ms=latency,
            finish_reason=response.choices[0].finish_reason,
        )

    async def generate_stream(self, messages, *, model=None, **kwargs):
        stream = await self._client.chat.completions.create(
            model=model or self.default_model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
```

### OllamaClient (llm/ollama_client.py)

```python
class OllamaClient(BaseLLMClient):
    """Ollama HTTP API 기반 클라이언트."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def generate(self, messages, *, model="qwen3-8b", **kwargs) -> LLMResponse:
        response = await self._client.post(
            "/api/chat",
            json={"model": model, "messages": messages, "stream": False, **kwargs},
        )
        data = response.json()
        # Ollama 응답 → LLMResponse 변환
        ...

    async def generate_stream(self, messages, *, model="qwen3-8b", **kwargs):
        async with self._client.stream(
            "POST",
            "/api/chat",
            json={"model": model, "messages": messages, "stream": True},
        ) as response:
            async for line in response.aiter_lines():
                data = json.loads(line)
                if content := data.get("message", {}).get("content"):
                    yield content

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False
```

### vLLMClient (llm/vllm_client.py)

```python
class VLLMClient(BaseLLMClient):
    """
    vLLM은 OpenAI 호환 API를 제공하므로 OpenAI SDK 재사용.
    base_url만 vLLM 서버로 변경.
    """

    def __init__(self, base_url: str = "http://localhost:8001/v1"):
        self._client = AsyncOpenAI(
            api_key="EMPTY",       # vLLM은 API key 불필요
            base_url=base_url,
        )
```

---

## 5.2 모델 라우팅 (llm/router.py) ⭐

### 규칙 기반 + LLM 하이브리드 라우팅

```python
class ComplexityLevel(str, Enum):
    SIMPLE = "simple"       # 단순 사실 질문
    COMPLEX = "complex"     # 분석, 비교, 추론
    CODE = "code"           # 코드 생성/분석

class ModelRouter:
    def __init__(
        self,
        clients: dict[str, BaseLLMClient],       # {"openai": ..., "ollama": ...}
        circuit_breakers: dict[str, CircuitBreaker],
        model_mapping: dict[ComplexityLevel, list[ModelConfig]],
    ):
        ...

    async def route(self, query: str, context: dict | None = None) -> RoutingResult:
        # 1. 규칙 기반 Fast Path
        complexity = self._rule_based_classify(query)

        # 2. 규칙으로 판단 불가 → LLM classifier
        if complexity is None:
            complexity = await self._llm_classify(query)

        # 3. 복잡도에 따른 모델 선택 (서킷 브레이커 반영)
        model_config = await self._select_model(complexity)

        return RoutingResult(
            complexity=complexity,
            model=model_config.model_name,
            client_name=model_config.client_name,
        )

    def _rule_based_classify(self, query: str) -> ComplexityLevel | None:
        tokens = query.split()

        # 단순 질문 (짧은 사실 질문)
        if len(tokens) < 15 and not any(kw in query for kw in ["분석", "비교", "왜", "어떻게"]):
            return ComplexityLevel.SIMPLE

        # 코드 관련
        if any(kw in query for kw in ["코드", "함수", "구현", "```", "def ", "class "]):
            return ComplexityLevel.CODE

        # 분석/비교 키워드
        if any(kw in query for kw in ["분석", "비교", "요약", "평가", "전략"]):
            return ComplexityLevel.COMPLEX

        return None  # 판단 불가 → LLM classifier로 위임

    async def _select_model(self, complexity: ComplexityLevel) -> ModelConfig:
        """복잡도에 맞는 모델 중 서킷이 닫힌 첫 번째 모델 선택."""
        candidates = self.model_mapping[complexity]
        for model_config in candidates:
            cb = self.circuit_breakers.get(model_config.client_name)
            if cb is None or cb.state != CircuitState.OPEN:
                return model_config
        # 모든 서킷 열림 → 최후 fallback (OpenAI)
        return self.model_mapping[ComplexityLevel.SIMPLE][-1]
```

### 모델 매핑 설정

```python
model_mapping = {
    ComplexityLevel.SIMPLE: [
        ModelConfig(client="ollama", model="qwen3-8b"),
        ModelConfig(client="openai", model="gpt-4o-mini"),
    ],
    ComplexityLevel.COMPLEX: [
        ModelConfig(client="openai", model="gpt-4o"),
        ModelConfig(client="ollama", model="exaone-deep"),
    ],
    ComplexityLevel.CODE: [
        ModelConfig(client="ollama", model="codestral"),
        ModelConfig(client="openai", model="gpt-4o"),
    ],
}
```

### 프로덕션 포인트

- 규칙 기반으로 80%의 요청을 빠르게 분류, 나머지 20%만 LLM classifier 호출 → 비용 절약
- 서킷 브레이커 + Fallback 체인으로 특정 서비스 장애 시 자동 우회
- 라우팅 결정 로깅: 어떤 복잡도로 분류되어 어떤 모델이 선택됐는지 추적
- 비용 추정 메트릭: 모델별 토큰 단가 × 사용량으로 실시간 비용 모니터링

---

## 5.3 시맨틱 캐시 (llm/cache.py)

### 설계

```
Cache Miss Flow:
  Query → Embed → Redis에서 유사 임베딩 검색 → 없음 → LLM 호출 → 결과 캐시 저장

Cache Hit Flow:
  Query → Embed → Redis에서 유사 임베딩 검색 → 유사도 >= threshold → 캐시 응답 반환
```

### 구현

```python
class SemanticCache:
    def __init__(
        self,
        redis: Redis,
        embedder: BaseEmbedder,
        threshold: float = 0.92,    # 유사도 임계값
        ttl: int = 3600,            # 캐시 TTL (1시간)
        max_cache_size: int = 10000,
    ):
        ...

    async def get(self, query: str) -> CacheResult | None:
        query_embedding = await self.embedder.embed_query(query)

        # Redis에서 모든 캐시 임베딩 조회 (비효율 → 개선 방안 아래)
        cached_entries = await self._get_all_cache_entries()

        best_match = None
        best_similarity = 0.0

        for entry in cached_entries:
            similarity = cosine_similarity(query_embedding, entry.embedding)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = entry

        if best_match and best_similarity >= self.threshold:
            CACHE_HIT_RATE.labels(result="hit").inc()
            return CacheResult(answer=best_match.answer, similarity=best_similarity)

        CACHE_HIT_RATE.labels(result="miss").inc()
        return None

    async def set(self, query: str, answer: str, embedding: list[float]):
        cache_id = str(uuid4())
        pipe = self.redis.pipeline()
        pipe.set(f"cache:emb:{cache_id}", serialize_embedding(embedding), ex=self.ttl)
        pipe.set(f"cache:ans:{cache_id}", answer, ex=self.ttl)
        pipe.set(f"cache:query:{cache_id}", query, ex=self.ttl)
        await pipe.execute()
```

### 성능 개선 방안

- 현재: Redis keys 전체 스캔 → O(n) 비용
- 개선 1: Redis에 임베딩을 저장하되, 별도 Milvus "cache" 컬렉션에서 ANN 검색
- 개선 2: Redis Stack의 RediSearch 모듈 사용 (벡터 검색 지원)
- 개선 3: 인메모리 FAISS 인덱스로 빠른 유사도 검색 후 Redis에서 답변 조회

---

## 5.4 SSE 스트리밍 (llm/streaming.py)

### FastAPI SSE 엔드포인트

```python
from sse_starlette.sse import EventSourceResponse

async def stream_chat_response(
    query: str,
    context: list[str],
    llm_client: BaseLLMClient,
    model: str,
) -> EventSourceResponse:

    async def event_generator():
        messages = build_messages(query, context)
        full_response = []

        async for token in llm_client.generate_stream(messages, model=model):
            full_response.append(token)
            yield {
                "event": "token",
                "data": json.dumps({"content": token}),
            }

        # 스트림 완료 시 메타데이터 전송
        yield {
            "event": "done",
            "data": json.dumps({
                "model": model,
                "total_tokens": len("".join(full_response)),
            }),
        }

    return EventSourceResponse(event_generator())
```

### SSE 이벤트 프로토콜

```
event: token
data: {"content": "안녕"}

event: token
data: {"content": "하세요"}

event: sources
data: {"documents": [{"title": "...", "page": 3, "score": 0.95}]}

event: done
data: {"model": "gpt-4o-mini", "total_tokens": 128, "latency_ms": 1234}
```

### 프로덕션 포인트

- `sse-starlette` 패키지 사용 (FastAPI 공식 권장)
- `event` 타입 분리: `token` (본문), `sources` (참조 문서), `error`, `done`
- 클라이언트 연결 끊김 감지: `request.is_disconnected()` 체크로 불필요한 LLM 호출 중단
- Nginx SSE 프록시 설정: `proxy_buffering off; proxy_cache off;`
- heartbeat: 30초마다 빈 주석(`:heartbeat`) 전송으로 연결 유지

---

## 5.5 LLM 서비스 통합 (llm/__init__.py)

### LLMService 파사드

```python
class LLMService:
    """LLM 관련 기능의 통합 진입점."""

    def __init__(
        self,
        router: ModelRouter,
        cache: SemanticCache,
        clients: dict[str, BaseLLMClient],
    ):
        self.router = router
        self.cache = cache
        self.clients = clients

    async def chat(
        self,
        query: str,
        context: list[str] | None = None,
        stream: bool = True,
    ) -> LLMResponse | AsyncGenerator:
        # 1. 캐시 확인
        cached = await self.cache.get(query)
        if cached:
            if stream:
                return self._cached_stream(cached.answer)
            return LLMResponse(content=cached.answer, ...)

        # 2. 모델 라우팅
        routing = await self.router.route(query)

        # 3. LLM 호출
        client = self.clients[routing.client_name]
        messages = build_messages(query, context)

        if stream:
            return client.generate_stream(messages, model=routing.model)
        else:
            response = await client.generate(messages, model=routing.model)
            # 4. 캐시 저장
            await self.cache.set(query, response.content, ...)
            return response
```

---

## 체크리스트

- [ ] llm/base.py (BaseLLMClient, LLMResponse, TokenUsage)
- [ ] llm/openai_client.py (generate + stream)
- [ ] llm/ollama_client.py (generate + stream + health)
- [ ] llm/vllm_client.py (OpenAI 호환 래퍼)
- [ ] llm/router.py (규칙 + LLM 하이브리드 라우팅)
- [ ] llm/cache.py (시맨틱 캐시)
- [ ] llm/streaming.py (SSE 이벤트 생성)
- [ ] llm/service.py (LLMService 파사드)
- [ ] 모델 매핑 설정 (config 또는 별도 YAML)
- [ ] 서킷 브레이커 인스턴스 생성 + LLM 클라이언트 연동
