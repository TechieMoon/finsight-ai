import json
from pathlib import Path
from uuid import uuid4

from finsight.config import Settings
from finsight.models import Question, now_iso
from finsight.workflow import Agent


def main():
    cases = json.loads(Path("evaluation/questions.json").read_text(encoding="utf-8"))
    rows = []
    # Keep local evaluation DB until process exit; Windows Chroma mmap handles prevent early deletion.
    directory = Path("data/evaluations") / uuid4().hex
    directory.mkdir(parents=True)
    if directory.exists():
        agent = Agent(Settings(_env_file=None, finsight_mode="mock", chroma_path=str(directory)))
        for case in cases:
            answer = agent.run(Question(question=case["question"]))
            checks = {
                "route": answer.route == case["route"],
                "row_count": len(answer.financials) == case["rows"],
                "mock_label": "MOCK" in answer.answer and answer.mode == "mock",
                "citation_integrity": all(h["quote"] in h["text"] for h in answer.evidence),
                "source_scope": all(s.mode == "mock" and not s.url for s in answer.sources),
            }
            if case["id"] in [3, 10]:
                checks["retrieved_expected_scope"] = bool(answer.evidence)
            if case["id"] == 12:
                checks["abstained_no_evidence"] = not answer.evidence and bool(answer.warnings)
            if case["id"] == 2:
                checks["exact_profit_growth"] = answer.financials[-1]["profit_growth_pct"] == "80.00"
            if case["id"] == 7:
                checks["loss_to_profit"] = answer.financials[-1]["profit_growth_note"] == "흑자 전환"
            rows.append(
                {**case, "actual_route": answer.route, "checks": checks, "passed": all(checks.values())}
            )
    report = {
        "executed_at": now_iso(),
        "mode": "mock",
        "total": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "limitations": "Synthetic fixtures and hash embeddings only. Not live financial accuracy or semantic RAG quality.",
        "cases": rows,
    }
    Path("evaluation/results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Mock evaluation: {report['passed']}/{report['total']}")
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
