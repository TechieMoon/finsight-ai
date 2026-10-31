import os

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FinSight AI | 공시 분석", page_icon="📊", layout="wide")
API = os.environ.get("FINSIGHT_API_URL", "http://127.0.0.1:8000").rstrip("/")
st.title("FinSight AI")
st.caption("금융 공시 분석 · 기업 비교 | 수치 계산과 공시 근거를 함께 확인하세요")

with st.sidebar:
    st.header("분석 설정")
    basis = st.selectbox(
        "재무제표 기준", ["CFS", "OFS"], format_func=lambda x: "연결 (CFS)" if x == "CFS" else "별도 (OFS)"
    )
    st.caption("지원: 삼성전자 · SK하이닉스 / 연간 매출·영업이익 / 최대 4개 연도")
    st.info("질문에 '연결' 또는 '별도'가 명시되면 질문의 기준을 우선합니다.")
    try:
        health = httpx.get(f"{API}/health", timeout=3).json()
        if health.get("mode") == "mock":
            st.warning("MOCK 모드\n\n수치·공시 모두 합성 테스트 데이터입니다.")
        else:
            st.success("LIVE 모드 · OpenDART")
            st.caption("모드 표시는 API 연동 검증 완료를 의미하지 않습니다.")
    except (httpx.HTTPError, ValueError):
        st.error("API에 연결할 수 없습니다. FastAPI 서버를 먼저 실행하세요.")
    st.caption("투자 추천 및 수익 보장을 제공하지 않습니다.")

with st.form("question_form"):
    question = st.text_area(
        "분석할 질문",
        "삼성전자와 SK하이닉스의 2023~2025년 매출액과 영업이익률을 비교해 줘.",
        max_chars=1000,
        height=100,
    )
    submitted = st.form_submit_button("분석 실행", type="primary")

if submitted:
    st.session_state.pop("analysis", None)
    with st.spinner("재무 데이터와 공시 근거를 확인하고 있습니다…"):
        try:
            response = httpx.post(f"{API}/analyze", json={"question": question, "basis": basis}, timeout=180)
            response.raise_for_status()
            st.session_state.analysis = response.json()
        except httpx.HTTPStatusError as exc:
            st.error(
                f"분석 요청 실패 (HTTP {exc.response.status_code}). 질문 길이·서버 설정·호출 한도를 확인하세요."
            )
        except (httpx.HTTPError, ValueError):
            st.error("서버 응답을 받지 못했습니다. 서버 실행 및 네트워크를 확인하세요.")

result = st.session_state.get("analysis")
if result:
    if result["mode"] == "mock":
        st.warning("MOCK · 아래의 모든 수치와 공시는 합성 데이터이며 실제 기업 실적이 아닙니다.")
    st.subheader("분석 결과")
    # Render untrusted disclosures as plain text, never HTML or executable Markdown.
    st.text(result["answer"])
    for warning in result["warnings"]:
        st.warning(warning)
    if result["financials"]:
        frame = pd.DataFrame(result["financials"])
        numeric = [
            "revenue",
            "operating_profit",
            "operating_margin_pct",
            "revenue_growth_pct",
            "profit_growth_pct",
        ]
        for col in numeric:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        st.subheader("기업별 재무 비교")
        display = frame[["company", "year", "basis", *numeric, "period_end"]].rename(
            columns={
                "company": "기업",
                "year": "회계연도",
                "basis": "재무제표",
                "revenue": "매출액 (원)",
                "operating_profit": "영업이익 (원)",
                "operating_margin_pct": "영업이익률 (%)",
                "revenue_growth_pct": "매출 증가율 (%)",
                "profit_growth_pct": "영업이익 증가율 (%)",
                "period_end": "기간 종료일",
            }
        )
        st.dataframe(display, hide_index=True, width="stretch")
        st.caption("결측/0 기준/적자 기준 증가율은 빈 값입니다. 적자 전환 여부는 분석 결과를 확인하세요.")
        left, right = st.columns(2)
        with left:
            st.subheader("매출액 추이 (십억원)")
            st.line_chart(frame.pivot(index="year", columns="company", values="revenue") / 1e9)
        with right:
            st.subheader("영업이익 추이 (십억원)")
            st.bar_chart(frame.pivot(index="year", columns="company", values="operating_profit") / 1e9)
    st.subheader("출처 및 데이터 기준")
    for source in result["sources"]:
        st.text(f"{source['title']} | 기준일 {source['reference_date']} | 접수번호 {source['receipt']}")
        if source["mode"] == "live" and source["url"].startswith(
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
        ):
            st.link_button("DART 원문 열기", source["url"])
        else:
            st.caption("합성 fixture · 실제 공시 원문 링크 없음")
        st.caption(f"조회/수집 시각 (UTC): {source['retrieved_at']}")
    st.caption(f"분석 시각 (UTC): {result['retrieved_at']} | 회계기간: 연간 1월 1일~12월 31일, KRW")
    with st.expander("분석 경로"):
        st.json(result["trace"])
