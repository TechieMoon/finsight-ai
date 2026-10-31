"""Read-only service baseline. Live snapshots stay in ignored data/; reports contain no credentials.

This module never modifies finsight/, production Chroma collections, or service configuration.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import sys
import time
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = "2026-10-29"


def timestamp():
    return datetime.now(UTC).isoformat()


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


def secrets():
    from finsight.config import Settings

    config = Settings()
    values = [config.dart_api_key.get_secret_value(), config.openai_api_key.get_secret_value()]
    values.extend(
        v for k, v in os.environ.items() if re.search(r"KEY|SECRET|TOKEN|PASSWORD", k, re.IGNORECASE)
    )
    return [v for v in values if len(v) >= 12]


def write_json(path: Path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if any(secret in text for secret in secrets()):
        raise ValueError("Refusing output containing a credential")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def locations(run):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run):
        raise ValueError("run must be a simple directory name")
    raw = ROOT / "data" / "baseline" / run
    report = ROOT / "evaluation" / "baseline" / run
    raw.mkdir(parents=True, exist_ok=True)
    report.mkdir(parents=True, exist_ok=True)
    return raw, report


def environment():
    names = ["langgraph", "openai", "chromadb", "httpx", "pydantic", "pytest"]
    return {
        "python": platform.python_version(),
        "platform": sys.platform,
        "packages": {name: version(name) for name in names},
        "service_sha256": {p.name: digest(p.read_bytes()) for p in sorted((ROOT / "finsight").glob("*.py"))},
    }


def collect(run):
    from finsight.config import Settings
    from finsight.dart import DartClient
    from finsight.models import COMPANIES
    from finsight.rag import clean_xml

    raw, report = locations(run)
    config = Settings(finsight_mode="live")
    config.require_live()

    class RecordingDart(DartClient):
        last_rows = None

        def json(self, endpoint, params):
            result = super().json(endpoint, params)
            if endpoint == "fnlttSinglAcntAll.json":
                self.last_rows = result
            return result

    dart = RecordingDart(config)
    manifest = {
        "started_at": timestamp(),
        "origin": "live_opendart",
        "environment": environment(),
        "basis": "CFS",
        "snapshots": [],
        "errors": [],
    }
    for company, stock in COMPANIES.items():
        for year in [2022, 2023, 2024, 2025]:
            name = f"{stock}-{year}-CFS"
            existing = raw / name / "snapshot.json"
            if existing.exists():
                item = read_json(existing)
                manifest["snapshots"].append(item)
                print(f"Reused live snapshot: {stock} {year}", flush=True)
                continue
            directory = raw / name
            directory.mkdir(exist_ok=True)
            try:
                if (directory / "financial-api.json").exists():
                    from finsight.finance import normalize

                    financial = normalize(read_json(directory / "financial-api.json"), company, year, "CFS")
                else:
                    financial = dart.financial(company, year, "CFS")
                    write_json(directory / "financial-api.json", dart.last_rows)
                documents = dart.document(financial.source.receipt)
                files = []
                text_parts = []
                parser_errors = []
                for i, document in enumerate(documents):
                    if any(secret.encode() in document for secret in secrets()):
                        raise ValueError("credential found in source document")
                    path = directory / f"document-{i}.xml"
                    path.write_bytes(document)
                    files.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(document)})
                    try:
                        text_parts.append(clean_xml(document))
                    except Exception as exc:  # noqa: BLE001 -- persist stage/type without provider exception text
                        parser_errors.append(
                            {
                                "file": path.name,
                                "stage": "service_clean_xml",
                                "error_type": type(exc).__name__,
                                "status": "failed",
                            }
                        )
                text = " ".join(text_parts)
                (directory / "cleaned.txt").write_text(text, encoding="utf-8")
                item = {
                    "company": company,
                    "stock_code": stock,
                    "year": year,
                    "basis": "CFS",
                    "origin": "live_opendart",
                    "captured_at": timestamp(),
                    "financial": financial.model_dump(mode="json"),
                    "documents": files,
                    "service_parser_errors": parser_errors,
                    "cleaned_sha256": digest(text.encode()),
                    "directory": directory.relative_to(ROOT).as_posix(),
                }
                write_json(existing, item)
                manifest["snapshots"].append(item)
                print(
                    f"Captured live financial + original: {stock} {year}, receipt={financial.source.receipt}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 -- redact credentials at evaluation boundary
                # Never serialize SDK/HTTP exception text, request URLs, headers, or config.
                manifest["errors"].append(
                    {
                        "company": company,
                        "year": year,
                        "stage": "collect",
                        "error_type": type(exc).__name__,
                        "status": "incomplete",
                    }
                )
                print(f"Collection incomplete: {stock} {year} ({type(exc).__name__})", flush=True)
            write_json(report / "manifest.json", manifest)
    dart.client.close()
    manifest["finished_at"] = timestamp()
    write_json(report / "manifest.json", manifest)
    return manifest


def inspect_tables(run):
    """Expose original table context, not automatically asserted financial truth."""
    from bs4 import BeautifulSoup

    raw, report = locations(run)
    manifest = read_json(report / "manifest.json")
    index = []
    for snapshot in manifest["snapshots"]:
        tables = []
        for doc in snapshot["documents"]:
            data = (ROOT / doc["path"]).read_bytes()
            # Diagnostics preserve rows/cells from original XML; no service cleaner reuse.
            import warnings

            from bs4 import XMLParsedAsHTMLWarning

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
                soup = BeautifulSoup(data, "html.parser")
            for i, table in enumerate(soup.find_all("table")):
                rows = [
                    [
                        cell.get_text(" ", strip=True)
                        for cell in row.find_all(["td", "th", "te", "tu"], recursive=False)
                    ]
                    for row in table.find_all("tr")
                ]
                if not any(
                    any(re.search(r"매출액|영업이익|영업손익|영업손실", cell) for cell in row) for row in rows
                ):
                    continue
                preceding = []
                for tag in table.find_all_previous(["title", "p", "table"], limit=5):
                    preceding.append(tag.get_text(" ", strip=True)[:1200])
                tables.append(
                    {"document_sha256": doc["sha256"], "table_index": i, "preceding": preceding, "rows": rows}
                )
        path = raw / Path(snapshot["directory"]).name / "original-tables.json"
        write_json(path, tables)
        index.append(
            {
                "company": snapshot["company"],
                "year": snapshot["year"],
                "candidate_tables": len(tables),
                "path": path.relative_to(ROOT).as_posix(),
            }
        )
    write_json(report / "original-table-index.json", index)
    print(json.dumps(index, ensure_ascii=False, indent=2))


def reference_percent(numerator, denominator):
    """Independent rational reference, never calls finsight.finance percent/growth."""
    if numerator is None or denominator is None or Decimal(denominator) <= 0:
        return None
    value = Fraction(Decimal(numerator)) / Fraction(Decimal(denominator)) * 100
    with localcontext() as context:
        context.prec = 60
        return str(
            (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
        )


def build_references(run):
    """Independent original-table extraction. It does not use API amounts as expected values."""
    _raw, report = locations(run)
    manifest = read_json(report / "manifest.json")
    refs = []
    for snapshot in manifest["snapshots"]:
        tables = read_json(ROOT / snapshot["directory"] / "original-tables.json")
        candidates = [t for t in tables if "요약연결재무정보" in " ".join(t["preceding"][:3])]
        reference = {
            "company": snapshot["company"],
            "year": snapshot["year"],
            "basis": "CFS",
            "receipt": snapshot["financial"]["source"]["receipt"],
            "status": "pending_original_review",
            "human_review": "pending",
        }
        if len(candidates) == 1:
            table = candidates[0]
            doc = next(d for d in snapshot["documents"] if d["sha256"] == table["document_sha256"])
            raw_text = (ROOT / doc["path"]).read_bytes().decode("utf-8")
            cover = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_text))[:5000]
            year = snapshot["year"]
            year_match = re.search(
                rf"사업연도\s*{year}년\s*01월\s*01일\s*부터\s*{year}년\s*12월\s*31일", cover
            )
            term = re.search(r"사\s*업\s*보\s*고\s*서\s*\(제\s*(\d+)\s*기\)", cover)
            first_header = " ".join(table["rows"][0][1:2])
            term_match = term and re.search(rf"제\s*{term[1]}\s*기", first_header)
            unit_match = re.search(r"단위\s*:\s*백만원", " ".join(table["preceding"][:2]))
            extracted = {}
            row_evidence = {}
            for metric, labels in {
                "revenue": {"매출액"},
                "operating_profit": {"영업이익", "영업이익(손실)", "영업손실"},
            }.items():
                matches = [r for r in table["rows"] if r and re.sub(r"\s", "", r[0]) in labels]
                if len(matches) == 1 and len(matches[0]) > 1:
                    cell = matches[0][1].strip().replace(",", "").replace("△", "-")
                    if re.fullmatch(r"\(?-?\d+\)?", cell):
                        value = Decimal("-" + cell[1:-1] if cell.startswith("(") else cell)
                        extracted[metric] = str(value * 1_000_000)
                        row_evidence[metric] = matches[0]
            reference.update(
                {
                    "table_index": table["table_index"],
                    "document_sha256": doc["sha256"],
                    "source_file": doc["path"],
                    "original_unit": "백만원",
                    "unit_multiplier": "1000000",
                    "column_index": 1,
                    "header": table["rows"][0],
                    "original_rows": row_evidence,
                    "context": table["preceding"][:3],
                    "period_evidence": year_match[0] if year_match else None,
                    "term_evidence": term[0] if term else None,
                    **extracted,
                }
            )
            if year_match and term_match and unit_match and len(extracted) == 2:
                reference["status"] = "verified_original_automatic"
        refs.append(reference)
    write_json(report / "financial-references.json", refs)
    print(
        "Original table references:",
        sum(r["status"] == "verified_original_automatic" for r in refs),
        "/",
        len(refs),
    )


def freeze_corpus(run):
    """Copy existing live embeddings, documents and IDs without re-embedding or writing the production DB."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    from finsight.config import Settings
    from finsight.rag import DisclosureStore

    raw, report = locations(run)
    if (report / "corpus-manifest.json").exists():
        print("Reusing frozen corpus; use a new run ID to capture a different corpus.")
        return
    config = Settings(finsight_mode="live")
    source = chromadb.PersistentClient(
        path=config.chroma_path, settings=ChromaSettings(anonymized_telemetry=False)
    )
    identity = "live-" + config.embedding_model
    name = "disclosures-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    existing = source.get_collection(name).get(include=["documents", "metadatas", "embeddings"])
    destination = DisclosureStore(config.model_copy(update={"chroma_path": str(raw / "chroma")}))
    groups = {}
    corpus = []
    for start in range(0, len(existing["ids"]), 100):
        stop = start + 100
        destination.collection.upsert(
            ids=existing["ids"][start:stop],
            documents=existing["documents"][start:stop],
            metadatas=existing["metadatas"][start:stop],
            embeddings=existing["embeddings"][start:stop],
        )
    for id_, text, meta in zip(existing["ids"], existing["documents"], existing["metadatas"]):
        if meta.get("mode") != "live":
            raise ValueError("Non-live data in baseline collection")
        key = f"{meta['company']}:{meta['year']}:{meta['receipt']}"
        groups[key] = groups.get(key, 0) + 1
        corpus.append({"id": id_, "text": text, "source": meta})
    corpus.sort(key=lambda row: row["id"])
    write_json(raw / "corpus.json", corpus)
    snapshot = {
        "captured_at": timestamp(),
        "origin": "existing_live_chroma",
        "collection": name,
        "embedding_model": config.embedding_model,
        "groups": groups,
        "chunks": len(corpus),
        "corpus_sha256": digest(json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()),
        "embedding_sha256": digest(existing["embeddings"].tobytes())
        if existing["embeddings"] is not None
        else None,
        "index_path": (raw / "chroma").relative_to(ROOT).as_posix(),
        "note": "Copied existing vectors. No ingestion or financial correctness implied.",
    }
    write_json(report / "corpus-manifest.json", snapshot)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


