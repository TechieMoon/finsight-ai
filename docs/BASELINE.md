# FinSight AI 실제 데이터 Baseline — 2026-10-29

> 10월 29일, 개선 작업 전에 측정한 결과입니다. 여기 기록된 XML 정제 실패는 10월 31일에 고쳤고, 그 결과는 [XML 수정 기록](XML_REPAIR.md)에 따로 있습니다.

서비스 코드(워크플로·Decimal 계산·API 계약)를 바꾸지 않은 상태에서 측정했다. 측정 전후로 `finsight/*.py`의 SHA-256을 비교해 코드가 그대로인지 확인했다.

## 실제 수행 결과

| 항목 | 결과 | 해석 |
|---|---|---|
| 기존 전체 회귀 테스트 | 56 passed, 2 skipped | 최초 53개 이후 XML 테스트 3개가 추가되어 현재 56개 |
| 기존 Mock 질문 평가 | 24/24 | Mock 회귀 결과, 실제 금융 정확도로 사용하지 않음 |
| 기존 실제 연동 테스트 | 1 passed, 1 failed | 재무 조회 성공, 실제 공시 XML 정제 실패 |
| 평가 도구 자체 테스트 | 12 passed | 정답 미검토 시 null, 빈 분모, 인용별 판정, 원문 단위/기간, 비밀정보 쓰기 거부 등 |
| 실제 재무 원문 자동 대조 | 12/12, 100% | 두 기업 × 2023~2025 × 매출액/영업이익, CFS 한정 |
| 실제 계산값 대조 | 17/17, 100% | 원문에서 독립 추출한 값으로 기대 비율 산출 |
| 계산 미산출 상태 | 1/1 | SK하이닉스 2024년 전기 적자 → 흑자 전환, 영업이익 증가율 null |
| 실제 RAG 질문 실행 | 24 완료, 0 실행 오류 | 기존 실제 벡터 DB 복제 + 실제 OpenAI 호출 |
| 검색 결과 존재 | 21/24 | 검색 결과가 있다는 관측치이며 Recall이나 정답률이 아님 |
| 최종 공시 인용 채택 | 3/24 질문, 총 6개 인용 | 근거 적합성의 성공률이 아님 |
| 인용의 저장 청크 일치 | 6/6 | 의미적 뒷받침과 별개 |
| 인용의 실제 원문 텍스트 일치 | 6/6 | 동일 접수번호 원문에서 독립적인 진단용 텍스트 추출로 확인 |
| 근거 부족 안내 관측 | 21/24 | 올바른 거부인지 사람 검토 전이므로 거부 정확도가 아님 |
| Recall@3 / 채택 정밀도 / 부족 근거 거부율 | null | 사람 검토 0/24; 임의로 정답 처리하지 않음 |

재무 수치의 자동 일치는 원문 표와 API 수치의 기계적 일치다. 사람의 회계 검토, 회계정책 일치,
기업 전체의 금융 정확성, 모든 기간·지표·별도재무제표의 정확성을 의미하지 않는다.
이 문서와 원본 JSON/XML의 값이 다르면 원본을 따른다. 의미 검색 성능 수치는 아직 확정하지 않았다.

## 수집 범위와 원문 대조

삼성전자·SK하이닉스 2023~2025년 연결 연간 재무정보를 OpenDART에서 실제 조회했다.
2023년 증가율 계산을 위해 두 기업의 2022년 데이터를 보조 수집했다.
총 8개 기업·연도 조합의 재무 API 응답과 동일 접수번호의 원문 XML 24개를 보존했다.
현재 원본 자료는 `data/baseline/2026-10-29/`에 있으며 기존 `.gitignore`로 Git 제외된다.

독립 원문 대조 절차:

1. 서비스와 같은 `DartClient.financial()`로 실제 API 값을 확보하고 정규화 결과와 응답을 저장한다.
2. 재무 응답의 접수번호로 원문을 받는다. 서비스 정제 성공 여부와 별개로 원문을 보존한다.
3. 평가 전용 파서로 원문 표의 행·열을 추출한다. API 금액으로 정답을 채우지 않는다.
4. `요약연결재무정보` 문맥과 `백만원` 단위를 가진 유일한 표를 찾는다.
5. 원문 표지의 사업연도 시작/종료, 제N기와 당기 열의 제N기를 대조한다.
6. 해당 표의 매출액·영업이익 당기 열을 독립 추출하고 백만원을 원으로 환산한다.
7. 추출값과 서비스 정규화값을 비교한다. 모호하거나 표가 여러 개면 자동 확정하지 않는다.

