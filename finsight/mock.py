from decimal import Decimal

from finsight.finance import DataError
from finsight.models import Financial, Source, now_iso

# Deliberately synthetic small numbers. These are NOT historical corporate results.
VALUES = {
    "삼성전자": {2022: (90, 9), 2023: (100, 10), 2024: (120, 18), 2025: (132, 22)},
    "SK하이닉스": {2022: (45, 4), 2023: (50, -5), 2024: (75, 15), 2025: (90, 18)},
}


class MockClient:
    def financial(self, company: str, year: int, basis: str) -> Financial:
        pair = VALUES.get(company, {}).get(year)
        if pair is None:
            raise DataError(f"MOCK: {company} {year} 합성 데이터가 없습니다.")
        factor = Decimal(1000000000) * (Decimal("0.8") if basis == "OFS" else 1)
        return Financial(
            company=company,
            year=year,
            basis=basis,
            revenue=Decimal(pair[0]) * factor,
            operating_profit=Decimal(pair[1]) * factor,
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            source=Source(
                title=f"MOCK 합성 재무 fixture {company} {year}",
                receipt=f"MOCK-{company}-{year}",
                url="",
                company=company,
                year=year,
                reference_date=f"{year}-12-31",
                retrieved_at=now_iso(),
                mode="mock",
            ),
        )


def mock_documents() -> list[tuple[str, dict]]:
    docs = []
    for company in VALUES:
        for year in range(2023, 2026):
            source = Source(
                title=f"MOCK {company} {year} 사업보고서 대용 문서",
                receipt=f"MOCK-{company}-{year}",
                url="",
                company=company,
                year=year,
                reference_date=f"{year}-12-31",
                retrieved_at=now_iso(),
                mode="mock",
            )
            docs.append(
                (
                    (
                        f"[합성 테스트 문서: 실제 공시 아님] {company} {year}년 실적 변화 원인. "
                        "메모리 제품 수요 증가와 제품 판매 가격 상승이 매출 및 영업이익 변화에 영향을 주었다. "
                        "이 설명은 검색 테스트를 위한 가상 시나리오이며 실제 기업 사실을 의미하지 않는다."
                    ),
                    source.model_dump(),
                )
            )
    return docs