def reference_growth(current, previous):
    if current is None or previous is None or Decimal(previous) <= 0:
        return None
    return reference_percent(str(Decimal(current) - Decimal(previous)), previous)


def rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def quote_key(hit):
    return digest((hit["id"] + "\n" + hit["quote"]).encode())[:20]


def experiment_directory(report, variant):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", variant):
        raise ValueError("variant must be a simple directory name")
    destination = report if variant == "baseline" else report / "variants" / variant
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def evaluate_rag_metrics(cases, reviews):
    """No relevance/abstention accuracy without explicitly reviewed gold. No vacuous successes."""
    labels = {r["id"]: r for r in reviews if r.get("status") == "reviewed" and r.get("reviewer")}
    recalls = []
    supported, judged = 0, 0
    refused, unanswerable = 0, 0
    wrong_refusal, answerable = 0, 0
    for case in cases:
        if case.get("status") != "completed":
            continue
        label = labels.get(case["id"])
        if not label:
            continue
        if case.get("group") in {"unindexed_control", "partial_corpus_control"}:
            continue
        gold = label.get("gold_relevant_chunk_ids", [])
        selected = case["result"]["evidence"]
        if label.get("gold_complete") and label.get("expected_support") is True and gold:
            retrieved = {h["id"] for h in case["retrieved_candidates"]}
            recalls.append(len(set(gold) & retrieved) / len(set(gold)))
        for hit in selected:
            value = label.get("quote_support", {}).get(quote_key(hit))
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError("Quote support must be boolean or null")
                judged += 1
                supported += value
        if label.get("gold_complete") and label.get("expected_support") is False:
            unanswerable += 1
            refused += case["observed"]["explicit_evidence_refusal"]
        if label.get("gold_complete") and label.get("expected_support") is True:
            answerable += 1
            wrong_refusal += case["observed"]["explicit_evidence_refusal"]
    return {
        "recall_at_3_macro": {
            "value": sum(recalls) / len(recalls) if recalls else None,
            "reviewed_questions": len(recalls),
            "definition": "Per-scoped top-3 after production threshold; gold chunk set must be complete.",
        },
        "adopted_evidence_precision": rate(supported, judged),
        "insufficient_evidence_refusal_rate": rate(refused, unanswerable),
        "incorrect_refusal_rate": rate(wrong_refusal, answerable),
        "human_review_coverage": rate(sum(c["id"] in labels for c in cases), len(cases)),
    }


