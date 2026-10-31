from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

COMPANIES = {"삼성전자": "005930", "SK하이닉스": "000660"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    basis: Literal["CFS", "OFS"] = "CFS"

    @field_validator("question")
    @classmethod
    def clean(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2 or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("질문은 2자 이상이며 제어 문자를 포함할 수 없습니다.")
        return value


class Source(BaseModel):
    title: str
    receipt: str
    url: str
    company: str
    year: int
    reference_date: str
    retrieved_at: str
    mode: Literal["mock", "live"]


class Financial(BaseModel):
    company: str
    year: int
    basis: Literal["CFS", "OFS"]
    revenue: Decimal | None
    operating_profit: Decimal | None
    currency: str = "KRW"
    period_start: str
    period_end: str
    source: Source


class Answer(BaseModel):
    mode: Literal["mock", "live"]
    route: str
    answer: str
    financials: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieved_at: str = Field(default_factory=now_iso)
    trace: list[str] = Field(default_factory=list)
