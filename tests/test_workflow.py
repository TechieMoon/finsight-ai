import pytest

from finsight.config import Settings
from finsight.finance import DataError
from finsight.models import Question
from finsight.workflow import Agent, classify


@pytest.mark.parametrize(
    "question,route",
    [
        ("삼성전자 2024 매출", "finance"),
        ("SK하이닉스 2024 실적 원인", "mixed"),
        ("삼성전자 매수 추천", "unsupported"),
        ("애플 매출", "unsupported"),
        ("삼성전자 2024 분기 매출", "unsupported"),
        ("삼성전자 2024 순이익", "unsupported"),
        ("삼성전자 2030 매출", "unsupported"),
        ("삼성전자 2010 매출", "unsupported"),
        ("삼성전자 2025~2023 매출", "unsupported"),
        ("삼성전자 연결 별도 비교", "unsupported"),
    ],
)
def test_routes(question, route):
    assert classify(question, 2026)["route"] == route


def test_years():
    assert classify("두 기업의 최근 연간 실적 비교", 2026)["years"] == [2025]
    assert classify("삼성전자 2024 영업이익 전년 대비", 2026)["years"] == [2023, 2024]
    assert classify("삼성전자 2023~2025 매출", 2026)["years"] == [2023, 2024, 2025]


def test_graph_finance(tmp_path):
    agent = Agent(Settings(_env_file=None, chroma_path=str(tmp_path)))
    result = agent.run(Question(question="삼성전자 2024 영업이익 전년 대비 증가"))
    assert len(result.financials) == 2
    assert result.financials[-1]["profit_growth_pct"] == "80.00"
    assert "MOCK" in result.answer
    assert "validated" in result.trace
    assert all(s.mode == "mock" and not s.url for s in result.sources)


def test_graph_retrieval(tmp_path):
    agent = Agent(Settings(_env_file=None, chroma_path=str(tmp_path), rag_max_distance=1))
    result = agent.run(Question(question="SK하이닉스 2024년 실적 변화 원인을 공시 근거로 설명"))
    assert result.evidence
    assert "disclosure_tool" in result.trace
    assert all(hit["quote"] in hit["text"] for hit in result.evidence)


def test_missing_and_errors(tmp_path):
    class Broken:
        def financial(self, *args):
            raise DataError("API 테스트 오류")

    result = Agent(Settings(_env_file=None), financial_client=Broken()).run(
        Question(question="삼성전자 2024 매출")
    )
    assert not result.financials
    assert "API 테스트 오류" in result.warnings
    assert "검증 가능한 답변을 생성할 수 없습니다" in result.answer


def test_live_requires_key():
    with pytest.raises(ValueError, match="DART_API_KEY"):
        Agent(Settings(_env_file=None, finsight_mode="live", dart_api_key=""))


def test_store_failure_keeps_financials():
    from chromadb.errors import InternalError

    class BrokenStore:
        def search(self, *args):
            raise InternalError("unsafe details")

    result = Agent(Settings(_env_file=None), store=BrokenStore()).run(
        Question(question="삼성전자 2024 실적 원인")
    )
    assert len(result.financials) == 1
    assert not result.evidence
    assert any("저장소" in w for w in result.warnings)
    assert "unsafe" not in result.model_dump_json()


def test_forged_evidence_rejected():
    from finsight.mock import mock_documents

    text, source = mock_documents()[0]

    class WrongScope:
        def search(self, *args):
            return [{"id": "bad", "text": text, "source": source, "distance": 0.1}]

    result = Agent(Settings(_env_file=None), store=WrongScope()).run(
        Question(question="SK하이닉스 2024 실적 원인")
    )
    assert not result.evidence
    assert any("범위를 벗어난" in w for w in result.warnings)


def test_separate_basis_decimal_format():
    result = Agent(Settings(_env_file=None)).run(Question(question="삼성전자 2025 별도 매출"))
    assert result.financials[0]["basis"] == "OFS"
    assert "105,600,000,000원" in result.answer


def test_unavailable_growth_is_not_formatted_as_a_percentage():
    result = Agent(Settings(_env_file=None)).run(Question(question="삼성전자 2024 매출"))
    assert result.financials[0]["revenue_growth_pct"] is None
    assert "매출 증가율 산출 불가," in result.answer
    assert "산출 불가%" not in result.answer