def run_rag(run, variant="baseline"):
    from finsight.config import Settings
    from finsight.finance import DataError
    from finsight.models import Question
    from finsight.rag import DisclosureStore
    from finsight.workflow import Agent

    raw, report = locations(run)
    manifest = read_json(report / "manifest.json")
    corpus_manifest = read_json(report / "corpus-manifest.json")
    questions = read_json(ROOT / "evaluation/baseline/questions.json")
    corpus = {row["id"]: row for row in read_json(raw / "corpus.json")}
    snapshots = {(s["company"], s["year"], s["basis"]): s["financial"] for s in manifest["snapshots"]}

    class FrozenFinancials:
        def financial(self, company, year, basis):
            found = snapshots.get((company, year, basis))
            if found is None:
                raise DataError("Baseline 실제 재무 스냅샷에 해당 범위가 없습니다.")
            # Replay raw live API rows through the CURRENT normalizer; not synthetic fixtures.
            from finsight.finance import normalize

            stock = next(
                s["stock_code"]
                for s in manifest["snapshots"]
                if (s["company"], s["year"], s["basis"]) == (company, year, basis)
            )
            rows = read_json(raw / f"{stock}-{year}-{basis}" / "financial-api.json")
            return normalize(rows, company, year, basis)

    config = Settings(finsight_mode="live", chroma_path=str(raw / "chroma"))
    config.require_live(rag=True)
    store = DisclosureStore(config)
    result_directory = experiment_directory(report, variant)
    output = result_directory / "rag-results.json"
    experiment = {
        "started_at": timestamp(),
        "mode": "live_corpus_with_live_openai",
        "financial_transport": "replay_of_captured_live_opendart_responses",
        "environment": environment(),
        "embedding_model": config.embedding_model,
        "llm_model": config.openai_model,
        "rag_max_distance": config.rag_max_distance,
        "top_k_per_scope": 3,
        "corpus_sha256": corpus_manifest["corpus_sha256"],
        "question_set_sha256": digest((ROOT / "evaluation/baseline/questions.json").read_bytes()),
        "cost_tokens": None,
        "cost_note": "Provider usage not instrumented; no cost estimate asserted.",
        "cases": [],
    }
    if output.exists():
        old = read_json(output)
        for key in [
            "corpus_sha256",
            "question_set_sha256",
            "environment",
            "llm_model",
            "embedding_model",
            "rag_max_distance",
        ]:
            if old[key] != experiment[key]:
                raise ValueError("Baseline configuration changed; use a new run ID")
        experiment = old
    completed = {c["id"] for c in experiment["cases"]}
    for question in questions:
        if question["id"] in completed:
            continue
        agent = Agent(config, financial_client=FrozenFinancials(), store=store)
        candidates = []
        start = time.perf_counter()
        try:
            answer = None
            for event in agent.graph.stream(
                {"request": Question(question=question["question"])}, stream_mode="updates"
            ):
                if "disclosure_tool" in event:
                    candidates = event["disclosure_tool"].get("evidence", [])
                if "generate" in event:
                    answer = event["generate"]["result"]
            if answer is None:
                raise ValueError("Graph did not produce an Answer")
            selected = answer.evidence
            matches = [h["id"] in corpus and h["quote"] in corpus[h["id"]]["text"] for h in selected]
            observed = {
                "retrieval_nonempty": bool(candidates),
                "selected_quotes": len(selected),
                "quotes_in_frozen_corpus": sum(matches),
                "explicit_evidence_refusal": not selected
                and any("근거" in warning for warning in answer.warnings),
                "scope_match": all(
                    [h["source"]["company"], h["source"]["year"]] in question["expected_scope"]
                    for h in selected
                ),
            }
            case = {
                **question,
                "status": "completed",
                "elapsed_seconds": round(time.perf_counter() - start, 3),
                "retrieved_candidates": candidates,
                "result": answer.model_dump(mode="json"),
                "observed": observed,
                "human_semantic_review": "pending",
            }
        except Exception as exc:  # noqa: BLE001 -- persist failure without provider exception text
            case = {
                **question,
                "status": "error",
                "error_type": type(exc).__name__,
                "elapsed_seconds": round(time.perf_counter() - start, 3),
                "human_semantic_review": "pending",
            }
        experiment["cases"].append(case)
        write_json(output, experiment)
        print(f"RAG {question['id']}: {case['status']}", flush=True)
    experiment["finished_at"] = timestamp()
    write_json(output, experiment)
    review_path = result_directory / "rag-reviews.json"
    if not review_path.exists():
        write_json(
            review_path,
            [
                {
                    "id": c["id"],
                    "status": "pending",
                    "reviewer": None,
                    "reviewed_at": None,
                    "expected_support": None,
                    "gold_complete": False,
                    "gold_relevant_chunk_ids": [],
                    "quote_support": {quote_key(h): None for h in c.get("result", {}).get("evidence", [])},
                    "notes": "Candidate group is NOT a gold label. Review the full frozen corpus.",
                }
                for c in experiment["cases"]
            ],
        )
    summarize_rag(run, variant)


