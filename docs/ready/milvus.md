# Milvus 핵심 개념

## Milvus란?

- 오픈소스 벡터 데이터베이스. 대규모 벡터 유사도 검색에 특화.
- 수십억 건의 벡터를 밀리초 단위로 검색 가능.
- Cloud-native 설계: 컴퓨팅(Query Node)과 스토리지(Data Node)를 분리하여 독립 스케일링.

## Milvus vs pgvector

| 항목 | Milvus | pgvector |
|---|---|---|
| **설계 목적** | 벡터 검색 전용 | PostgreSQL 확장 |
| **인덱스** | HNSW, IVF_FLAT, IVF_PQ, DiskANN, SCANN | IVFFlat, HNSW |
| **Hybrid Search** | 네이티브 지원 (dense + sparse) | 별도 쿼리 + 애플리케이션 레벨 결합 |
| **스케일링** | 수평 확장 (Query Node 추가) | 단일 PostgreSQL 인스턴스 |
| **파티셔닝** | Partition Key로 멀티 테넌트 격리 | 테이블 파티셔닝 (수동) |
| **운영 복잡도** | 별도 서비스 관리 필요 | PostgreSQL에 포함 |
| **적합한 규모** | 10만 건 이상 | 10만 건 이하 |

### pgvector의 한계
- **VACUUM 문제**: 벡터 데이터는 row 크기가 크므로 (1536차원 = 약 6KB/row) Dead Tuple 발생 시 디스크 팽창이 심각.
- **인덱스 빌드**: HNSW 인덱스 빌드가 느리고 메모리를 많이 소모. `maintenance_work_mem`을 크게 설정해야 함.
- **검색과 CRUD 경합**: 벡터 검색이 CPU 집약적이라 일반 CRUD 쿼리와 리소스 경합 발생.

## 벡터 인덱스 알고리즘

### HNSW (Hierarchical Navigable Small World)

- 그래프 기반 인덱스. 계층적 구조로 탐색.
- **원리**: 상위 레이어는 장거리 점프 (고속도로), 하위 레이어는 단거리 정밀 탐색 (일반 도로).
- **파라미터**:
  - `M`: 각 노드의 연결 수. 클수록 정확하지만 메모리 증가. (기본 16)
  - `ef_construction`: 인덱스 빌드 시 탐색 범위. 클수록 정확한 인덱스. (기본 200)
  - `ef`: 검색 시 탐색 범위. 클수록 정확하지만 느림. (기본 128)
- **장점**: 검색 속도 빠름 (O(log N)), 정확도 높음.
- **단점**: 메모리 사용량 큼 (원본 벡터 + 그래프 구조).

### IVF_FLAT (Inverted File Index)

- 클러스터링 기반 인덱스.
- **원리**: k-means로 벡터를 `nlist`개 클러스터로 나눔 → 검색 시 `nprobe`개 클러스터만 탐색.
- **파라미터**:
  - `nlist`: 클러스터 수. 보통 `sqrt(N)` ~ `4*sqrt(N)`.
  - `nprobe`: 검색할 클러스터 수. 클수록 정확하지만 느림.
- **장점**: 메모리 효율적 (원본 벡터만 저장).
- **단점**: HNSW 대비 정확도/속도 열위.

### IVF_PQ (Product Quantization)

- IVF + 벡터 압축. 원본 벡터를 서브벡터로 쪼개서 양자화.
- 메모리를 극단적으로 절약 (10~100배). 정확도는 다소 희생.
- **적합한 경우**: 수억 건 이상, 메모리가 제한적인 환경.

### DiskANN

- SSD에 인덱스를 저장하고 메모리에는 압축된 벡터만 로드.
- 메모리 대비 데이터셋이 훨씬 클 때 사용.

## 유사도 메트릭

| 메트릭 | 설명 | 범위 | 사용 |
|---|---|---|---|
| **Cosine** | 벡터 방향의 유사도 | [-1, 1] | 텍스트 임베딩 (가장 보편적) |
| **L2 (Euclidean)** | 벡터 간 거리 | [0, ∞) | 이미지, 좌표 |
| **IP (Inner Product)** | 내적 | (-∞, ∞) | 정규화된 벡터에서 cosine과 동일 |

- Cosine similarity = IP(normalized A, normalized B). 정규화된 벡터에서는 사실상 같음.
- Milvus에서 cosine을 쓰면 내부적으로 벡터를 정규화 후 IP로 계산.

## Hybrid Search

Dense (벡터 유사도) + Sparse (키워드 매칭)을 결합하는 검색 방식.

### Dense Search
- 임베딩 모델로 생성한 밀집 벡터 간 유사도 검색.
- **강점**: 의미적으로 유사한 문서 찾기 ("자동차" 검색 → "차량" 문서도 찾음).
- **약점**: 정확한 키워드/고유명사 매칭에 취약.

### Sparse Search (BM25)
- 단어 빈도 기반 키워드 매칭. TF-IDF의 개선 버전.
- **강점**: 정확한 키워드 매칭 ("ISO-27001" → 정확히 포함하는 문서).
- **약점**: 동의어, 다른 표현을 이해하지 못함.

### RRF (Reciprocal Rank Fusion)

두 검색 결과의 순위를 결합하는 알고리즘.

```
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

- `k`: 스무딩 파라미터. 기본 60.
- 각 검색에서의 순위를 역수로 변환하여 합산. 순위 기반이라 점수 스케일이 달라도 동작.
- **왜 단순 점수 합산이 아닌가?**: Dense와 Sparse의 점수 스케일이 다름. Cosine은 0~1, BM25는 0~수십. 정규화해도 분포가 다르면 한쪽에 치우침. RRF는 순위만 보므로 공정.

## 컬렉션 & 파티션

### 컬렉션 (Collection)
- RDBMS의 테이블에 해당.
- 스키마 정의: 필드 타입, 벡터 차원, 인덱스 설정.

### 파티션 (Partition)
- 컬렉션 내 데이터를 논리적으로 분리.
- **Partition Key**: 특정 필드 값 기준으로 자동 파티셔닝. 멀티 테넌트에 활용.
  ```python
  # tenant_id가 같은 데이터는 같은 파티션에 저장
  schema.add_field("tenant_id", DataType.VARCHAR, is_partition_key=True)
  ```
- 검색 시 `partition_names`를 지정하면 해당 파티션만 탐색 → 성능 향상.

## Consistency Level

| 레벨 | 설명 |
|---|---|
| Strong | 모든 노드에 반영된 후 읽기. 가장 느림. |
| Bounded Staleness | 일정 시간 이내의 데이터 보장. |
| Session | 같은 세션 내에서 자기가 쓴 데이터는 즉시 읽기. |
| Eventually | 최종 일관성. 가장 빠름. |

- RAG에서는 문서 인제스트 후 즉시 검색할 일이 드물므로 `Session` 또는 `Eventually`가 적합.
