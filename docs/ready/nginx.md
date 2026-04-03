# Nginx 핵심 개념

## Nginx란?

- 고성능 웹 서버 / 리버스 프록시 / 로드 밸런서.
- **이벤트 기반 비동기 아키텍처**: Apache(프로세스/스레드 기반) 대비 동시 연결 처리 효율 높음.
- C10K 문제(만 개 동시 연결)를 해결하기 위해 설계됨.

## 리버스 프록시

```
Client → Nginx (80/443) → FastAPI (8000)
```

```nginx
upstream api_servers {
    server api:8000;
}

server {
    listen 80;

    location /api/ {
        proxy_pass http://api_servers;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### 왜 리버스 프록시가 필요한가?
1. **SSL/TLS 종료**: Nginx에서 HTTPS 처리 → 백엔드는 HTTP로 통신. 인증서 관리 일원화.
2. **정적 파일 서빙**: Nginx가 직접 서빙. FastAPI가 처리할 필요 없음.
3. **버퍼링**: 느린 클라이언트의 요청을 Nginx가 버퍼링 → 백엔드 연결 빠르게 해제.
4. **보안**: 백엔드 서버를 외부에 직접 노출하지 않음. 요청 필터링, Rate Limiting.

## 로드 밸런싱

```nginx
upstream api_servers {
    least_conn;                    # 로드 밸런싱 알고리즘
    server api-1:8000 weight=3;   # 가중치 3
    server api-2:8000 weight=1;   # 가중치 1
    server api-3:8000 backup;     # 백업 (다른 서버 다운 시만)
}
```

### 알고리즘

| 알고리즘 | 설명 |
|---|---|
| `round-robin` (기본) | 순서대로 분배 |
| `least_conn` | 활성 연결이 적은 서버로 |
| `ip_hash` | 클라이언트 IP 해시로 고정 서버 배정 (세션 유지) |
| `random two` | 랜덤 2개 선택 후 연결 적은 쪽 |

## SSE 프록시 설정

LLM 스트리밍 응답을 위한 특수 설정:

```nginx
location /api/v1/chat {
    proxy_pass http://api_servers;
    
    # SSE에 필수
    proxy_buffering off;           # 버퍼링 비활성화 (즉시 전달)
    proxy_cache off;               # 캐싱 비활성화
    proxy_read_timeout 300s;       # LLM 응답 대기 시간 (길게)
    
    # HTTP/1.1 유지 (chunked transfer)
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

- `proxy_buffering off`가 핵심. 버퍼링이 켜져 있으면 Nginx가 응답을 모아서 보내므로 스트리밍이 안 됨.

## 주요 설정

### worker_processes & connections
```nginx
worker_processes auto;          # CPU 코어 수만큼 자동 설정
events {
    worker_connections 1024;    # 워커당 최대 연결 수
    use epoll;                  # Linux 이벤트 알림 메커니즘
}
```

- 최대 동시 연결 수 = `worker_processes * worker_connections`.

### 요청 크기 제한
```nginx
client_max_body_size 100M;      # 파일 업로드 최대 크기
```

- 문서 업로드를 위해 충분히 크게 설정.

### Gzip 압축
```nginx
gzip on;
gzip_types application/json text/plain text/css;
gzip_min_length 1000;           # 1KB 이하는 압축 안 함
```
