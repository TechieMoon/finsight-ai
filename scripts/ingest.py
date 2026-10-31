"""Explicit, bounded ingestion from the official OpenDART document API only."""

import argparse
import json

from finsight.config import settings
from finsight.dart import DartClient
from finsight.models import COMPANIES
from finsight.rag import DisclosureStore, ingest


def main():
    parser = argparse.ArgumentParser(description="공식 DART 사업보고서 수집 (임베딩 비용 발생)")
    parser.add_argument("--company", choices=list(COMPANIES), required=True)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not 2015 <= args.year < datetime.now(ZoneInfo("Asia/Seoul")).year:
        parser.error("완료된 회계연도만 수집할 수 있습니다.")
    config = settings()
    if config.finsight_mode != "live":
        parser.error("실제 공시 수집은 FINSIGHT_MODE=live에서만 실행하세요.")
    config.require_live(rag=True)
    result = ingest(DartClient(config), DisclosureStore(config), args.company, args.year)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
