import io
import zipfile

import httpx
import pytest

from finsight.config import Settings
from finsight.dart import DartClient, Limiter, RateLimit, unzip_xml
from finsight.finance import DataError


def client(handler):
    return DartClient(
        Settings(_env_file=None, dart_api_key="test-secret"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("status", ["010", "011", "020", "100", "800"])
def test_dart_api_errors(status):
    dart = client(lambda request: httpx.Response(200, json={"status": status, "message": "unsafe"}))
    with pytest.raises(DataError) as error:
        dart.json("list.json", {})
    assert "unsafe" not in str(error.value)
    assert "test-secret" not in str(error.value)


def test_no_data():
    assert client(lambda r: httpx.Response(200, json={"status": "013"})).json("list.json", {}) == []


def test_retry_success():
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"status": "000", "list": []})
        )

    assert client(handler).json("list.json", {}) == []
    assert len(calls) == 3


def test_timeout_redacted():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("test-secret", request=request)

    with pytest.raises(DataError) as error:
        client(handler).json("list.json", {})
    assert len(calls) == 3
    assert "test-secret" not in str(error.value)


def test_limiter():
    limiter = Limiter(1)
    limiter.acquire()
    with pytest.raises(RateLimit):
        limiter.acquire()


def test_corp_code():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "CORPCODE.xml",
            "<result><list><stock_code>005930</stock_code><corp_code>00126380</corp_code></list></result>",
        )
    dart = client(lambda r: httpx.Response(200, content=buffer.getvalue()))
    assert dart.corp_code("삼성전자") == "00126380"
    assert dart.corp_code("삼성전자") == "00126380"


def test_invalid_zip():
    with pytest.raises(DataError):
        unzip_xml(b"<result><status>010</status></result>")