`financial-references.json`에 원문 SHA-256, 표 인덱스, 표 머리글, 원본 행, 단위,
표지의 기간·기수 근거를 남긴다. 상태는 `verified_original_automatic`, 사람 검토는 `pending`이다.
표 추출은 서비스 XML 파서와 다른 진단용 HTML 파서를 사용한다. 이는 원문 대조를 위한 평가 경로이며
서비스 파서를 우회해 수집을 성공 처리하거나 새 벡터 DB를 생성한 것이 아니다.

원문 재무값에 대한 비율 기대값은 `Fraction`과 별도의 Decimal 컨텍스트(60자리, HALF_EVEN)로
산출한다. 서비스의 `percent()`/`growth()`를 기대값 산출에 호출하지 않는다.
운영 계산값은 기존 `compare()`로 구한다. null은 숫자 성공 개수에 포함하지 않고 따로 집계한다.

## 재무 스냅샷과 RAG 실험의 구분

- 실제 OpenDART 통신은 수집 단계에서 수행했다.
- RAG 24개 질문에서는 동일한 실제 API 스냅샷을 재생했다. 질문마다 DART를 재호출한 실험이 아니다.
- 질문 임베딩과 인용 선택에는 실제 OpenAI API를 사용했다. 합성 문서·Mock 임베딩을 사용하지 않았다.
- 현재 생산 DB에 있는 SK하이닉스 2024년 공시 833개 청크와 기존 벡터를 평가 전용 DB로 복제했다.
- 원래 생산 컬렉션에 새 문서나 임베딩을 추가하지 않았다.
- 재무는 두 기업 3개 연도가 검증 대상이나, RAG 의미 검색 대상은 기존에 수집된 SK하이닉스 2024년이다.
- 삼성전자와 다른 연도의 질문은 **미수집 대조군**이다. 그 보고서에 근거 자체가 없다고 판정하지 않는다.

문서·청크·모델·질문·서비스 코드 해시, 검색 임계값(0.6), 범위별 top-3를 기록했다.
모델 응답은 확률적이며 temperature=0도 동일 출력을 보장하지 않는다.
질문별 관측 실행 시간은 저장했지만 통제된 성능 벤치마크가 아니다.
토큰 사용량·정확한 비용은 계측하지 않아 null로 남겼다.

## RAG 질문 24개와 사람 검토

질문은 `evaluation/baseline/questions.json`에 고정했다.

- R01~R12: 실적, AI 수요, HBM, 제품 구성, 수익성 등 직접 근거가 있을 것으로 예상하는 12개 후보.
- R13~R20: 제품별 이익 기여도, 고객별 가격, 반사실적 금액, 단일 원인 단정 등 근거 부족 8개 후보.
- R21~R23: 미수집 기업·연도 3개 대조군.
- R24: 두 기업 중 한 기업만 수집된 부분 범위 대조군.

`direct_candidate`와 `insufficient_candidate`는 질문 설계 가설이지 확정 정답이 아니다.
전체 문서를 확인한 사람이 `rag-reviews.json`에 정답 근거와 판단을 기록해야 한다.
초기에는 모든 질문과 인용문이 pending이다. LLM을 별도로 호출해 정답을 만들어 넣지 않았다.

검토 순서:

1. `rag-review.csv`에서 질문·검색/채택 현황을 본다.
2. `rag-results.json`에서 검색된 청크, 답변, 경고를 확인한다.
3. `data/baseline/2026-10-29/corpus.json` 전체 833개 청크와 원문을 확인한다.
   검색 결과만 보고 정답 청크를 지정하면 Recall 평가가 편향된다.
4. `rag-reviews.json`에서 `status=reviewed`, 검토자, 검토일, `expected_support`를 작성한다.
5. 관련 근거의 전체 청크 ID 집합을 `gold_relevant_chunk_ids`에 기록하고 확인 완료 시 `gold_complete=true`로 둔다.
6. 채택한 **각 인용문**의 의미적 뒷받침을 `quote_support`의 quote_key별 true/false로 기록한다.
   같은 청크의 인용문도 각각 평가한다. 매핑은 `adopted-quotes.csv`에 있다.
