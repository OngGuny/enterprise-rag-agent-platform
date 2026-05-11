# ADR-001: 벡터 DB로 Milvus 채택 (vs pgvector)

- **상태**: 채택
- **작성일**: 2026-05-06
- **관련 모듈**: `src/core/milvus.py`, `src/rag/vectorstore/`(예정), `docker-compose.yml`

## 맥락

Enterprise RAG Agent Platform 은 기업 문서를 인제스트해 임베딩하고, 사용자 질의에 대해 의미 기반 검색(semantic search) + 메타데이터 필터링 + 향후 하이브리드(BM25 + dense) 검색을 제공해야 한다.

핵심 제약은 다음과 같다.

- **임베딩 차원**: BGE-M3 기준 1,024차원, OpenAI `text-embedding-3-small` 1,536차원. 두 모델을 동시에 운영할 가능성이 있고, 모델 교체 시 재인덱싱이 발생한다.
- **데이터 규모**: MVP 기준 10만~100만 청크, 운영 1년차 목표 1,000만 청크 이상. 파일 한 건당 평균 200~500 청크를 가정.
- **검색 패턴**: top-k 의미 검색 + 테넌트/문서타입/생성일 같은 메타데이터 필터 + 향후 BM25 + dense 하이브리드. 재정렬(reranker)은 별도 단계로 둔다.
- **운영**: Docker Compose 로 단일 노드 시작, 추후 Kubernetes 로 확장. 한국 기업 환경 — SaaS 의존을 줄이고 자가 운영 가능해야 한다.
- **팀 경험**: PostgreSQL 운영 경험은 풍부하나, Milvus 는 신규 도입.

## 선택지

### A) PostgreSQL + pgvector
- **장점**:
  - 단일 DB. 트랜잭션·관계·벡터를 한 곳에서 관리 → 운영 단순.
  - 기존 PostgreSQL 운영 경험을 그대로 활용. 백업/모니터링/권한 체계 재사용.
  - HNSW(0.5+) / IVFFlat 인덱스 지원, 0.7부터 양자화도 옵션화.
  - `WHERE` 절로 메타데이터 필터링이 자연스럽다.
- **단점**:
  - 수천만 벡터 수준에서 인덱스 빌드 시간과 메모리 사용량이 빠르게 증가. 큰 코퍼스에서 ANN 정확도/지연 트레이드오프가 거칠다.
  - 다중 모델(다중 차원) 컬렉션 관리가 어색하다 — 차원이 다르면 사실상 별 테이블.
  - 하이브리드 검색을 직접 구현해야 한다 (BM25 + 벡터 결합 RRF/가중합 SQL 으로). 운영 표준이 없다.
  - 인덱스 리빌드/재인덱싱 시 메인 DB 의 IO 와 경쟁 → 운영 영향이 크다.

### B) Milvus (스탠드얼론 / 클러스터)
- **장점**:
  - 벡터 검색 전용 설계. 1억+ 벡터 규모에서도 검증된 ANN(HNSW, IVF, DiskANN) 옵션.
  - **하이브리드 검색**(`hybrid_search` API, sparse + dense, RRF/weighted) 이 1급 시민. BM25/sparse 와 dense 를 같은 쿼리로.
  - 다중 컬렉션 / 다중 차원 / 다중 모델을 자연스럽게 표현. 모델 교체나 A/B 가 깔끔.
  - 메타데이터 필터링도 표현식 기반(`expr=`) 으로 풍부하게 지원.
  - PyMilvus 클라이언트, Milvus 2.4 의 `MilvusClient` 단순화 API 가 있어 학습 곡선이 낮아짐.
- **단점**:
  - 운영 컴포넌트가 늘어난다 (etcd, MinIO/S3, Pulsar/Kafka — Milvus 2.4 standalone 은 단일 컨테이너로 묶여 있음).
  - 트랜잭션이 RDB 만큼 강하지 않다. 메타데이터의 정합성은 PostgreSQL 측에서 별도로 보증해야 한다.
  - 팀에 새로운 학습 곡선과 새로운 모니터링 대상이 생긴다.

