from types import SimpleNamespace

import pytest

from finsight.config import Settings
from finsight.finance import DataError
from finsight.workflow import Agent, SelectedQuotes


def test_model_invented_quote_is_discarded(monkeypatch):
    text = "메모리 수요 증가와 판매가격 상승이 해당 회계연도 매출 증가에 영향을 주었습니다."

    def parse(**kwargs):
        assert kwargs["messages"][0]["role"] == "system"
        assert "신뢰하지 않는 데이터" in kwargs["messages"][0]["content"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=SelectedQuotes(
                            quotes=[text, "원문에 없는 가상의 매출 수치를 만들어서 제시하는 문장입니다."]
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(
        "finsight.workflow.OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
    )
    agent = Agent(
        Settings(_env_file=None, finsight_mode="live", openai_api_key="test"), financial_client=object()
    )
    selected = agent.choose_quotes("실적 변화 원인", [{"id": "source-1", "text": text}])
    assert len(selected) == 1
    assert selected[0]["quote"] == text


def test_model_error_is_redacted(monkeypatch):
    def parse(**kwargs):
        raise RuntimeError("sensitive-key-must-not-appear")

    monkeypatch.setattr(
        "finsight.workflow.OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
    )
    agent = Agent(
        Settings(_env_file=None, finsight_mode="live", openai_api_key="test"), financial_client=object()
    )
    with pytest.raises(DataError) as error:
        agent.choose_quotes("실적 원인", [{"id": "1", "text": "문서"}])
    assert "sensitive" not in str(error.value)
