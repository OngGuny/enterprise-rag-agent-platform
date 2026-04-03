# Docker & Docker Compose 핵심 개념

## 컨테이너 vs VM

| 항목 | 컨테이너 | VM |
|---|---|---|
| 가상화 레벨 | OS 커널 공유 (프로세스 격리) | 하드웨어 가상화 (게스트 OS) |
| 크기 | MB 단위 | GB 단위 |
| 시작 시간 | 초 단위 | 분 단위 |
| 오버헤드 | 거의 없음 | 게스트 OS 리소스 소모 |

- 컨테이너는 Linux의 **namespace** (프로세스 격리)와 **cgroup** (리소스 제한)으로 구현.

## Dockerfile 최적화

### 레이어 캐싱
```dockerfile
# 의존성 먼저 복사 → 코드 변경 시 pip install 재실행 방지
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 코드는 나중에 복사
COPY src/ ./src/
```

- Docker는 각 명령어를 레이어로 캐싱. 변경된 레이어 이후만 재빌드.
- **변경 빈도가 낮은 레이어를 위에**, 높은 레이어를 아래에 배치.

### Multi-stage Build
```dockerfile
# Build stage
FROM python:3.12-slim AS builder
COPY pyproject.toml .
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.12-slim
COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
```

- 빌드 도구는 최종 이미지에 포함되지 않음 → 이미지 크기 감소.

## Docker Compose

여러 컨테이너를 정의하고 함께 실행하는 도구.

### depends_on vs healthcheck

```yaml
services:
  api:
    depends_on:
      postgres:
        condition: service_healthy  # healthcheck 통과 후 시작
  
  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 5s
      timeout: 3s
      retries: 5
```

- `depends_on`만으로는 컨테이너 "시작"만 보장. 서비스가 "준비"되었는지는 모름.
- `healthcheck` + `condition: service_healthy`로 서비스가 실제로 준비된 후 시작.

### 네트워킹

- 같은 Compose 파일의 서비스들은 자동으로 같은 네트워크에 배치.
- **서비스 이름이 DNS 호스트명**: `postgres:5432`, `redis:6379`, `milvus:19530`.
- 외부 노출은 `ports`로. 내부 통신만 필요하면 `expose`로.

### Volume

```yaml
volumes:
  milvus_data:    # Named Volume: Docker가 관리, 컨테이너 삭제 후에도 유지
  
services:
  milvus:
    volumes:
      - milvus_data:/var/lib/milvus         # Named Volume 마운트
      - ./infra/milvus:/etc/milvus          # Bind Mount: 호스트 파일 직접 연결
```

- **Named Volume**: 데이터 영속성. DB 데이터, 모델 파일.
- **Bind Mount**: 설정 파일, 코드 (개발 시 핫 리로드).

## Docker Compose Override

```bash
# 기본 + GPU 오버라이드
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

```yaml
# docker-compose.gpu.yml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

- 기본 파일을 수정하지 않고 환경별 설정을 덮어씌움.
- `docker-compose.yml` (기본) + `docker-compose.gpu.yml` (GPU) + `docker-compose.prod.yml` (프로덕션) 등.

## 프로덕션 고려사항

### 리소스 제한
```yaml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"
        reservations:
          memory: 512M
```

### 로그 관리
```yaml
services:
  api:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

- 로그 파일 크기 제한 안 하면 디스크가 가득 찰 수 있음.

### 재시작 정책
```yaml
services:
  api:
    restart: unless-stopped  # 수동 종료 외에는 항상 재시작
```

| 정책 | 설명 |
|---|---|
| `no` | 재시작 안 함 (기본) |
| `always` | 항상 재시작 |
| `on-failure` | 비정상 종료(exit code != 0) 시만 |
| `unless-stopped` | 수동 종료 외에는 항상 |
