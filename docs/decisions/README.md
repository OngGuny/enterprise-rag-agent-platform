# Architecture Decision Records (ADR)

이 디렉토리는 Enterprise RAG Agent Platform 의 주요 기술 결정을 기록한다.

## 작성 원칙

- **결정 시점에 기록**: 코드를 짜기 전 또는 직후. 시간이 지나면 "왜 그렇게 했는지"를 잊는다.
- **선택지를 비교**: 한 가지 옵션만 적으면 ADR이 아니라 사후 정당화에 가깝다. 떨어뜨린 옵션도 같이 적는다.
- **근거를 남긴다**: 트레이드오프·벤치마크·제약·외부 의존성 등 미래의 자신/팀이 결정을 재평가할 때 필요한 재료.
- **상태를 갱신한다**: 결정이 뒤집히면 새 ADR을 만들고, 옛 ADR은 `Superseded by ADR-NNN` 으로 표기한다.

## 인덱스

| 번호 | 제목 | 상태 | 작성일 |
|---|---|---|---|
| [ADR-001](001-vector-database-milvus-over-pgvector.md) | 벡터 DB로 Milvus 채택 (vs pgvector) | 채택 | 2026-05-06 |
| [ADR-002](002-async-session-and-repository-pattern.md) | SQLAlchemy AsyncSession + 리포지토리 패턴 | 채택 | 2026-05-06 |
| [ADR-003](003-singleton-managers-for-external-services.md) | 외부 서비스 매니저 싱글톤 (Redis / Milvus) | 채택 | 2026-05-06 |

## 템플릿

새 ADR 작성 시 [`000-template.md`](000-template.md) 를 복사해서 시작한다.
