import re
from decimal import Decimal, InvalidOperation

from finsight.models import Financial, Source


class DataError(ValueError):
    """Safe, user-readable data quality error; never includes request URLs or keys."""


def amount(value: str | None) -> Decimal | None:
    if value is None or value.strip() in {"", "-"}:
        return None
    text = value.strip().replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise DataError("재무 금액의 숫자 형식을 확인할 수 없습니다.") from exc
    if not result.is_finite():
        raise DataError("유한하지 않은 금액입니다.")
    return result


def percent(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return (numerator / denominator * 100).quantize(Decimal("0.01"))


def growth(current: Decimal | None, previous: Decimal | None) -> tuple[Decimal | None, str]:
    if current is None or previous is None:
        return None, "결측값으로 증가율 산출 불가"
    if previous == 0:
        return None, "전기 값이 0이므로 증가율 산출 불가"
    if previous < 0:
        return None, "흑자 전환" if current > 0 else "적자 지속/손익분기 (증가율 미산출)"
    return percent(current - previous, previous), "적자 전환" if current < 0 else "정상"


def normalize(rows: list[dict], company: str, year: int, basis: str) -> Financial:
    selected = [r for r in rows if r.get("sj_div") in {"IS", "CIS"}]
    if not selected:
        raise DataError("연간 손익계산서가 없습니다.")
    for row in selected:
        if row.get("bsns_year") != str(year) or row.get("reprt_code") != "11011":
            raise DataError("요청한 연간 회계기간과 응답이 다릅니다.")
        if row.get("fs_div", basis) != basis or row.get("currency", "KRW") != "KRW":
            raise DataError("연결/별도 구분 또는 통화가 일치하지 않습니다.")
        if row.get("thstrm_dt"):
            dates = re.findall(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", row["thstrm_dt"])
            expected = [(str(year), "01", "01"), (str(year), "12", "31")]
            if dates != expected:
                raise DataError("당기 손익의 기간이 요청한 12개월 회계연도와 다릅니다.")
    receipts = {r.get("rcept_no", "") for r in selected}
    if len(receipts) != 1 or not re.fullmatch(r"\d{14}", next(iter(receipts))):
        raise DataError("접수번호가 없거나 여러 공시가 혼합되었습니다.")

    def extract(ids: set[str], names: set[str]) -> Decimal | None:
        matches = [r for r in selected if r.get("account_id") in ids]
        if not matches:
            matches = [r for r in selected if re.sub(r"\s", "", r.get("account_nm", "")) in names]
        # Only current-period amount. Never combine frmtrm/thstrm_add with annual thstrm.
        values = {amount(r.get("thstrm_amount")) for r in matches}
        if len(values) > 1:
            raise DataError("중복 재무 항목의 금액이 서로 달라 사용하지 않습니다.")
        return next(iter(values), None)

    receipt = next(iter(receipts))
    from finsight.models import now_iso

    return Financial(
        company=company,
        year=year,
        basis=basis,
        revenue=extract({"ifrs-full_Revenue", "ifrs_Revenue"}, {"매출액", "수익(매출액)", "영업수익"}),
        operating_profit=extract({"dart_OperatingIncomeLoss"}, {"영업이익", "영업이익(손실)", "영업손익"}),
        period_start=f"{year}-01-01",
        period_end=f"{year}-12-31",
        source=Source(
            title=f"{company} {year} 사업보고서 재무제표",
            receipt=receipt,
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            company=company,
            year=year,
            reference_date=f"{year}-12-31",
            retrieved_at=now_iso(),
            mode="live",
        ),
    )


def compare(records: list[Financial]) -> list[dict]:
    if len({(r.basis, r.currency) for r in records}) > 1:
        raise DataError("서로 다른 재무제표 기준 또는 통화는 비교할 수 없습니다.")
    if len({(r.company, r.year) for r in records}) != len(records):
        raise DataError("동일 기업·연도의 중복 관측값입니다.")
    lookup = {(r.company, r.year): r for r in records}
    result = []
    for record in sorted(records, key=lambda r: (r.company, r.year)):
        previous = lookup.get((record.company, record.year - 1))
        rev_growth, rev_note = growth(record.revenue, previous.revenue if previous else None)
        op_growth, op_note = growth(record.operating_profit, previous.operating_profit if previous else None)
        margin = percent(record.operating_profit, record.revenue)
        result.append(
            {
                "company": record.company,
                "year": record.year,
                "basis": record.basis,
                "currency": record.currency,
                "revenue": str(record.revenue) if record.revenue is not None else None,
                "operating_profit": str(record.operating_profit)
                if record.operating_profit is not None
                else None,
                "operating_margin_pct": str(margin) if margin is not None else None,
                "revenue_growth_pct": str(rev_growth) if rev_growth is not None else None,
                "profit_growth_pct": str(op_growth) if op_growth is not None else None,
                "revenue_growth_note": rev_note,
                "profit_growth_note": op_note,
                "period_start": record.period_start,
                "period_end": record.period_end,
                "receipt": record.source.receipt,
            }
        )
    return result
