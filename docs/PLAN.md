# 초기 구현 계획 (2026-10-27)

빈 폴더에서 시작했습니다. 목표 버전은 Python 3.11, 로컬 개발 환경은 3.12입니다.

## 순서

1. 설정·모델 → Decimal 계산 → 단위 테스트
2. OpenDART HTTP 클라이언트 → 기업코드, 연간 전체 재무제표, 공시 원문 수집 → Mock HTTP로 검증
3. Chroma 저장소와 OpenAI 임베딩, 테스트용 오프라인 임베딩 분리 → 검색 검증
4. Typed State, 조건부 라우팅, 데이터 검증, 답변 생성 → 평가 질문 20개 이상
5. FastAPI와 Streamlit → 통합 테스트, 실행 방법, 검증 기록

## 모듈

- `finsight/config.py`, `models.py`: 환경변수와 스키마
- `finance.py`: 계산과 재무 항목 검증
- `dart.py`: 공공 API 호출, timeout·재시도·호출 제한
- `rag.py`: 정제, 청크, 임베딩, Chroma, 검색
- `workflow.py`: LangGraph 그래프
- `api.py`: HTTP 경계
- `ui/app.py`: 서버에만 질의하는 Streamlit
- `tests/`: 오프라인 테스트와 선택 실행하는 실제 연동 테스트
- `scripts/`: 설정 진단, 공시 수집, 평가

## 데이터 흐름

질문 → 입력 검증 → 규칙 기반 분류 → 재무 조회·계산 → 필요하면 공시 검색 → 범위·출처 검증 → 수치 템플릿과 근거 발췌 → 응답

LIVE 모드에서는 OpenAI structured output으로 공시에서 관련 문장의 ID만 고릅니다. 금액, URL, 접수번호는 LLM이 만들지 않고 서버가 검증된 데이터로 채웁니다.

## 첫 범위

- 삼성전자와 SK하이닉스, 2015년 이후 마감된 연간 손익, 연결/별도를 명시
- 전기 금액을 당기 금액으로 쓰지 않고 연도마다 따로 조회
- 키가 없으면 Mock으로만 실행하고, LIVE 모드가 실패했을 때 Mock으로 바꾸지 않음
- Docker, 배포, CI, MCP는 실제 데이터 검증을 마친 뒤로 미룸