7. 불명확한 판정은 null로 유지한다. 특히 기간, 전망/실적, 연결/별도, 인과관계 과장을 확인한다.

가격 효과 질문에 기술·판매 확대 설명만 제시하는 경우, 당기 보고서 안의 과거 실적 설명을
당기 원인으로 사용하는 경우 등을 검토한다. 원문에 있는 문장도 질문의 답을 보장하지 않는다.
‘근거가 없다’는 판정에는 검색 실패와 문서상 미공시를 구분한 검토 메모가 필요하다.

## 지표 정의

| 지표 | 분자/분모 및 집계 | 자동 확정 가능 여부 |
|---|---|---|
| 금융 수치 일치율 | 원문 자동 기준값과 동일한 수치 / 대조 완료 수치 | 자동 표 대조로 가능, 사람 검토 여부 별도 |
| 계산 일치율 | 독립 기대값과 일치한 비율 / 계산 가능한 비율 | 가능 |
| 미산출 상태 일치율 | 올바른 null / null 기대 사례 | 가능, 숫자와 별도 |
| Recall@3 | 질문별 `검색된 gold 청크 수 / 전체 gold 청크 수`의 평균 | 완전한 사람 gold 필요 |
| 근거 채택 정밀도 | 실질적으로 질문을 뒷받침한 인용 수 / 판정 완료 채택 인용 수 | 사람 판정 필요 |
| 근거 부족 거부율 | 근거 부족으로 올바르게 설명을 제한한 질문 / gold상 근거 부족 질문 | 사람 gold 필요 |
| 잘못된 거부율 | 답변 가능한데 설명을 제한한 질문 / gold상 답변 가능 질문 | 사람 gold 필요 |
| 인용 존재 일치율 | 원문/저장 청크에 존재한 인용 / 채택 인용 | 자동 가능, 의미 정확도 아님 |

Recall@3의 k는 현재 서비스의 **기업·연도 범위별 top-3, 거리 필터 적용 후**를 뜻한다.
복수 범위 요청은 범위별 검색 결과의 합집합을 사용한 질문 단위 지표다. 전역 top-3와 동일하지 않다.
미수집·부분 범위 대조군은 핵심 의미 평가의 정밀도/거부율/Recall 분모에서 제외한다.
분모가 0이거나 gold가 없으면 null이다. 빈 결과를 ‘100% 정밀’로 처리하지 않는다.
사람 검토된 일부 질문만으로 점수를 낼 때 검토 커버리지와 분모를 반드시 같이 보고한다.

## 발견한 오류·제약

1. **실제 공시 수집 회귀:** 보존한 원문 24개 중 22개가 현재 `clean_xml()`에서 오류를 일으켰다.
   하나라도 실패하면 현재 `ingest()` 전체가 실패한다. 실제 연동 테스트도 SK하이닉스 2024년 원문에서
   `ParseError: not well-formed (invalid token), line 866, column 62`로 실패했다.
   원문 확보와 평가 전용 표 추출은 성공했지만 새 생산 공시 인덱싱은 성공으로 기록하지 않았다.
   앞서 경고를 없애기 위해 적용한 엄격한 XML 처리가 실제 입력과 맞지 않는 회귀다.
   Baseline은 서비스 코드를 바꾸지 않고 측정하는 것이 목적이어서 이 단계에서는 고치지 않았다.
2. RAG는 검색 결과 존재 21개에 비해 최종 인용을 채택한 질문이 3개다.
   검색 적합성 부족, 인용 선택 누락, 보수적 거부 중 원인을 사람 검토로 구분해야 한다.
3. 6개 인용은 모두 존재하지만 질문에 대한 의미적 지원 여부는 검토 전이다.
4. 두 기업·2023~2025 전체에 대한 RAG 성능은 측정하지 않았다. 현재 인덱스 범위가 좁다.
5. 자동 재무 표 추출은 현재 12월 결산·연결 요약표 구조에 한정된다. 별도재무제표는 미측정이다.
6. 기존 24/24 Mock 결과와 실제 데이터 결과는 별도 파일·모드로 저장했다.

## 재현 명령

프로젝트 루트에서 실행한다. 시스템 환경변수를 그대로 읽으며 키 값을 출력하지 않는다.
`collect`는 DART 요청, `rag`는 OpenAI API 비용을 발생시킨다. 기존 스냅샷·완료된 실험은 재사용한다.

