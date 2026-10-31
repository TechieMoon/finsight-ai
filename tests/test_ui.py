from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from finsight.config import Settings
from finsight.models import Question
from finsight.workflow import Agent


def test_ui_question_result_table_chart_sources(monkeypatch):
    answer = Agent(Settings(_env_file=None)).run(Question(question="두 기업의 2023~2025년 매출 비교"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"mode": "mock"}))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200,
            json=answer.model_dump(mode="json"),
            request=httpx.Request("POST", "http://localhost/analyze"),
        ),
    )
    app = AppTest.from_file(str(Path("ui/app.py").resolve())).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 6
    assert any("MOCK" in warning.value for warning in app.warning)
    assert any("접수번호" in item.value for item in app.text)


def test_ui_error_clears_stale_result(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"mode": "mock"}))

    def fail(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx, "post", fail)
    app = AppTest.from_file(str(Path("ui/app.py").resolve())).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.error
    assert not app.dataframe
