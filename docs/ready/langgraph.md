# LangGraph 핵심 개념

## LangGraph란?

- LangChain 팀이 만든 **상태 머신 기반 AI 에이전트 프레임워크**.
- 유향 그래프로 에이전트 워크플로우를 정의. 노드 = 처리 단계, 엣지 = 전이 조건.
- LangChain의 단선형 체인(A→B→C)의 한계를 극복하기 위해 등장.

## LangChain vs LangGraph

| 항목 | LangChain (LCEL) | LangGraph |
|---|---|---|
| 구조 | 선형 파이프라인 | 유향 그래프 (순환 가능) |
| 분기 | RunnableBranch (제한적) | Conditional Edge (자유로움) |
| 루프 | 어려움 | 네이티브 지원 |
| 상태 관리 | 없음 (각 단계가 독립) | AgentState로 전체 상태 공유 |
| 적합한 경우 | 단순 RAG, 프롬프트 체인 | 멀티스텝 에이전트, 반복 추론 |

## 핵심 구성 요소

### StateGraph

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(AgentState)
graph.add_node("analyze", analyze_fn)
graph.add_node("search", search_fn)
graph.add_edge("analyze", "search")
graph.add_edge("search", END)
app = graph.compile()
```

### State (상태)

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # 메시지 누적
    current_step: int
    tool_results: dict
    final_answer: str | None
```

- `Annotated[list, add_messages]`: reducer 함수. 노드가 반환하는 메시지를 기존 리스트에 append.
- **reducer가 없으면**: 노드의 반환값이 기존 값을 덮어씀.
- **reducer가 있으면**: 노드의 반환값을 기존 값과 합침 (append, merge 등).

### Node (노드)

```python
async def analyze(state: AgentState) -> dict:
    # state를 읽고, 처리하고, 변경할 필드만 반환
    result = await llm.invoke(state["messages"])
    return {"messages": [result], "current_step": state["current_step"] + 1}
```

- 노드는 함수 또는 Runnable.
- 입력: 현재 State. 출력: 변경할 State 필드의 dict.
- 반환하지 않은 필드는 그대로 유지됨.

### Edge (엣지)

```python
# 무조건 전이
graph.add_edge("analyze", "search")

# 조건부 전이
graph.add_conditional_edges(
    "analyze",                    # 출발 노드
    route_function,               # 조건 함수 (state → str)
    {
        "rag": "rag_search",      # 반환값 → 도착 노드 매핑
        "web": "web_search",
        "direct": "generate",
    }
)
```

- 조건 함수는 State를 받아서 문자열 키를 반환.
- 이 키가 매핑 dict에서 다음 노드를 결정.

## Tool Calling (Function Calling)

LLM이 도구를 선택하고 호출하는 패턴.

### 흐름
```
1. 사용자 질문 + 도구 목록(JSON Schema) → LLM에 전달
2. LLM이 "이 도구를 이 인자로 호출하라" 응답 (tool_call)
3. 해당 도구 실행 → 결과를 다시 LLM에 전달
4. LLM이 결과를 종합하여 최종 답변 생성
```

### JSON Schema 기반 도구 정의
```python
tools = [{
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "벡터 DB에서 관련 문서 검색",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색 쿼리"},
                "top_k": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    }
}]
```

## Checkpointing (체크포인팅)

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

# thread_id로 대화 상태 유지
config = {"configurable": {"thread_id": "user-123"}}
result = await app.ainvoke(input, config)
```

- 각 노드 실행 후 State를 저장.
- **Human-in-the-loop**: 특정 노드에서 멈추고 사용자 승인 후 재개.
- **대화 히스토리**: thread_id별로 State를 유지하여 멀티턴 대화 구현.

## 에러 핸들링 & 가드레일

### max_steps
```python
async def guardrails(state: AgentState) -> dict:
    if state["current_step"] >= state["max_steps"]:
        return {"final_answer": "최대 단계에 도달했습니다.", "is_sufficient": True}
    ...
```

### 무한 루프 방지
- 같은 도구를 같은 인자로 연속 호출하면 루프로 판단.
- step 카운터로 강제 종료.
- 비용 리밋: 총 토큰 소비량 제한.

## Streaming

```python
async for event in app.astream_events(input, config, version="v2"):
    if event["event"] == "on_chat_model_stream":
        print(event["data"]["chunk"].content, end="")
```

- 노드 단위 스트리밍: 각 노드의 중간 결과를 실시간으로 전달.
- LLM 토큰 단위 스트리밍: `astream_events`로 LLM 응답을 토큰 단위로 받기.