```powershell
# 최초 기존 테스트 재현 (추가 평가 도구 테스트는 별도)
.\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_dart.py tests/test_finance.py tests/test_grounding.py tests/test_live.py tests/test_rag.py tests/test_ui.py tests/test_workflow.py -q
.\.venv\Scripts\python.exe scripts/evaluate.py

# 실제 연동 검사: 현재는 공시 정제 테스트 실패가 재현됨
$env:RUN_LIVE_TESTS="1"
.\.venv\Scripts\python.exe -m pytest tests/test_live.py -v
Remove-Item Env:RUN_LIVE_TESTS

# 원문·수치·현재 인덱스 고정과 평가
.\.venv\Scripts\python.exe scripts/baseline.py collect --run 2026-10-29
.\.venv\Scripts\python.exe scripts/baseline.py inspect-tables --run 2026-10-29
.\.venv\Scripts\python.exe scripts/baseline.py build-references --run 2026-10-29
.\.venv\Scripts\python.exe scripts/baseline.py financial-metrics --run 2026-10-29
.\.venv\Scripts\python.exe scripts/baseline.py freeze-corpus --run 2026-10-29
.\.venv\Scripts\python.exe scripts/baseline.py rag --run 2026-10-29

# 사람 정답 검토 후 지표만 재계산 (외부 호출 없음)
.\.venv\Scripts\python.exe scripts/baseline.py rag-metrics --run 2026-10-29
.\.venv\Scripts\python.exe -m pytest tests/test_baseline.py -q
```

`audit`는 Baseline 당시의 서비스 코드와 현재 코드가 같은지 검사하며 `service-hashes-before.json`이 필요하다.
이 파일은 측정을 시작할 때 만들어 두었다. 새로 실행할 때는 기존 기록을 덮어쓰지 말고 다른 run ID를 쓴다.
스냅샷이나 gold를 수정하면 기존 결과를 같은 실험으로 해석할 수 없다.

## 이후 evaluate_evidence 비교 준비

서비스 개선 후 **동일한 run의 원문·벡터·질문을 유지하고 다른 variant**로 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts/baseline.py rag --run 2026-10-29 --variant evidence-v1
.\.venv\Scripts\python.exe scripts/baseline.py rag-metrics --run 2026-10-29 --variant evidence-v1
```

기존 Baseline 결과는 보존하고 `variants/evidence-v1/`에 새 결과를 저장한다.
정답 청크는 동일 corpus ID를 기준으로 재사용할 수 있으나, 새 인용문에 대한 판정은 별도로 필요하다.
서비스 코드 해시가 기록되어 실제 개선 전후를 구분한다.
지금 준비된 것은 데이터 고정, 실행, 자동 검사, 검토 양식까지다. 사람의 정답 검토가 남아 있어서
개선 효과는 아직 측정할 수 없고, evaluate_evidence도 구현하지 않았다.

## 결과 파일과 보안

결과: `evaluation/baseline/2026-10-29/`

- `pytest-existing.xml`, `pytest-live.xml`, `pytest-evaluator.xml`: 테스트 원본
- `mock-results.json`: 기존 Mock 평가 별도 보존
- `manifest.json`, `corpus-manifest.json`: 실제 수집·고정 인덱스·환경·모델·서비스 해시
- `financial-references.json`, `financial-results.json`, `original-table-index.json`: 원문 대조 증적
- `rag-results.json`, `rag-summary.json`, `rag-review.csv`, `adopted-quotes.csv`: 실제 실행·자동 관측·검토 자료
- `rag-reviews.json`: 사람 정답, 현재 모두 pending
- `source-audit.json`: 원문 해시·서비스 파서 오류·인용의 원문 존재 검사
- `service-hashes-before.json`, `service-integrity.json`: 서비스 파일 불변 검증
- `security-audit.json`: 현재 알려진 키 값·인증 query URL의 보고서 포함 여부 검사

원문·벡터는 `data/`에만 저장한다. API 인증 query URL·헤더·Settings 전체·환경변수 덤프·SDK 오류문구를
결과에 저장하지 않는다. 오류는 단계·타입·필요한 파싱 위치만 기록한다.
known-secret 검사는 알려진 키 값만 찾으므로 모든 비밀정보를 잡아내지는 못한다.
