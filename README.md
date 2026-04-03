# Enterprise RAG Agent Platform

> FastAPI + Milvus + vLLM + LangGraph 기반 엔터프라이즈 RAG 에이전트 플랫폼

## Overview

기업 문서를 인제스트하고, RAG 기반 검색 + AI 에이전트 워크플로우를 통해 사용자 질문에 답변하는 **엔터프라이즈 AI 플랫폼 백엔드**.

## Tech Stack

### Backend & API
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-499848?style=flat-square)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square&logo=pydantic&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=flat-square&logo=celery&logoColor=white)

### LLM & AI Agent
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langchain&logoColor=white)
![vLLM](https://img.shields.io/badge/vLLM-FF6F00?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=flat-square&logo=ollama&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI_API-412991?style=flat-square&logo=openai&logoColor=white)

### Vector DB & Search
![Milvus](https://img.shields.io/badge/Milvus-00A1EA?style=flat-square&logo=milvus&logoColor=white)
![HNSW](https://img.shields.io/badge/HNSW_Index-4A90D9?style=flat-square)
![BM25](https://img.shields.io/badge/BM25_Sparse-6C757D?style=flat-square)
![RRF](https://img.shields.io/badge/RRF_Fusion-8B5CF6?style=flat-square)

### Database & Cache
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-Async-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white)

### Infra & Monitoring
![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-009639?style=flat-square&logo=nginx&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat-square&logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat-square&logo=grafana&logoColor=white)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      API Gateway (Nginx)                │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  FastAPI Application                     │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Chat API │  │ Docs API │  │Agent API │  │Health  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┘  │
│       │              │             │                     │
│  ┌────▼──────────────▼─────────────▼──────────────────┐ │
│  │              Core Services                          │ │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────────────┐   │ │
│  │  │ RAG     │ │ LLM      │ │ Agent (LangGraph)  │   │ │
│  │  │Pipeline │ │Router    │ │ State Machine      │   │ │
│  │  └────┬────┘ └────┬─────┘ └────────┬───────────┘   │ │
│  └───────┼───────────┼────────────────┼───────────────┘ │
└──────────┼───────────┼────────────────┼─────────────────┘
           │           │                │
     ┌─────▼───┐ ┌─────▼───┐  ┌────────▼────────┐
     │ Milvus  │ │vLLM/    │  │  Tool Calling   │
     │         │ │Ollama   │  │  (SQL, Web, RAG) │
     └─────────┘ └─────────┘  └─────────────────┘

     ┌─────────┐ ┌─────────┐  ┌─────────────────┐
     │PostgreSQL│ │  Redis  │  │ Celery Workers  │
     └─────────┘ └─────────┘  └─────────────────┘
```

## Key Features

### RAG Pipeline
- **Multi-format Extraction** - PDF (OCR fallback), DOCX, PPTX, Web
- **Parent-Child Chunking** - 검색 정확도(child) + 충분한 컨텍스트(parent)
- **Hybrid Search** - Dense (cosine) + Sparse (BM25) + RRF fusion
- **Re-ranking** - Cross-encoder 기반 정밀 재정렬

### LLM Serving
- **Model Routing** - 질문 복잡도 기반 모델 자동 선택 (규칙 + LLM 하이브리드)
- **Semantic Cache** - 임베딩 유사도 기반 캐시 (Redis)
- **Circuit Breaker** - 장애 감지 + 자동 fallback (vLLM → Ollama → OpenAI)
- **SSE Streaming** - Server-Sent Events 기반 실시간 응답

### AI Agent (LangGraph)
- **Stateful Workflow** - 상태 머신 기반 복잡한 분기/루프 지원
- **Tool Calling** - RAG 검색, SQL 실행, 웹 검색 등 동적 도구 호출
- **Guardrails** - max_steps 제한, 반복 호출 감지, 품질 체크
- **Execution Logging** - 에이전트 실행 과정 전체 로깅

## Project Structure

```
src/
├── main.py                  # FastAPI 앱 진입점
├── config.py                # 설정 관리 (pydantic-settings)
├── api/                     # API 레이어
│   ├── endpoints/           # chat, documents, collections, agents, health
│   ├── middleware.py         # 요청 로깅, Rate Limiting, CORS
│   └── schemas/             # Pydantic 요청/응답 모델
├── rag/                     # RAG 파이프라인
│   ├── extractors/          # PDF, DOCX, PPTX, Web 텍스트 추출
│   ├── chunkers/            # Semantic, Recursive, Parent-Child 청킹
│   ├── embeddings/          # OpenAI, Local (Sentence Transformers) 임베딩
│   ├── vectorstore/         # Milvus 클라이언트, 스키마, 인덱싱, 검색
│   └── retriever.py         # 검색 → Re-ranking → Context 구성
├── agent/                   # AI 에이전트
│   ├── graph.py             # LangGraph 상태 머신
│   ├── state.py             # AgentState 정의
│   ├── nodes/               # query_analyzer, router, rag_search, web_search 등
│   ├── tools/               # Tool Calling 인터페이스
│   └── memory.py            # 대화 히스토리 관리
├── llm/                     # LLM 서빙
│   ├── router.py            # 태스크별 모델 라우팅
│   ├── streaming.py         # SSE 스트리밍
│   ├── cache.py             # Redis 시맨틱 캐싱
│   └── *_client.py          # OpenAI, vLLM, Ollama 클라이언트
├── db/                      # PostgreSQL (메타데이터)
│   ├── models/              # ORM 모델
│   └── repositories/        # 리포지토리 패턴
├── core/                    # 공통 유틸리티
│   ├── exceptions.py        # 커스텀 예외
│   ├── logging.py           # 구조화 로깅 (structlog)
│   ├── rate_limiter.py      # Token Bucket Rate Limiter
│   └── circuit_breaker.py   # 서킷 브레이커 패턴
└── workers/                 # Celery 비동기 작업
    └── tasks/               # 문서 인제스트, 임베딩 생성
```

## Getting Started

```bash
# 환경 설정
cp .env.example .env

# Docker Compose로 전체 서비스 실행
docker compose up -d

# GPU 서빙이 필요한 경우
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# API 서버 확인
curl http://localhost:8000/api/v1/health
```
