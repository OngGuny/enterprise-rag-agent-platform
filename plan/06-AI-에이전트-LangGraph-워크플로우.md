# 06. AI 에이전트: LangGraph 워크플로우

## 목표

LangGraph 기반 상태 머신으로 멀티스텝 에이전트를 구현한다. 질문 분석 → 도구 선택 → 실행 → 답변 생성 → 품질 검증의 루프를 지원하며, Tool Calling, 가드레일, 실행 로깅을 포함한다.

---

## 6.1 AgentState 정의 (agent/state.py)

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # 대화 메시지 (LangGraph의 add_messages reducer)
    messages: Annotated[list, add_messages]

    # 질문 분석 결과
    query: str
    intent: str | None                    # rag, web, sql, direct
    complexity: str | None                # simple, complex, code
    required_tools: list[str]             # 필요한 도구 목록

    # 실행 추적
    current_step: int                     # 현재 스텝 번호
    max_steps: int                        # 최대 스텝 (가드레일)
    tool_results: dict[str, Any]          # 도구 실행 결과
    tool_call_history: list[dict]         # 도구 호출 이력 (무한루프 감지용)

    # RAG 컨텍스트
    retrieved_context: list[dict] | None  # 검색된 문서 조각
    collection_name: str | None

    # 최종 결과
    final_answer: str | None
    is_sufficient: bool                   # 답변 충분성 (guardrails 판단)
    confidence_score: float | None

    # 메타
    execution_id: str                     # 실행 세션 ID (로깅용)
    error: str | None
```

---

## 6.2 그래프 구성 (agent/graph.py)

### 노드와 엣지

```
[START]
   │
   ▼
[query_analyzer] ──(conditional)──┬── "rag"    → [rag_search]
                                  ├── "web"    → [web_search]
                                  ├── "sql"    → [sql_executor]
                                  └── "direct" → [answer_generator]
                                        │
[rag_search] ──────────────────────────►│
[web_search] ──────────────────────────►│
[sql_executor] ────────────────────────►│
                                        │
                                        ▼
                                [answer_generator]
                                        │
                                        ▼
                                [guardrails] ──┬── sufficient → [END]
                                               └── insufficient → [query_analyzer] (재시도)
```

### 구현

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

def build_agent_graph() -> CompiledGraph:
    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node("query_analyzer", query_analyzer_node)
    graph.add_node("rag_search", rag_search_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("sql_executor", sql_executor_node)
    graph.add_node("answer_generator", answer_generator_node)
    graph.add_node("guardrails", guardrails_node)

    # 진입점
    graph.set_entry_point("query_analyzer")

    # 조건부 엣지: 분석 결과에 따라 도구 선택
    graph.add_conditional_edges(
        "query_analyzer",
        route_by_intent,
        {
            "rag": "rag_search",
            "web": "web_search",
            "sql": "sql_executor",
            "direct": "answer_generator",
        },
    )

    # 도구 → 답변 생성
    graph.add_edge("rag_search", "answer_generator")
    graph.add_edge("web_search", "answer_generator")
    graph.add_edge("sql_executor", "answer_generator")

    # 답변 → 가드레일
    graph.add_edge("answer_generator", "guardrails")

    # 가드레일 → 종료 or 재시도
    graph.add_conditional_edges(
        "guardrails",
        check_sufficiency,
        {
            "end": END,
            "retry": "query_analyzer",
        },
    )

    # 체크포인트 (대화 히스토리 유지)
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
```

---

## 6.3 노드 구현 (agent/nodes/)

### query_analyzer (질문 분석)

```python
async def query_analyzer_node(state: AgentState) -> dict:
    """사용자 질문을 분석하여 의도와 필요한 도구를 판단."""

    query = state["query"]
    step = state["current_step"] + 1

    # 가드레일: 최대 스텝 초과 시 강제 direct
    if step > state["max_steps"]:
        return {
            "intent": "direct",
            "required_tools": [],
            "current_step": step,
            "error": "max_steps_exceeded",
        }

    # LLM에게 질문 분석 요청
    analysis_prompt = """
    사용자 질문을 분석하여 JSON으로 응답하세요:
    {
        "intent": "rag" | "web" | "sql" | "direct",
        "reasoning": "왜 이 의도로 분류했는지",
        "required_tools": ["tool1", "tool2"],
        "sub_queries": ["세부 질문1", "세부 질문2"]
    }

    질문: {query}
    이전 도구 결과: {tool_results}
    """

    response = await llm_client.generate(
        messages=[{"role": "user", "content": analysis_prompt.format(...)}],
        temperature=0.0,  # 분석은 deterministic하게
    )

    analysis = parse_json_response(response.content)

    return {
        "intent": analysis["intent"],
        "required_tools": analysis.get("required_tools", []),
        "current_step": step,
    }
```

### router (라우팅 함수)

