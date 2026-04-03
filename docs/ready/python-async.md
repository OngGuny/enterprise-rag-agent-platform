# Python Async & 동시성 핵심 개념

## asyncio 기본

### 이벤트 루프
- 단일 스레드에서 여러 코루틴을 번갈아 실행하는 메커니즘.
- 코루틴이 I/O 대기(`await`)하면 다른 코루틴으로 전환 → 대기 시간 활용.

```python
async def fetch_data():
    response = await httpx.get("https://api.example.com")  # I/O 대기 중 다른 코루틴 실행
    return response.json()
```

### async/await의 의미
- `async def`: 코루틴 함수 정의.
- `await`: "여기서 양보(yield)할 수 있다"는 표시. I/O 대기 지점.
- `await` 없는 `async` 함수는 의미 없음 (동기 함수와 동일하게 동작).

## 동시성 vs 병렬성

| 구분 | 동시성 (Concurrency) | 병렬성 (Parallelism) |
|---|---|---|
| 정의 | 여러 작업을 번갈아 처리 | 여러 작업을 동시에 처리 |
| 구현 | asyncio, 스레드 | 멀티 프로세스 |
| GIL 영향 | 받음 | 안 받음 (프로세스 분리) |
| 적합한 작업 | I/O 바운드 | CPU 바운드 |

### GIL (Global Interpreter Lock)
- CPython의 뮤텍스. 한 번에 하나의 스레드만 Python 바이트코드 실행 가능.
- I/O 작업 중에는 GIL 해제 → 스레드도 I/O 바운드에는 유효.
- **CPU 바운드 작업에서 멀티스레딩은 무의미** → 멀티프로세싱 또는 Celery 사용.

## asyncio 패턴

### gather (병렬 실행)
```python
results = await asyncio.gather(
    fetch_from_milvus(query),
    fetch_from_redis(cache_key),
    fetch_from_db(doc_id),
)
# 세 작업이 동시에 실행, 모두 완료될 때까지 대기
```

### TaskGroup (Python 3.11+)
```python
async with asyncio.TaskGroup() as tg:
    task1 = tg.create_task(fetch_from_milvus(query))
    task2 = tg.create_task(fetch_from_redis(cache_key))
# 하나라도 예외 발생 시 나머지 자동 취소 (gather보다 안전)
results = [task1.result(), task2.result()]
```

### Semaphore (동시 실행 수 제한)
```python
sem = asyncio.Semaphore(10)  # 최대 10개 동시 실행

async def rate_limited_fetch(url):
    async with sem:
        return await httpx.get(url)

# 100개 URL을 동시에 요청하되, 동시 연결은 10개로 제한
await asyncio.gather(*[rate_limited_fetch(url) for url in urls])
```

## Context Manager (async)

```python
@asynccontextmanager
async def get_db_session():
    session = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
```

- `async with`로 리소스 생명주기 관리.
- DB 세션, HTTP 클라이언트, 파일 핸들 등에 활용.

## Generator & AsyncGenerator

```python
# 동기 제너레이터
def read_chunks(file):
    while chunk := file.read(1024):
        yield chunk

# 비동기 제너레이터 (SSE 스트리밍에 활용)
async def stream_llm_response(prompt: str):
    async for token in llm.astream(prompt):
        yield f"data: {token}\n\n"
```

- SSE 스트리밍 = FastAPI `StreamingResponse` + async generator.

## Type Hints (3.12)

```python
# 3.9+: 내장 타입 소문자 사용
list[str]           # not List[str]
dict[str, int]      # not Dict[str, int]
tuple[int, ...]     # not Tuple[int, ...]

# 3.10+: Union 대신 |
str | None          # not Optional[str]
int | str           # not Union[int, str]

# 3.12: type 문
type Vector = list[float]
type JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None
```

## 자주 쓰이는 패턴

### ABC (Abstract Base Class)
```python
from abc import ABC, abstractmethod

class BaseLLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str: ...

    @abstractmethod
    async def stream(self, prompt: str) -> AsyncGenerator[str, None]: ...
```

- 인터페이스 정의. 서브 클래스에서 반드시 구현해야 하는 메서드 강제.
- 이 프로젝트에서 Extractor, Chunker, Embedder, LLMClient 모두 이 패턴 사용.

### Protocol (구조적 서브타이핑)
```python
from typing import Protocol

class Searchable(Protocol):
    async def search(self, query: str, top_k: int) -> list[dict]: ...
```

- ABC와 달리 상속 없이도 메서드 시그니처만 맞으면 호환 (duck typing의 정적 버전).
