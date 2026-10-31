import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from finsight.finance import DataError
from finsight.rag import chunks, clean_xml, normalize_dart_xml_text

manifest = json.loads(Path("evaluation/baseline/2026-10-29/manifest.json").read_text(encoding="utf-8"))
report = {
    "executed_at": datetime.now(UTC).isoformat(),
    "kind": "baseline_xml_snapshot_regression",
    "cases": [],
}
for item in manifest["snapshots"]:
    combined = []
    for doc in item["documents"]:
        p = Path(doc["path"])
        raw = p.read_bytes()
        same = hashlib.sha256(raw).hexdigest() == doc["sha256"]
        row = {
            "company": item["company"],
            "year": item["year"],
            "file": p.name,
            "sha256_matches_baseline": same,
        }
        assert same
        try:
            text = clean_xml(raw)
            assert text
            raw_text = raw.decode("utf-8")
            terms = {name: name in text for name in ["S&P", "R&D", "SK E&S"] if name in raw_text}
            assert all(terms.values()), terms
            combined.append(text)
            row.update(
                status="passed",
                characters=len(text),
                literal_business_terms=terms,
                bare_ampersands_escaped=normalize_dart_xml_text(raw).count(b"&amp;") - raw.count(b"&amp;"),
            )
        except (DataError, AssertionError, UnicodeError) as exc:
            row.update(
                status="failed",
                error_type=type(exc).__name__,
                cause_type=type(exc.__cause__).__name__,
                position=getattr(exc.__cause__, "position", None),
            )
        report["cases"].append(row)
    print(
        item["company"], item["year"], "documents", len(combined), "chunks", len(chunks(" ".join(combined)))
    )
report["passed"] = sum(r["status"] == "passed" for r in report["cases"])
report["total"] = len(report["cases"])
out = Path("evaluation/xml-repair-2026-10-31")
out.mkdir(exist_ok=True)
(out / "snapshot-regression.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Actual original XML", report["passed"], "/", report["total"])
assert report["passed"] == report["total"]