```python
def route_by_intent(state: AgentState) -> str:
    """query_analyzer의 결과로 다음 노드 결정."""
    intent = state.get("intent", "direct")

    # 무한루프 방지: 동일 도구 3회 연속 호출 시 direct로 전환
    history = state.get("tool_call_history", [])
    if len(history) >= 3:
        last_three = [h["tool"] for h in history[-3:]]
        if len(set(last_three)) == 1:
            logger.warning("infinite_loop_detected", tool=last_three[0])
            return "direct"

    return intent
```

### rag_search (RAG 검색)

```python
async def rag_search_node(state: AgentState) -> dict:
    """Milvus에서 관련 문서를 검색."""

    query = state["query"]
    collection = state.get("collection_name", "default")

    results = await retriever.retrieve(
        query=query,
        collection_name=collection,
        top_k=5,
    )

    return {
        "tool_results": {
            **state.get("tool_results", {}),
            "rag_results": [
                {"text": r.text, "score": r.score, "metadata": r.metadata}
                for r in results
            ],
        },
        "retrieved_context": [{"text": r.text, "score": r.score} for r in results],
        "tool_call_history": [
            *state.get("tool_call_history", []),
            {"tool": "rag_search", "query": query, "result_count": len(results)},
        ],
    }
```

### web_search (웹 검색)

```python
async def web_search_node(state: AgentState) -> dict:
    """외부 웹 검색 (Tavily API 또는 DuckDuckGo)."""

    query = state["query"]

    # Tavily API 호출
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": 5, "search_depth": "advanced"},
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
        )

    results = response.json().get("results", [])

    return {
        "tool_results": {
            **state.get("tool_results", {}),
            "web_results": [
                {"title": r["title"], "content": r["content"], "url": r["url"]}
                for r in results
            ],
        },
        "tool_call_history": [
            *state.get("tool_call_history", []),
            {"tool": "web_search", "query": query, "result_count": len(results)},
        ],
    }
```

### sql_executor (SQL 실행)

```python
async def sql_executor_node(state: AgentState) -> dict:
    """
    LLM이 생성한 SQL을 안전하게 실행.
    READ-ONLY 쿼리만 허용 (SELECT).
    """

    query = state["query"]

    # LLM에게 SQL 생성 요청 (스키마 정보 포함)
    sql_prompt = f"""
    다음 질문에 답하기 위한 SQL 쿼리를 작성하세요.
    SELECT 문만 허용됩니다.

    질문: {query}
    스키마: {db_schema_info}
    """

    response = await llm_client.generate(
        messages=[{"role": "user", "content": sql_prompt}],
    )

    sql = extract_sql(response.content)

    # 안전성 검증
    if not is_safe_sql(sql):
        return {"error": "unsafe_sql_rejected", "tool_results": {...}}

    # 실행 (READ-ONLY 연결)
    result = await execute_readonly_query(sql)

    return {
        "tool_results": {
            **state.get("tool_results", {}),
            "sql_results": {"query": sql, "rows": result[:100], "row_count": len(result)},
        },
        "tool_call_history": [...],
    }

def is_safe_sql(sql: str) -> bool:
    """SQL 안전성 검증. DML/DDL 차단."""
    dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
    sql_upper = sql.upper().strip()
    return sql_upper.startswith("SELECT") and not any(d in sql_upper for d in dangerous)
```

### answer_generator (답변 생성)

```python
async def answer_generator_node(state: AgentState) -> dict:
    """도구 결과를 종합하여 최종 답변 생성."""

    query = state["query"]
    tool_results = state.get("tool_results", {})

    # 컨텍스트 구성
    context_parts = []
    if rag := tool_results.get("rag_results"):
        context_parts.append("## 문서 검색 결과\n" + format_rag_results(rag))
    if web := tool_results.get("web_results"):
        context_parts.append("## 웹 검색 결과\n" + format_web_results(web))
    if sql := tool_results.get("sql_results"):
        context_parts.append("## 데이터 조회 결과\n" + format_sql_results(sql))

    system_prompt = """
    당신은 기업 AI 어시스턴트입니다.
    제공된 컨텍스트를 기반으로 질문에 답변하세요.
    컨텍스트에 없는 정보는 추측하지 마세요.
    출처를 명시하세요.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"컨텍스트:\n{chr(10).join(context_parts)}\n\n질문: {query}"},
    ]

    response = await llm_client.generate(messages=messages)

    return {
        "final_answer": response.content,
        "messages": [{"role": "assistant", "content": response.content}],
    }
```

### guardrails (품질 검증)

