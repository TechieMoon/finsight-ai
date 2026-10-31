import os

import pytest

from finsight.config import Settings
from finsight.dart import DartClient
from finsight.rag import DisclosureStore, ingest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1", reason="opt-in: RUN_LIVE_TESTS=1 and real API keys required"
    ),
]


def test_live_dart():
    config = Settings(finsight_mode="live")
    data = DartClient(config).financial("삼성전자", 2024, "CFS")
    assert data.revenue is not None and data.revenue > 0
    assert data.source.mode == "live"
    assert data.source.receipt in data.source.url


def test_live_ingestion_and_semantic_search(tmp_path):
    config = Settings(finsight_mode="live", chroma_path=str(tmp_path))
    config.require_live(rag=True)
    store = DisclosureStore(config)
    result = ingest(DartClient(config), store, "SK하이닉스", 2024)
    assert result["chunks"] > 0
    hits = store.search("메모리 수요와 판매가격이 실적에 미친 영향", "SK하이닉스", 2024)
    assert hits
    assert all(h["source"]["receipt"] == result["receipt"] for h in hits)
