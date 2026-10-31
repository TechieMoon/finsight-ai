"""Evaluation-only tests: missing gold must never produce an accuracy claim."""

import pytest

from scripts import baseline


def case(id_="R01", evidence=None, refusal=False):
    return {
        "id": id_,
        "status": "completed",
        "retrieved_candidates": [{"id": "a"}, {"id": "b"}],
        "result": {"evidence": evidence or []},
        "observed": {"explicit_evidence_refusal": refusal},
    }


def review(id_="R01", support=True, gold=None, judgments=None):
    return {
        "id": id_,
        "status": "reviewed",
        "reviewer": "test-fixture-only",
        "reviewed_at": "2026-10-29",
        "expected_support": support,
        "gold_complete": True,
        "gold_relevant_chunk_ids": gold or [],
        "quote_support": judgments or {},
    }


def test_no_human_gold_means_unknown_not_perfect():
    metrics = baseline.evaluate_rag_metrics([case()], [{"id": "R01", "status": "pending"}])
    assert metrics["recall_at_3_macro"]["value"] is None
    assert metrics["adopted_evidence_precision"]["value"] is None
    assert metrics["insufficient_evidence_refusal_rate"]["value"] is None


def test_recall_uses_gold_denominator_and_counts_missing_evidence():
    metrics = baseline.evaluate_rag_metrics([case()], [review(gold=["a", "z"])])
    assert metrics["recall_at_3_macro"]["value"] == 0.5


def test_quotes_in_same_chunk_need_separate_support_judgments():
    first = {"id": "a", "quote": "A relevant quote from the same chunk."}
    second = {"id": "a", "quote": "An irrelevant quote from the same chunk."}
    metrics = baseline.evaluate_rag_metrics(
        [case(evidence=[first, second])],
        [review(judgments={baseline.quote_key(first): True, baseline.quote_key(second): False})],
    )
    assert metrics["adopted_evidence_precision"]["value"] == 0.5


def test_missing_quotes_do_not_count_as_correct_precision():
    metrics = baseline.evaluate_rag_metrics([case(refusal=True)], [review(support=False)])
    assert metrics["adopted_evidence_precision"]["value"] is None
    assert metrics["insufficient_evidence_refusal_rate"]["value"] == 1.0


def test_unindexed_controls_do_not_inflate_refusal_accuracy():
    c = {**case(refusal=True), "group": "unindexed_control"}
    metrics = baseline.evaluate_rag_metrics([c], [review(support=False)])
    assert metrics["insufficient_evidence_refusal_rate"]["value"] is None


def test_incomplete_gold_does_not_create_recall():
    r = {**review(gold=["a"]), "gold_complete": False}
    assert baseline.evaluate_rag_metrics([case()], [r])["recall_at_3_macro"]["value"] is None


def test_independent_rational_calculation_and_null_states():
    assert baseline.reference_percent("18", "120") == "15.00"
    assert baseline.reference_growth("18", "10") == "80.00"
    assert baseline.reference_growth("15", "-5") is None
    assert baseline.reference_percent("1", "0") is None


def test_writer_refuses_secret_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(baseline, "secrets", lambda: ["fixture-sensitive-token"])
    target = tmp_path / "unsafe.json"
    with pytest.raises(ValueError, match="credential"):
        baseline.write_json(target, {"message": "fixture-sensitive-token"})
    assert not target.exists()


def test_variants_cannot_overwrite_baseline_or_escape_report_directory(tmp_path):
    assert baseline.experiment_directory(tmp_path, "baseline") == tmp_path
    assert baseline.experiment_directory(tmp_path, "evidence-v1") == tmp_path / "variants" / "evidence-v1"
    with pytest.raises(ValueError):
        baseline.experiment_directory(tmp_path, "../../outside")


@pytest.mark.parametrize(
    "unit,cover_year,expected_status",
    [
        ("백만원", 2024, "verified_original_automatic"),
        ("천원", 2024, "pending_original_review"),
        ("백만원", 2023, "pending_original_review"),
    ],
)
def test_original_reference_is_independent_and_requires_period_unit(
    monkeypatch, tmp_path, unit, cover_year, expected_status
):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    monkeypatch.setattr(baseline, "secrets", list)
    raw, report = baseline.locations("fixture")
    source = raw / "document.xml"
    source.write_text(
        f"<DOCUMENT>사업보고서 사 업 보 고 서 (제 1 기) 사업연도 {cover_year}년 01월 01일 부터 "
        f"{cover_year}년 12월 31일 까지</DOCUMENT>",
        encoding="utf-8",
    )
    directory = raw / "scope"
    directory.mkdir()
    baseline.write_json(
        report / "manifest.json",
        {
            "snapshots": [
                {
                    "company": "fixture",
                    "year": 2024,
                    "directory": directory.relative_to(tmp_path).as_posix(),
                    "financial": {"revenue": "999999999", "source": {"receipt": "20250319000665"}},
                    "documents": [
                        {"sha256": "source-fixture", "path": source.relative_to(tmp_path).as_posix()}
                    ],
                }
            ]
        },
    )
    baseline.write_json(
        directory / "original-tables.json",
        [
            {
                "preceding": [f"(단위: {unit})", "가. 요약연결재무정보"],
                "rows": [["구분", "제1기"], ["매출액", "120"], ["영업이익", "18"]],
                "document_sha256": "source-fixture",
                "table_index": 1,
            }
        ],
    )
    baseline.build_references("fixture")
    reference = baseline.read_json(report / "financial-references.json")[0]
    assert reference["status"] == expected_status
    if expected_status == "verified_original_automatic":
        assert reference["revenue"] == "120000000"
        assert reference["revenue"] != "999999999"
