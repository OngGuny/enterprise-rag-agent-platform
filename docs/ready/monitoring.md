# Prometheus & Grafana 핵심 개념

## Prometheus

- 오픈소스 시계열(time-series) 모니터링 시스템. CNCF 졸업 프로젝트.
- **Pull 모델**: Prometheus가 주기적으로 타겟의 `/metrics` 엔드포인트를 스크래핑.
- PromQL이라는 쿼리 언어로 메트릭 조회.

### 4가지 메트릭 타입

| 타입 | 설명 | 예시 |
|---|---|---|
| **Counter** | 단조 증가 카운터 | 총 요청 수, 총 에러 수 |
| **Gauge** | 증가/감소 가능한 값 | 현재 메모리 사용량, 활성 연결 수 |
| **Histogram** | 값의 분포 (버킷) | 응답 시간 분포, 요청 크기 분포 |
| **Summary** | 값의 분위수 (quantile) | p50, p95, p99 응답 시간 |

### Histogram vs Summary
- **Histogram**: 서버 사이드 버킷 카운트. 여러 인스턴스 집계 가능.
  ```
  http_request_duration_seconds_bucket{le="0.1"} 24000   # 0.1초 이하: 24000건
  http_request_duration_seconds_bucket{le="0.5"} 33000   # 0.5초 이하: 33000건
  http_request_duration_seconds_bucket{le="1.0"} 34500   # 1.0초 이하: 34500건
  ```
- **Summary**: 클라이언트 사이드 분위수 계산. 집계 불가.
- **권장**: Histogram. 분산 환경에서 집계 가능하고, PromQL로 분위수 근사 계산.

### PromQL 예시

```promql
# 5분간 초당 요청 수 (RPS)
rate(http_requests_total[5m])

# 95 퍼센타일 응답 시간
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# 에러율
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])
```

### FastAPI에서 Prometheus 메트릭

```python
from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency",
    ["method", "endpoint"]
)

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

## Grafana

- 메트릭 시각화 대시보드. Prometheus를 데이터소스로 연결.
- JSON 기반 대시보드 정의 → 버전 관리 가능.

### 이 프로젝트의 주요 대시보드

#### API Metrics Dashboard
- RPS (Requests Per Second)
- 응답 시간 분포 (p50, p95, p99)
- 에러율
- 엔드포인트별 트래픽

#### GPU Metrics Dashboard (DCGM)
- GPU 사용률 (%)
- GPU 메모리 사용량
- 추론 처리량 (tokens/sec)
- 모델별 응답 시간

### Alert 규칙

```yaml
# prometheus/rules.yml
groups:
  - name: api_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Error rate > 5% for 5 minutes"
```

## 관측 가능성 (Observability) 3요소

| 요소 | 도구 | 역할 |
|---|---|---|
| **Metrics** | Prometheus + Grafana | "무엇이 문제인가?" (수치) |
| **Logs** | structlog + ELK/Loki | "왜 문제인가?" (상세 기록) |
| **Traces** | OpenTelemetry + Jaeger | "어디서 느린가?" (요청 경로 추적) |

### structlog

```python
import structlog

logger = structlog.get_logger()
logger.info("document_ingested", document_id=42, chunks=15, duration_ms=1200)
# → {"event": "document_ingested", "document_id": 42, "chunks": 15, "duration_ms": 1200, "timestamp": "..."}
```

- 구조화된 JSON 로그. 파싱/검색이 쉬움.
- `request_id`를 바인딩하면 요청 단위로 로그 추적 가능.

## RED 메서드 (서비스 모니터링)

| 지표 | 설명 | PromQL |
|---|---|---|
| **Rate** | 초당 요청 수 | `rate(http_requests_total[5m])` |
| **Errors** | 에러율 | `rate(http_requests_total{status=~"5.."}[5m])` |
| **Duration** | 응답 시간 | `histogram_quantile(0.95, ...)` |

- 모든 서비스에 이 3가지를 대시보드로 만들면 기본적인 모니터링 완성.