def summarize_rag(run, variant="baseline"):
    raw, report = locations(run)
    report = experiment_directory(report, variant)
    experiment = read_json(report / "rag-results.json")
    reviews = read_json(report / "rag-reviews.json")
    cases = experiment["cases"]
    corpus_ids = {row["id"] for row in read_json(raw / "corpus.json")}
    case_ids = {c["id"] for c in cases}
    if len({r["id"] for r in reviews}) != len(reviews) or any(r["id"] not in case_ids for r in reviews):
        raise ValueError("Review IDs must be unique and correspond to recorded cases")
    for label in reviews:
        if not set(label.get("gold_relevant_chunk_ids", [])) <= corpus_ids:
            raise ValueError("Review refers to unknown frozen corpus IDs")
        if label.get("status") == "reviewed":
            if (
                not label.get("reviewer")
                or not label.get("reviewed_at")
                or not isinstance(label.get("expected_support"), bool)
            ):
                raise ValueError("Reviewed gold needs reviewer, date and boolean support label")
            case = next(c for c in cases if c["id"] == label["id"])
            valid_keys = {quote_key(h) for h in case.get("result", {}).get("evidence", [])}
            if not set(label.get("quote_support", {})) <= valid_keys:
                raise ValueError("Quote judgments must correspond to selected quotes")
    successful = [c for c in cases if c["status"] == "completed"]
    quotes = sum(c["observed"]["selected_quotes"] for c in successful)
    matches = sum(c["observed"]["quotes_in_frozen_corpus"] for c in successful)
    summary = {
        "executed_at": timestamp(),
        "mode": experiment["mode"],
        "completed": len(successful),
        "errors": len(cases) - len(successful),
        "retrieval_nonempty_rate_observed": rate(
            sum(c["observed"]["retrieval_nonempty"] for c in successful), len(successful)
        ),
        "quote_literal_match_rate": rate(matches, quotes),
        "explicit_refusal_count_observed": sum(
            c["observed"]["explicit_evidence_refusal"] for c in successful
        ),
        "semantic_metrics": evaluate_rag_metrics(cases, reviews),
        "limitations": [
            "Literal match is not semantic support.",
            "Unindexed controls are not evidence of document-level unanswerability.",
            "Candidate direct/insufficient labels are hypotheses; all human labels initially pending.",
            "This is a 2024 SK hynix corpus baseline, not multi-company/year retrieval quality.",
        ],
    }
    write_json(report / "rag-summary.json", summary)
    with (report / "adopted-quotes.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "case_id",
                "quote_key",
                "chunk_id",
                "question",
                "quote",
                "receipt",
                "source_year",
                "human_support",
            ],
        )
        writer.writeheader()
        for case in successful:
            for hit in case["result"]["evidence"]:
                writer.writerow(
                    {
                        "case_id": case["id"],
                        "quote_key": quote_key(hit),
                        "chunk_id": hit["id"],
                        "question": case["question"],
                        "quote": hit["quote"],
                        "receipt": hit["source"]["receipt"],
                        "source_year": hit["source"]["year"],
                        "human_support": "pending",
                    }
                )
    with (report / "rag-review.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id",
                "group",
                "question",
                "status",
                "route",
                "retrieved_count",
                "selected_quotes",
                "explicit_refusal",
                "human_review",
            ],
        )
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "id": case["id"],
                    "group": case["group"],
                    "question": case["question"],
                    "status": case["status"],
                    "route": case.get("result", {}).get("route"),
                    "retrieved_count": len(case.get("retrieved_candidates", [])),
                    "selected_quotes": case.get("observed", {}).get("selected_quotes"),
                    "explicit_refusal": case.get("observed", {}).get("explicit_evidence_refusal"),
                    "human_review": "See rag-reviews.json; pending unless explicitly reviewed",
                }
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def audit(run):
    """Audit source preservation, parser failures and literal quotes independently of the stored vectors."""
    import subprocess
    import warnings

    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    from finsight.rag import clean_xml

    _raw, report = locations(run)
    manifest = read_json(report / "manifest.json")
    experiment = read_json(report / "rag-results.json")
    documents_by_receipt = {}
    parser_findings = []
    raw_hash_matches = []
    for snapshot in manifest["snapshots"]:
        documents_by_receipt[snapshot["financial"]["source"]["receipt"]] = snapshot["documents"]
        for document in snapshot["documents"]:
            content = (ROOT / document["path"]).read_bytes()
            raw_hash_matches.append(digest(content) == document["sha256"])
            try:
                clean_xml(content)
            except Exception as exc:  # noqa: BLE001 -- safe diagnostic metadata only
                parser_findings.append(
                    {
                        "company": snapshot["company"],
                        "year": snapshot["year"],
                        "file": document["path"],
                        "error_type": type(exc).__name__,
                        "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
                        "position": getattr(exc.__cause__, "position", None),
                        "service_ingestion": "blocked_for_this_document",
                    }
                )
    literal = []
    cache = {}
    for case in experiment["cases"]:
        for hit in case.get("result", {}).get("evidence", []):
            receipt = hit["source"]["receipt"]
            if receipt not in cache:
                cache[receipt] = []
                for document in documents_by_receipt.get(receipt, []):
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
                        soup = BeautifulSoup((ROOT / document["path"]).read_bytes(), "html.parser")
                    for element in soup(["script", "style"]):
                        element.decompose()
                    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
                    cache[receipt].append((document, text))
            match = next(
                (
                    (document, text.find(hit["quote"]))
                    for document, text in cache[receipt]
                    if hit["quote"] in text
                ),
                None,
            )
            literal.append(
                {
                    "case_id": case["id"],
                    "quote_key": quote_key(hit),
                    "receipt": receipt,
                    "original_report_literal_match": bool(match),
                    "document_sha256": match[0]["sha256"] if match else None,
                    "normalized_text_offset": match[1] if match else None,
                    "human_semantic_support": "pending",
                }
            )
    original = {
        "executed_at": timestamp(),
        "mode": "live_original_snapshot_diagnostic",
        "original_file_hash_matches": rate(sum(raw_hash_matches), len(raw_hash_matches)),
        "service_parser_failures": parser_findings,
        "literal_quotes_in_original": rate(
            sum(row["original_report_literal_match"] for row in literal), len(literal)
        ),
        "quotes": literal,
        "note": "Independent tolerant HTML text extraction is for source inspection only, not a production parser fix.",
    }
    write_json(report / "source-audit.json", original)
    before = read_json(report / "service-hashes-before.json")
    before = {item["file"]: item["sha256"].lower() for item in before}
    after = environment()["service_sha256"]
    write_json(
        report / "service-integrity.json",
        {"checked_at": timestamp(), "unchanged": before == after, "before": before, "after": after},
    )
    findings = []
    checked = 0
    known_secrets = [secret.encode() for secret in secrets()]
    paths = [
        ROOT / "scripts/baseline.py",
        ROOT / "tests/test_baseline.py",
        ROOT / "docs/BASELINE.md",
        ROOT / "README.md",
        *report.glob("*"),
        ROOT / "evaluation/baseline/questions.json",
        ROOT / "evaluation/results.json",
    ]
    for path in paths:
        if path.is_file():
            checked += 1
            content = path.read_bytes()
            if any(secret in content for secret in known_secrets):
                findings.append({"file": path.relative_to(ROOT).as_posix(), "type": "credential_value"})
            if re.search(rb"[?&](?:crtfc_key|api_key|access_token)=[^\s&\"<>]+", content, re.IGNORECASE):
                findings.append({"file": path.relative_to(ROOT).as_posix(), "type": "credential_query_url"})
    git = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True, check=False
    )
    security = {
        "checked_at": timestamp(),
        "files_scanned": checked,
        "credential_findings": findings,
        "git_repository": git.returncode == 0,
        "git_history_scan": "not_performed_no_repository" if git.returncode else "not_performed",
        "raw_snapshot_directory": "data/ (excluded by existing .gitignore)",
        "scope": "Known credential values and authentication query URLs in new report files; not a universal secret detector.",
    }
    write_json(report / "security-audit.json", security)
    print(
        json.dumps(
            {
                "service_unchanged": before == after,
                "original_files": len(raw_hash_matches),
                "parser_failed_documents": len(parser_findings),
                "literal_matches": original["literal_quotes_in_original"],
                "credential_findings": len(findings),
            },
            indent=2,
        )
    )
    if before != after or findings:
        raise SystemExit(1)


