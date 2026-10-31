# P0 구현 계획

빈 작업 디렉터리에서 시작 (2026-10-27). Python 3.11 목표, 로컬 설치 환경은 3.12.

1. 설정/모델 → Decimal 계산 → 단위 테스트
2. OpenDART HTTP 클라이언트 → 기업코드, 연간 전체 재무제표, 공시 원문 수집 → 모의 HTTP 검증
3. Chroma 영속 저장 + OpenAI 임베딩, 오프라인 테스트 임베딩 분리 → 검색 검증
4. Typed State / 조건부 라우팅 / 데이터 검증 / 답변 생성 → 평가 질문 최소 20개
5. FastAPI + Streamlit → 통합 테스트, 실행 가이드, 검증 결과

## 폴더와 데이터 흐름

`finsight/config.py`, `models.py`: 환경변수/검증 스키마
`finance.py`: 순수 계산 및 재무 항목 검증
`dart.py`: 공공 API만 호출, timeout/재시도/호출 제한
`rag.py`: 정제/청크/임베딩/Chroma/검색
`workflow.py`: 단일 LangGraph; `api.py`: HTTP 경계
`ui/app.py`: 서버에만 질의하는 Streamlit
`tests/`: 오프라인 테스트 및 opt-in 실제 연동 검사
`scripts/`: 설정 진단/공시 수집/재현 가능한 평가

질문 → 입력 검증 → 규칙 기반 제한형 분류 → 재무 조회/계산 → 필요 시 공시 검색
→ 범위·출처 검증 → 수치 템플릿 및 근거 발췌 → 응답.
실제 모드에서는 OpenAI structured output으로 공시의 관련 문장 ID를 선택한다.
LLM이 금액, URL, 접수번호를 생성하지 않도록 서버가 검증된 데이터에서 구성한다.

P0 범위: 삼성전자/SK하이닉스, 2015년 이후 완료된 연간 손익, 명시적 연결/별도.
전기 금액을 당기 금액과 합치지 않고 각 연도를 독립 조회한다.
실제 키가 없으면 mock으로만 실행 가능하며 실제 모드의 자동 mock 대체는 금지한다.
P0 실제 검증 전 Docker/배포/CI/MCP는 보류한다.
