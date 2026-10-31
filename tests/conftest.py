import pytest


@pytest.fixture(autouse=True)
def isolate_offline_configuration(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("FINSIGHT_MODE", "mock")
    monkeypatch.setenv("DART_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
