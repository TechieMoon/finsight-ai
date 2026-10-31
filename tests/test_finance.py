from decimal import Decimal

import pytest

from finsight.finance import DataError, amount, compare, growth, normalize, percent
from finsight.mock import MockClient


@pytest.mark.parametrize("raw,expected", [("1,200", "1200"), ("(45)", "-45"), ("-", None), (None, None)])
def test_amount(raw, expected):
    assert amount(raw) == (Decimal(expected) if expected else None)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "abc"])
def test_invalid_amount(raw):
    with pytest.raises(DataError):
        amount(raw)


def test_calculation_edges():
    assert percent(Decimal(-5), Decimal(50)) == Decimal("-10.00")
    assert percent(Decimal(1), Decimal(0)) is None
    assert growth(Decimal(18), Decimal(10))[0] == Decimal("80.00")
    assert growth(Decimal(15), Decimal(-5)) == (None, "흑자 전환")
    assert growth(Decimal(2), Decimal(0))[0] is None
    assert growth(None, Decimal(2))[0] is None


def test_comparison():
    client = MockClient()
    records = [client.financial("삼성전자", year, "CFS") for year in [2023, 2024]]
    result = compare(records)
    assert result[1]["operating_margin_pct"] == "15.00"
    assert result[1]["revenue_growth_pct"] == "20.00"
    assert result[1]["profit_growth_pct"] == "80.00"
    with pytest.raises(DataError):
        compare([*records, records[0]])
    with pytest.raises(DataError):
        compare([records[0], client.financial("SK하이닉스", 2023, "OFS")])


def rows():
    common = {
        "sj_div": "IS",
        "bsns_year": "2024",
        "reprt_code": "11011",
        "rcept_no": "20250311000001",
        "currency": "KRW",
    }
    return [
        {**common, "account_id": "ifrs-full_Revenue", "thstrm_amount": "120", "frmtrm_amount": "999"},
        {**common, "account_id": "dart_OperatingIncomeLoss", "thstrm_amount": "18"},
    ]


def test_normalize_current_period_only():
    result = normalize(rows(), "삼성전자", 2024, "CFS")
    assert result.revenue == Decimal(120)
    assert result.period_end == "2024-12-31"
    assert "20250311000001" in result.source.url


def test_duplicate_conflict():
    data = rows()
    data.append({**data[0], "thstrm_amount": "121"})
    with pytest.raises(DataError, match="중복"):
        normalize(data, "삼성전자", 2024, "CFS")


@pytest.mark.parametrize(
    "field,value", [("bsns_year", "2023"), ("reprt_code", "11012"), ("fs_div", "OFS"), ("currency", "USD")]
)
def test_period_basis_currency_validation(field, value):
    data = rows()
    data[0][field] = value
    with pytest.raises(DataError):
        normalize(data, "삼성전자", 2024, "CFS")


def test_incomplete_current_period():
    data = rows()
    data[0]["thstrm_dt"] = "2024.01.01 ~ 2024.09.30"
    with pytest.raises(DataError, match="12개월"):
        normalize(data, "삼성전자", 2024, "CFS")
