# Redis 핵심 개념

## Redis란?

- In-memory key-value 데이터 스토어. 읽기/쓰기 모두 마이크로초 단위.
- 단일 스레드 이벤트 루프. 락 경쟁이 없어서 빠름.
- Redis 7.0부터 I/O 멀티스레딩 지원 (커맨드 실행은 여전히 단일 스레드).

## 자료구조

### String
- 가장 기본. `SET key value`, `GET key`.
- 카운터 (`INCR`), TTL 캐시, 세션 저장.

### Hash
- 필드-값 쌍의 맵. `HSET user:1 name "kim" age 30`.
- 객체 저장에 적합. 필드 단위로 읽기/쓰기 가능.

### List
- 양방향 링크드 리스트. `LPUSH`, `RPUSH`, `LPOP`, `RPOP`.
- 메시지 큐, 최근 N개 항목.

### Set / Sorted Set
- Set: 중복 없는 집합. 교집합, 합집합 연산.
- Sorted Set (ZSet): 점수(score) 기반 정렬. **리더보드, 랭킹**.
  ```
  ZADD leaderboard 100 "user:1" 200 "user:2"
  ZRANGEBYSCORE leaderboard 0 150  → ["user:1"]
  ```

### Stream
- 이벤트 로그 / 메시지 스트림. Kafka의 경량 대안.
- Consumer Group으로 분산 처리 가능.

## Persistence (영속성)

### RDB (Redis Database)
- 특정 시점의 스냅샷을 디스크에 저장. `BGSAVE` (fork 후 백그라운드 저장).
- 장점: 복구 속도 빠름, 파일 하나.
- 단점: 마지막 스냅샷 이후 데이터 유실 가능.

### AOF (Append Only File)
- 모든 쓰기 명령을 로그에 기록.
- `appendfsync always`: 매 명령마다 fsync. 데이터 안전 but 느림.
- `appendfsync everysec`: 1초마다 fsync. 균형. (기본 권장)
- `appendfsync no`: OS에 맡김. 가장 빠르지만 데이터 유실 위험.

### RDB + AOF 조합
- 둘 다 켜면 Redis 재시작 시 AOF를 우선 사용 (더 완전하므로).
- 프로덕션 권장: AOF(everysec) + 주기적 RDB 스냅샷.

## Eviction Policy (메모리 부족 시)

| 정책 | 설명 |
|---|---|
| `noeviction` | 쓰기 거부 (기본) |
| `allkeys-lru` | LRU (Least Recently Used) 제거 |
| `allkeys-lfu` | LFU (Least Frequently Used) 제거 |
| `volatile-lru` | TTL이 설정된 키 중 LRU 제거 |
| `volatile-ttl` | TTL이 가장 짧은 키 제거 |

- 캐시 용도: `allkeys-lru` 또는 `allkeys-lfu`.
- 세션 저장소: `volatile-lru` (TTL 없는 키는 보존).

## Pub/Sub vs Stream

| 항목 | Pub/Sub | Stream |
|---|---|---|
| 메시지 보존 | X (구독자 없으면 소실) | O (영속 저장) |
| Consumer Group | X | O |
| 재처리 | X | O (ID 기반 재읽기) |
| 용도 | 실시간 알림, 이벤트 브로드캐스트 | 이벤트 소싱, 작업 큐 |

## 시맨틱 캐시에서 Redis 역할

이 프로젝트에서 Redis는 **시맨틱 캐시** 저장소로 사용:

```
cache:emb:{id} → 질문 임베딩 벡터 (bytes)
cache:ans:{id} → 캐시된 답변 (string)
```

- 새 질문이 들어오면 임베딩을 생성하고, 기존 캐시와 cosine similarity 비교.
- threshold(0.92) 이상이면 캐시 히트 → LLM 호출 없이 응답.
- TTL로 캐시 자동 만료 (1시간).

### 한계 & 개선
- 캐시 키가 많아지면 순차 비교가 느림 → Redis 자체의 벡터 검색(RediSearch) 모듈 활용 가능.
- 또는 캐시 임베딩도 Milvus에 저장하고 top-1 검색으로 대체.

## Celery 브로커로서의 Redis

- Celery 태스크 큐의 메시지 브로커 역할.
- 태스크 발행 → Redis List에 push → 워커가 pop하여 처리.
- **RabbitMQ vs Redis 브로커**:
  - RabbitMQ: 메시지 보장 강함, 복잡한 라우팅. 대규모 프로덕션.
  - Redis: 간단, 빠름, 이미 캐시로 쓰고 있으면 인프라 절약. 중소 규모 적합.
