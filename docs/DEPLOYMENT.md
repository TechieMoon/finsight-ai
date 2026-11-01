# 실행과 배포 메모

지금은 로컬 실행만 확인한 상태이며 외부에 배포하지 않았습니다. Dockerfile과 CI도 아직 없습니다.

## 로컬 실행

README의 두 명령으로 FastAPI(8000)와 Streamlit(8501)을 띄웁니다. 둘 다 `127.0.0.1`에 바인딩하고, UI는 `FINSIGHT_API_URL`로 API 주소를 찾습니다. `scripts/smoke.py`는 별도 포트(18000/18501)에서 서버를 띄워 검사한 뒤 종료합니다. Mock 모드는 화면에 합성 데이터임을 표시하므로 키 없이 시연할 때 쓸 수 있습니다.

## LIVE 모드로 바꾸기

1. `.env.example`을 `.env`로 복사하고 API 키를 넣습니다.
2. `FINSIGHT_MODE=live`로 바꾸고 서버를 다시 시작합니다.
3. 공시 수집 CLI로 질문할 연도의 문서를 저장합니다.
4. `RUN_LIVE_TESTS=1`로 연동 테스트를 실행합니다.
5. 수치와 링크를 원문과 대조하고, 날짜와 결과를 검증 문서에 남깁니다.

재무 조회만 한다면 OpenAI 키 없이도 LIVE 모드가 동작합니다. 공시 수집·검색·근거 선택에는 OpenAI 키가 필요합니다.

## 외부에 배포한다면

- Python 3.11 이미지와 고정된 의존성으로 빌드
- FastAPI와 UI는 별도 프로세스로 실행하고 API는 내부 네트워크에 배치
- 키는 플랫폼의 secret store로 주입하고 이미지·클라이언트·Git에 넣지 않기
- `CHROMA_PATH`에 영속 볼륨을 연결하고 백업·갱신 정책 정하기
- 공개 전에 인증, HTTPS, 서버 측 호출량·비용 한도 구현
- `/health`와 실제 질의 smoke 실행. `/health`가 정상이어도 외부 API 연결이 된다는 뜻은 아님
- 데이터 이용 조건과 외부 임베딩 서비스로 보내는 문서 범위 확인

아직 구현하지 않은 계획입니다.

## Windows에서 겪은 문제

- 샌드박스 환경에서 asyncio의 로컬 socketpair 생성이 막히면 FastAPI TestClient가 멈출 수 있습니다. 일반 터미널에서 실행하면 됩니다.
- 임시 경로 접근 오류가 나면 `TEMP`/`TMP`나 pytest `--basetemp`를 프로젝트 안의 경로로 지정합니다.
- Chroma가 Windows에서 mmap 파일을 잡고 있어서 프로세스가 끝나기 전에는 지울 수 없습니다. 평가용 DB는 `data/evaluations/`에 남습니다.