### C) Elasticsearch / OpenSearch (dense + BM25)
- **장점**: BM25 가 1급, 벡터도 점차 1급. 운영 친숙도 중간.
- **단점**: 대규모 dense 검색에서 Milvus 만큼의 ANN 성숙도/효율을 내기 어렵고, 클러스터 운영 비용이 가장 무겁다.

### D) Managed (Pinecone / Weaviate Cloud / Qdrant Cloud)
- **장점**: 운영 부담 0.
- **단점**: 데이터 주권/온프렘 요구가 있는 한국 엔터프라이즈 시나리오에 부적합. 비용이 트래픽에 선형적.

## 결정

**Milvus 2.4 (standalone) 채택**, 단일 컨테이너로 시작해 추후 클러스터로 확장한다. 메타데이터의 권위 있는 출처(Source of Truth)는 PostgreSQL 에 두고, Milvus 는 검색 인덱스 역할로 한정한다.

## 근거

1. **하이브리드 검색이 1급 시민**. RAG 품질에서 sparse(BM25) + dense 결합은 거의 표준이 되었고, pgvector 로 동일 기능을 달성하려면 SQL 글루 코드를 직접 짜야 한다. Milvus 의 `hybrid_search` 는 운영 표준 경로다.
2. **확장 한계의 위치가 다르다**. pgvector 는 운영 1년차 목표(1천만 청크 이상)에서 인덱스 리빌드 비용이 메인 OLTP DB 의 부하와 경쟁한다. 검색 워크로드를 OLTP 와 분리하는 것이 운영상 안전하다.
3. **다중 모델/다중 차원 표현이 자연스럽다**. BGE-M3(1024) 와 OpenAI(1536) 를 동시에, 또는 모델 교체 A/B 를 하려면 컬렉션 단위 분리가 깔끔하다.
4. **운영 부담은 통제 가능**. Milvus 2.4 standalone + `MilvusClient` 의 단순화 API 로 진입 비용이 줄었고, 본 프로젝트는 이미 다중 인프라(Postgres + Redis + Celery + Milvus + Ollama) 를 Compose 로 묶고 있어 컴포넌트 1개 추가의 한계 비용은 작다.
5. **데이터 주권**. 온프렘/자가운영 요구가 있는 엔터프라이즈 시나리오에서 매니지드는 후순위.

핵심 트레이드오프는 운영 컴포넌트 1개 증가 ↔ 하이브리드 검색·확장성·다중 모델 표현력의 획득이다. 이 프로젝트의 도메인(엔터프라이즈 RAG, 다중 LLM/임베딩 라우팅) 에서 후자의 가치가 명백히 크다고 판단했다.

## 결과

- `src/core/milvus.py` 에 `MilvusManager` 싱글톤(ADR-003 참조) 으로 클라이언트를 lifespan 에 묶었다.
- `docker-compose.yml` 에 Milvus 가 별도 서비스로 들어가고, etcd / MinIO 의존을 함께 관리한다.
- 메타데이터 정합성은 **PostgreSQL 이 권위**, Milvus 는 검색 인덱스. 문서 삭제/업데이트 시 두 저장소를 양쪽으로 갱신하는 책임은 인제스트 워커(Phase 4 / Phase 7) 가 진다.
- Phase 1 readiness 체크에서 Milvus 연결을 검증하되, 부팅 시 Milvus 가 일시적으로 떠 있지 않아도 앱은 살아 있게 한다 (`src/main.py` 의 lifespan 에서 `MilvusManager.connect` 실패를 warning 으로 흡수). 검색 기능 자체는 ready 가 아닐 때 503.
- 모니터링: 향후 Milvus 메트릭(쿼리 지연, 컬렉션 크기, 컴팩션 상태) 을 Prometheus 로 수집한다 (Phase 8).
- 위험: 운영 노하우 부족. 첫 사고는 컴팩션/메모리 관련일 가능성이 높다 — 컬렉션 크기와 segment 수 알람을 일찍 잡아둘 것.

## 참고

- 관련 ADR: ADR-003 (외부 서비스 매니저 싱글톤)
- [Milvus 2.4 Hybrid Search 문서](https://milvus.io/docs/multi-vector-search.md)
- [pgvector 0.7 Release Notes](https://github.com/pgvector/pgvector/releases)
