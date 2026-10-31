from fastapi.testclient import TestClient

from finsight.api import create_app
from finsight.config import Settings


def test_api(tmp_path):
    app = create_app(Settings(_env_file=None, chroma_path=str(tmp_path)))
    with TestClient(app) as client:
        assert client.get("/health").json()["mode"] == "mock"
        response = client.post("/analyze", json={"question": "두 기업의 2023~2025년 매출 비교"})
        assert response.status_code == 200
        assert len(response.json()["financials"]) == 6
        assert client.post("/analyze", json={"question": " "}).status_code == 422
        assert client.post("/analyze", json={"question": "가" * 1001}).status_code == 422
        assert (
            client.post("/analyze", json={"question": "삼성전자 매출", "basis": "invalid"}).status_code == 422
        )


def test_api_rate_limit():
    with TestClient(create_app(Settings(_env_file=None, api_calls_per_minute=1))) as client:
        assert client.post("/analyze", json={"question": "삼성전자 2024 매출"}).status_code == 200
        assert client.post("/analyze", json={"question": "삼성전자 2024 매출"}).status_code == 429
