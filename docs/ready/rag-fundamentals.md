# RAG 핵심 개념

## RAG란? (Retrieval-Augmented Generation)

- LLM에 **외부 지식을 검색하여 주입**한 뒤 답변을 생성하는 패턴.
- LLM의 한계를 보완:
  - **할루시네이션 감소**: 근거 문서를 제공하여 사실 기반 답변 유도.
  - **최신 정보 반영**: 학습 데이터 cutoff 이후 정보도 검색으로 제공.
  - **도메인 특화**: 기업 내부 문서를 검색 소스로 활용.

### RAG 파이프라인 흐름
```
질문 → 임베딩 → 벡터 검색 → 관련 문서 top-k 추출 → LLM에 컨텍스트로 전달 → 답변 생성
```

## 임베딩 (Embedding)

텍스트를 고차원 벡터 공간의 점으로 변환. 의미가 유사한 텍스트는 가까운 벡터.

### 주요 임베딩 모델

| 모델 | 차원 | 특징 |
|---|---|---|
| OpenAI text-embedding-3-small | 1536 | API 기반, 편리, 유료 |
| OpenAI text-embedding-3-large | 3072 | 더 높은 정확도 |
| BGE-M3 (BAAI) | 1024 | 오픈소스, 다국어, dense+sparse 동시 생성 |
| E5-mistral-7b | 4096 | LLM 기반 임베딩, 높은 정확도 |

### BGE-M3의 장점
- **Multi-Functionality**: Dense, Sparse, ColBERT 임베딩을 한번에 생성.
- **Multi-Linguality**: 100+ 언어 지원. 한국어 성능 우수.
- **Multi-Granularity**: 최대 8192 토큰. 긴 문서도 처리.

## 청킹 (Chunking)

문서를 검색 단위로 나누는 작업. RAG 성능에 직접적 영향.

### 청킹 전략 비교

| 전략 | 방식 | 장점 | 단점 |
|---|---|---|---|
| Fixed Size | 고정 글자/토큰 수로 분할 | 구현 간단, 예측 가능 | 문맥 단절 |
| Recursive | 구분자 우선순위로 재귀 분할 | 문단/문장 경계 존중 | 크기 불균일 |
| Semantic | 임베딩 유사도 기반 분할 | 의미 단위 보존 | 느림, 비용 |
| Parent-Child | 큰 단위(parent) + 작은 단위(child) | 검색 정확도 + 충분한 컨텍스트 | 구현 복잡 |

### Parent-Child 청킹 상세

```
원본 문서
├── Parent Chunk (512 토큰) ← 컨텍스트 제공용
│   ├── Child Chunk (128 토큰) ← 검색용
│   ├── Child Chunk (128 토큰)
│   └── Child Chunk (128 토큰)
├── Parent Chunk (512 토큰)
│   ├── Child Chunk (128 토큰)
│   └── ...
```

- **검색은 child로**: 작은 단위라 검색 정확도 높음.
- **컨텍스트는 parent로**: child가 히트하면 해당 parent 텍스트를 LLM에 전달. 충분한 맥락 제공.
- **왜 필요한가?**: 큰 청크로 검색하면 노이즈가 많고, 작은 청크로만 보내면 맥락이 부족. 둘의 장점을 결합.

### Overlap (오버랩)

- 인접 청크 간 겹치는 영역. 보통 청크 크기의 10~20%.
- **왜 필요한가?**: 청크 경계에서 문맥이 잘릴 수 있음. 오버랩으로 경계 정보 보존.

## Re-ranking

벡터 검색 결과를 더 정밀한 모델로 재정렬.

### 왜 필요한가?
- Bi-encoder (임베딩 모델): 질문과 문서를 각각 독립적으로 임베딩. 빠르지만 정밀도 한계.
- Cross-encoder (Re-ranker): 질문과 문서를 함께 입력하여 관련도 점수 계산. 느리지만 정확.

### 파이프라인
```
질문 → Bi-encoder로 top-20 검색 (빠름)
     → Cross-encoder로 top-20 재정렬 (정확)
     → top-5 선정 → LLM에 전달
```

### 주요 Re-ranker 모델
- **Cohere Rerank**: API 기반, 다국어 지원.
- **BGE Reranker v2**: 오픈소스, BAAI.
- **Cross-encoder/ms-marco**: Sentence Transformers 기반.

## 문서 추출 (Extraction)

### PDF 추출의 어려움
- **텍스트 기반 PDF**: `pypdf`로 직접 추출. 빠르고 정확.
- **스캔 PDF (이미지)**: OCR 필요. Tesseract, EasyOCR.
- **혼합 PDF**: 텍스트 추출 시도 → 텍스트가 부족하면 OCR 폴백.
- **표(Table)**: 일반 텍스트 추출로는 구조가 깨짐. Camelot, Tabula, 또는 Vision LLM 활용.

### Vision LLM 활용
- 이미지, 차트, 복잡한 레이아웃 → Vision 모델(GPT-4V 등)로 텍스트 설명 생성.
- 비용이 높지만, 기존 OCR로 처리 불가능한 경우 유용.

## 평가 지표

### Retrieval 평가
| 지표 | 설명 |
|---|---|
| **Recall@k** | 관련 문서 중 top-k에 포함된 비율 |
| **MRR** (Mean Reciprocal Rank) | 첫 번째 관련 문서의 순위 역수 평균 |
| **NDCG** | 순위 가중 관련도 점수 |

### Generation 평가
| 지표 | 설명 |
|---|---|
| **Faithfulness** | 답변이 제공된 컨텍스트에 기반하는가 (할루시네이션 체크) |
| **Answer Relevancy** | 답변이 질문에 적절한가 |
| **Context Precision** | 검색된 문서 중 실제 관련 문서 비율 |

- **RAGAS**: RAG 파이프라인 자동 평가 프레임워크. 위 지표들을 자동 측정.
