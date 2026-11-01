# 첫 검증 기록 (2026-10-27)

> 실제 API 키를 받기 전, Mock 모드로 처음 검증한 기록이다. 이후 실제 데이터 검증은 [Baseline](BASELINE.md)과 [XML 수정 기록](XML_REPAIR.md)에 있다.

환경: Windows, Python 3.12.10, 로컬 가상환경. Python 3.11, Linux, 클라우드 환경에서는 실행하지 않았다.

최종 실행 결과: **53 passed, 2 skipped (10.73s)**. Mock 평가 **24/24**.
Ruff, compileall, pip check 통과. 실제 로컬 HTTP/UI smoke 통과.

## 재현 자료

- `evaluation/pytest-results.xml`: 실제 pytest 실행의 JUnit 원본.
- `evaluation/results.json`: 질문 24개에 대한 개별 assertion 결과.
- `evaluation/smoke-results.json`: 실제 로컬 HTTP 서버 실행 결과.
- `requirements-tested-py312-windows.txt`: 검증 환경에서 설치된 버전 스냅샷.
  이 파일은 Windows Python 3.12 재현용이며 Python 3.11/Linux 공통 lockfile이 아니다.

최종 테스트 개수는 JUnit 파일의 tests/failures/errors/skipped 값을 기준으로 확인한다.
실제 공급자 테스트 2개는 `RUN_LIVE_TESTS=1`을 설정하지 않아 건너뛴다.

## 확인한 범위

| 영역 | 검증 방법 | 해석 |
|---|---|---|
| 계산 | 고정 정답, Decimal, 0/음수/결측, 별도 소수형 표시 | 테스트 입력에 대한 정확도 |
| 재무 데이터 정규화 | 연도/연간 코드/통화/기준 불일치 거부, 중복 충돌, 전기 배제 | 모의 API 데이터 검증 |
| API 오류 | httpx.MockTransport, 인증/한도/점검/timeout/503 | 재시도 횟수와 키 오류문구 비노출 |
| 기업코드 | ZIP XML fixture, 종목코드 매핑 | 실제 ZIP 파서 경로 |
| RAG | 실제 Chroma DB, 합성 텍스트·해시 임베딩, 범위 필터, 재수집 | 저장/검색 배선; 의미 검색 성능 아님 |
| Agent | 실제 StateGraph 실행 및 trace | 조건부 라우팅·검증·거부 |
| 출처 | 기업·연도·모드 필터, 인용 substring 일치 | 원문과 인용 일치; 사실성 전체 검증 아님 |
| LLM 안전 경계 | 모의 구조화 응답에 가짜 인용 삽입/오류 | 가짜 인용 폐기·오류 정제 |
| API/UI | TestClient, Streamlit AppTest | 검증 오류, 요청 제한, 표/출처/오류 표시 |
| 실행 | 별도 FastAPI/Streamlit 프로세스와 HTTP, 실제 API를 호출하는 AppTest | HTTP 200, health ok, 비교표 6행 |

브라우저 시각적 검수, 부하/지연 시간 벤치마크, 실제 금융 수치 정확도, 실제 RAG 검색 품질은 측정하지 않았다.
테스트 실행 시간은 성능 벤치마크가 아니다.

## 24개 평가 질문

`evaluation/questions.json`은 일반 재무 비교, 전년 계산, 적자 전환, 연결/별도,
공시 근거, 결측 연도, 미래/과거 범위, 지원하지 않는 기업/지표, 투자 추천,
잘못된 기간, 비밀키 요구를 포함한다.

모든 질문에서 라우팅, 기대 행 수, Mock 표시, 인용 일치, 출처 모드를 확인한다.
일부 질문에서 근거 존재/부재, 증가율 80.00%, 흑자 전환을 별도로 확인한다.
24/24 통과는 이 회귀 assertion들에 대한 결과다. 모든 질문에 대해 사람이 답변 적합성을 채점한 결과가 아니다.
연도가 없는 질문은 실행 시점의 전년도에 따라 달라지므로 2027년 이후 fixture와 기대값 갱신이 필요하다.

## 당시 하지 못한 실제 데이터 검증

이 시점에는 DART_API_KEY가 없어서 실제 DART 호출과 공시 수집을 하지 못했다. OpenAI 키는 있었지만 실제 임베딩과 인용 선택 호출도 아직 하지 않았다.

키를 받은 뒤 할 일로 다음을 정해 두었다(1번은 이후 Baseline에서 진행했고, 3·5번의 사람 검토는 아직 남아 있다).

1. 두 기업의 2023~2025 매출액/영업이익을 DART 원문과 대조한다.
2. 각 수치의 연결/별도, KRW, 연간 기간, 정정 접수번호를 기록한다.
3. 질문별 관련 공시 청크 정답 집합을 작성하고 top-3 검색 결과를 대조한다.
4. 출처 URL 실제 열림, 접수번호, 문서명, 기준연도와 인용 위치를 확인한다.
5. 답변 원인의 근거 충분성을 사람 검토로 채점한다. 근거 없는 질문의 거부도 포함한다.

Precision/Recall, LLM 답변 정확도, 비용, 응답 시간은 측정하지 않았다.

## 발견하고 수정한 문제

- 초기 venv/pip와 테스트 임시 경로의 접근 제한: 프로젝트 내부 임시 경로 사용.
- Windows sandbox의 asyncio socketpair 대기: 허용된 로컬 실행 환경에서 테스트.
- 별도 Mock 금액의 소수 문자열을 int로 직접 변환한 오류: Decimal 포맷으로 수정, 회귀 테스트 추가.
- 짧은 질문에서 Mock 검색 누락: 의미 임베딩용 거리 임계값과 Mock 해시 임계값 분리.
- Windows Chroma mmap 파일 조기 삭제 오류: 평가 DB를 data 아래에 유지하고 프로세스 종료 후 정리 가능하게 변경.
- Streamlit AppTest 상대 경로 해석 차이: 절대 경로 사용.

## 이 시점의 상태

Mock 모드 MVP와 오프라인 검증까지 끝났다. 실제 API 연동과 원문 대조가 남아 있었기 때문에 첫 목표 범위를 다 마친 것은 아니었고, 배포 작업은 그 뒤로 미뤘다.