```python
async def guardrails_node(state: AgentState) -> dict:
    """답변 품질을 검증하고, 부족하면 재시도를 트리거."""

    answer = state.get("final_answer", "")
    query = state["query"]
    step = state["current_step"]

    # 1. 최대 스텝 초과 → 강제 종료
    if step >= state["max_steps"]:
        return {"is_sufficient": True, "error": "forced_stop_max_steps"}

    # 2. 답변 길이 체크
    if len(answer.strip()) < 50:
        return {"is_sufficient": False}

    # 3. LLM 기반 품질 평가 (선택적)
    eval_prompt = f"""
    질문: {query}
    답변: {answer}

    이 답변이 질문에 충분히 답하고 있습니까?
    JSON으로 응답: {{"sufficient": true/false, "reason": "...", "confidence": 0.0-1.0}}
    """

    eval_response = await llm_client.generate(
        messages=[{"role": "user", "content": eval_prompt}],
        model="gpt-4o-mini",  # 평가는 가벼운 모델로
    )

    evaluation = parse_json_response(eval_response.content)

    return {
        "is_sufficient": evaluation.get("sufficient", True),
        "confidence_score": evaluation.get("confidence", 0.5),
    }

def check_sufficiency(state: AgentState) -> str:
    if state.get("is_sufficient", False):
        return "end"
    return "retry"
```

---

## 6.4 Tool Calling 인터페이스 (agent/tools/)

### BaseTool + Registry

```python
class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    def get_schema(self) -> dict:
        """OpenAI Function Calling 형식의 JSON Schema."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> dict:
        ...

class ToolRegistry:
    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool):
        cls._tools[tool.name] = tool

    @classmethod
    def get_all_schemas(cls) -> list[dict]:
        return [tool.get_schema() for tool in cls._tools.values()]

    @classmethod
    async def execute(cls, tool_name: str, **kwargs) -> dict:
        tool = cls._tools.get(tool_name)
        if not tool:
            raise ToolNotFoundError(tool_name)
        return await tool.execute(**kwargs)
```

---

## 6.5 대화 메모리 (agent/memory.py)

### Short-term + Long-term

```python
class ConversationMemory:
    def __init__(self, redis: Redis, max_history: int = 20):
        self.redis = redis
        self.max_history = max_history

    async def get_history(self, session_id: str) -> list[dict]:
        """Redis에서 최근 N개 대화 조회."""
        messages = await self.redis.lrange(f"chat:{session_id}", 0, self.max_history - 1)
        return [json.loads(m) for m in messages]

    async def add_message(self, session_id: str, role: str, content: str):
        key = f"chat:{session_id}"
        message = json.dumps({"role": role, "content": content, "timestamp": datetime.now().isoformat()})
        await self.redis.lpush(key, message)
        await self.redis.ltrim(key, 0, self.max_history - 1)
        await self.redis.expire(key, 86400)  # 24시간 TTL

    async def summarize_and_compress(self, session_id: str):
        """대화가 길어지면 앞부분을 LLM으로 요약하여 압축."""
        history = await self.get_history(session_id)
        if len(history) < self.max_history:
            return

        # 앞쪽 절반을 요약
        to_summarize = history[len(history)//2:]
        summary = await llm_client.generate(
            messages=[{"role": "user", "content": f"다음 대화를 요약하세요:\n{format_messages(to_summarize)}"}],
        )

        # 요약본으로 교체
        await self.redis.delete(f"chat:{session_id}")
        await self.add_message(session_id, "system", f"[이전 대화 요약] {summary.content}")
        for msg in history[:len(history)//2]:
            await self.add_message(session_id, msg["role"], msg["content"])
```

---

## 6.6 에이전트 실행 로깅

### 각 노드에서 자동 로깅

```python
def with_logging(node_name: str):
    """노드 실행을 자동으로 로깅하는 데코레이터."""
    def decorator(func):
        async def wrapper(state: AgentState) -> dict:
            start = time.perf_counter()
            try:
                result = await func(state)
                duration = (time.perf_counter() - start) * 1000

                await log_agent_step(
                    execution_id=state["execution_id"],
                    step=state["current_step"],
                    node=node_name,
                    input_data={"query": state["query"]},
                    output_data=result,
                    duration_ms=duration,
                )
                return result
            except Exception as e:
                await log_agent_step(
                    execution_id=state["execution_id"],
                    step=state["current_step"],
                    node=node_name,
                    error=str(e),
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
                raise
        return wrapper
    return decorator
```

---

## 체크리스트

- [ ] agent/state.py (AgentState TypedDict)
- [ ] agent/graph.py (StateGraph 구성 + compile)
- [ ] agent/nodes/query_analyzer.py
- [ ] agent/nodes/router.py (라우팅 함수)
- [ ] agent/nodes/rag_search.py
- [ ] agent/nodes/web_search.py
- [ ] agent/nodes/sql_executor.py (안전성 검증 포함)
- [ ] agent/nodes/answer_generator.py
- [ ] agent/nodes/guardrails.py (품질 검증 + 재시도)
- [ ] agent/tools/base.py (BaseTool)
- [ ] agent/tools/registry.py (ToolRegistry)
- [ ] agent/tools/definitions.py (Function Calling 스키마)
- [ ] agent/memory.py (Redis 기반 대화 메모리)
- [ ] 에이전트 실행 로깅 데코레이터
- [ ] api/endpoints/agents.py (에이전트 실행 API)
