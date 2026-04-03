# LLM 서빙 핵심 개념

## vLLM

- UC Berkeley에서 개발한 고성능 LLM 추론 엔진.
- OpenAI API 호환 서버로 띄울 수 있음 → 코드 변경 없이 OpenAI SDK로 접근.

### PagedAttention

vLLM의 핵심 기술. GPU 메모리 관리 혁신.

- **문제**: Transformer의 KV Cache가 연속된 메모리 블록을 요구 → 메모리 단편화 + 낭비.
- **해결**: OS의 가상 메모리(페이징) 개념을 KV Cache에 적용.
  - KV Cache를 고정 크기 블록으로 나눔.
  - 블록은 비연속적인 GPU 메모리에 배치 가능.
  - 필요할 때만 할당, 끝나면 즉시 해제.
- **효과**: 메모리 낭비 60~80% 감소 → 동시 처리 배치 크기 2~4배 증가.

### Continuous Batching

- **Static Batching**: 배치 내 모든 요청이 완료될 때까지 대기. 짧은 응답이 긴 응답에 묶임.
- **Continuous Batching**: 요청이 완료되면 즉시 빠지고, 새 요청이 바로 들어옴.
  - 처리량(throughput) 2~10배 향상.
  - 응답 지연(latency) 감소.

### 스펙큘레이티브 디코딩 (Speculative Decoding)

- 작은 모델(draft)이 여러 토큰을 한번에 예측 → 큰 모델(target)이 검증.
- 맞으면 한번에 여러 토큰 확정 → 추론 속도 향상.
- 품질은 큰 모델과 동일 (거부 샘플링으로 보장).

## Ollama

- 로컬 LLM 실행을 간편하게 만든 도구. Docker처럼 모델을 pull/run.
- REST API 제공 (`/api/generate`, `/api/chat`, `/api/embed`).
- **장점**: 설치/사용이 매우 간단, 모델 관리 편리.
- **단점**: 프로덕션 처리량에서는 vLLM 대비 열위 (continuous batching 없음).

### Ollama vs vLLM

| 항목 | Ollama | vLLM |
|---|---|---|
| 설치 | `curl -fsSL ollama.com | sh` | pip + CUDA 의존성 |
| API | 자체 API + OpenAI 호환 | OpenAI 호환 |
| Batching | 기본 sequential | Continuous Batching |
| 메모리 관리 | 기본 | PagedAttention |
| 양자화 | GGUF (llama.cpp) | AWQ, GPTQ, FP8 |
| 적합한 경우 | 개발, 프로토타입, 소규모 | 프로덕션, 고처리량 |

## 모델 라우팅

질문 복잡도에 따라 적절한 모델을 선택하여 비용과 품질의 균형을 맞추는 전략.

### 라우팅 로직
```
단순 사실 질문 ("서울 인구는?")  → small 모델 (qwen3-8b, gpt-4o-mini)
복잡한 분석 ("비교해줘", "분석해줘")  → large 모델 (gpt-4o)
코드 생성  → code 모델 (codestral)
임베딩  → embedding 모델 (bge-m3)
```

### 복잡도 판단 방식
1. **규칙 기반 (Fast Path)**: 토큰 수, 키워드 매칭으로 빠르게 분류.
2. **LLM 분류기 (Slow Path)**: 규칙으로 판단 불가 시 mini 모델이 복잡도 분류.
3. **하이브리드**: 규칙 → LLM 순서로 cascading. 대부분 규칙에서 분류되므로 비용 절약.

## 서킷 브레이커 (Circuit Breaker)

외부 서비스 장애 전파를 방지하는 패턴.

### 3가지 상태
```
CLOSED (정상) → 실패율 임계치 초과 → OPEN (차단)
OPEN → 일정 시간 경과 → HALF_OPEN (시험)
HALF_OPEN → 성공 → CLOSED / 실패 → OPEN
```

- **CLOSED**: 정상 동작. 실패 횟수 카운트.
- **OPEN**: 요청을 즉시 실패 처리 (fallback). 대기 시간 동안 실제 요청을 보내지 않음.
- **HALF_OPEN**: 제한된 요청만 통과시켜 복구 여부 확인.

### 이 프로젝트에서의 적용
```
vLLM 다운 → 서킷 OPEN → Ollama fallback
Ollama도 다운 → OpenAI API fallback
```

## 시맨틱 캐싱

동일한 질문뿐 아니라 **의미적으로 유사한 질문**에도 캐시를 적용.

### 기존 캐시 vs 시맨틱 캐시
- 기존: `hash("서울 인구") == hash("서울 인구")` → 완전 일치만 히트.
- 시맨틱: `cosine_sim(embed("서울 인구"), embed("서울의 인구수는?")) = 0.96` → 히트.

### 트레이드오프
- **장점**: 캐시 히트율 대폭 증가. LLM 호출 비용/지연 절약.
- **단점**: 임베딩 생성 비용, 유사도 검색 비용, threshold 튜닝 필요.
- **위험**: threshold가 낮으면 다른 질문에 잘못된 답변을 반환할 수 있음.

## 토큰과 비용

### 토큰이란?
- LLM이 텍스트를 처리하는 단위. 대략 영어 4글자, 한국어 1~2글자 = 1 토큰.
- `"Enterprise RAG Platform"` → 약 3 토큰.
- `"엔터프라이즈 RAG 플랫폼"` → 약 8~10 토큰 (한국어가 더 많은 토큰 소모).

### 비용 최적화 전략
1. **모델 라우팅**: 싼 모델로 처리 가능한 건 싼 모델로.
2. **시맨틱 캐싱**: 유사 질문 캐시 히트로 호출 자체를 줄임.
3. **프롬프트 최적화**: 불필요한 컨텍스트 줄이기, 시스템 프롬프트 간결화.
4. **배치 처리**: 임베딩은 개별 호출보다 배치가 효율적.