def financial_metrics(run):
    from finsight.finance import compare
    from finsight.models import Financial

    _raw, report = locations(run)
    manifest = read_json(report / "manifest.json")
    records = [Financial.model_validate(s["financial"]) for s in manifest["snapshots"]]
    actual = compare(records)
    references_path = report / "financial-references.json"
    references = read_json(references_path) if references_path.exists() else []
    lookup = {
        (r["company"], r["year"]): r
        for r in references
        if r.get("status") in {"verified_original_automatic", "verified_original_human"}
    }
    observed = {(row["company"], row["year"]): row for row in actual}
    rows = []
    matched, evaluated = 0, 0
    calculation_matched, calculation_evaluated = 0, 0
    numeric_matched, numeric_evaluated, null_matched, null_evaluated = 0, 0, 0, 0
    for key, row in observed.items():
        if key[1] not in {2023, 2024, 2025}:
            continue
        ref = lookup.get(key)
        previous = observed.get((key[0], key[1] - 1))
        prior_ref = lookup.get((key[0], key[1] - 1))
        base = ref or row
        prior_base = prior_ref or previous
        expected = {
            "operating_margin_pct": reference_percent(base["operating_profit"], base["revenue"]),
            "revenue_growth_pct": reference_growth(
                base["revenue"], prior_base["revenue"] if prior_base else None
            ),
            "profit_growth_pct": reference_growth(
                base["operating_profit"], prior_base["operating_profit"] if prior_base else None
            ),
        }
        checks = {name: row[name] == value for name, value in expected.items()}
        calculation_matched += sum(checks.values())
        calculation_evaluated += len(checks)
        for metric, value in expected.items():
            if value is None:
                null_evaluated += 1
                null_matched += checks[metric]
            else:
                numeric_evaluated += 1
                numeric_matched += checks[metric]
        values = {}
        for metric in ["revenue", "operating_profit"]:
            ok = Decimal(row[metric]) == Decimal(ref[metric]) if ref and row[metric] is not None else None
            values[metric] = {
                "actual": row[metric],
                "expected": ref[metric] if ref else None,
                "match": ok,
                "status": "evaluated" if ok is not None else "pending_original_review",
            }
            if ok is not None:
                matched += ok
                evaluated += 1
        rows.append(
            {
                "company": key[0],
                "year": key[1],
                "basis": row["basis"],
                "receipt": row["receipt"],
                "values": values,
                "calculations": {
                    "actual": {k: row[k] for k in expected},
                    "expected": expected,
                    "matches": checks,
                },
                "note": "Calculations use actual live API inputs; source correctness is a separate check.",
            }
        )
    result = {
        "executed_at": timestamp(),
        "mode": "live_snapshot_replay",
        "requested_company_years": 6,
        "captured_company_years": len(rows),
        "supporting_year": 2022,
        "financial_value_match": rate(matched, evaluated),
        "financial_value_review_coverage": rate(evaluated, 12),
        "reference_method": "Independent original summary CFS table, period/term/current column and million-KRW unit checked automatically",
        "human_financial_review_coverage": rate(
            sum(
                2
                for reference in references
                if reference["year"] in {2023, 2024, 2025}
                and reference.get("human_review") == "reviewed"
                and reference.get("reviewer")
            ),
            12,
        ),
        "calculation_match_including_null_states": rate(calculation_matched, calculation_evaluated),
        "calculation_numeric_match": rate(numeric_matched, numeric_evaluated),
        "calculation_undefined_state_match": rate(null_matched, null_evaluated),
        "rows": rows,
        "collection_errors": manifest["errors"],
    }
    write_json(report / "financial-results.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "collect",
            "inspect-tables",
            "build-references",
            "financial-metrics",
            "freeze-corpus",
            "rag",
            "rag-metrics",
            "audit",
        ],
    )
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument(
        "--variant", default="baseline", help="Separate RAG output using the same frozen sources"
    )
    args = parser.parse_args()
    if args.command in {"rag", "rag-metrics"}:
        {"rag": run_rag, "rag-metrics": summarize_rag}[args.command](args.run, args.variant)
        return
    {
        "collect": collect,
        "inspect-tables": inspect_tables,
        "build-references": build_references,
        "financial-metrics": financial_metrics,
        "freeze-corpus": freeze_corpus,
        "rag": run_rag,
        "rag-metrics": summarize_rag,
        "audit": audit,
    }[args.command](args.run)


if __name__ == "__main__":
    main()
