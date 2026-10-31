import hashlib
import math
import re

import chromadb
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from openai import OpenAI

from finsight.config import Settings
from finsight.finance import DataError
from finsight.models import Source, now_iso


def normalize_dart_xml_text(raw: bytes) -> bytes:
    """Escape literal business text seen in original DART files, without tag recovery.

    Leave references (including unknown ones), comments, CDATA and processing
    instructions untouched so malformed structure/entities still fail parsing.
    Only UTF-8/ASCII-compatible input is eligible for this narrow repair.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    if "\x00" in text:
        return raw
    protected = re.compile(r"(<!\[CDATA\[.*?\]\]>|<!--.*?-->|<\?.*?\?>)", re.DOTALL)
    reference = r"&(?!(?:[A-Za-z_:][A-Za-z0-9_.:\-]*|#[0-9]+|#x[0-9A-Fa-f]+);)"
    parts = protected.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = re.sub(reference, "&amp;", parts[index])
        # DART headings and deletion annotations use literal angle brackets.
        # Do not turn arbitrary unknown/mismatched tags into text.
        parts[index] = re.sub(r"<(?=\s)", "&lt;", parts[index])
        parts[index] = re.sub(r"<(?=삭제\s+\d{4}\.\d{1,2}\.\d{1,2}>)", "&lt;", parts[index])
        for label in (
            "ACI 세미나",
            "평가항목",
            "최고감사인과정",
            "이사ㆍ감사 전체의 보수현황",
            "보수지급금액 5억원 이상 중 상위 5명의 개인별 보수현황",
            "보수지급금액 5억원 이상인 이사ㆍ감사의 개인별 보수현황",
        ):
            parts[index] = parts[index].replace(f"<{label}>", f"&lt;{label}>")
    return "".join(parts).encode("utf-8")


def clean_xml(raw: bytes) -> str:
    if len(raw) > 40_000_000:
        raise DataError("개별 공시 문서가 너무 큽니다.")
    if b"<!ENTITY" in raw.upper() or b"<!DOCTYPE" in raw.upper():
        raise DataError("외부 엔티티 또는 DTD가 있는 문서는 수집하지 않습니다.")
    # Parse real disclosures as XML. Keep HTML fragment support for legacy inputs.
    declared_xml = raw.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<?xml")
    try:
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            repaired = normalize_dart_xml_text(raw)
            if repaired == raw:
                raise
            root = ElementTree.fromstring(repaired)
    except (ElementTree.ParseError, DefusedXmlException, ValueError) as exc:
        if declared_xml or re.match(rb"\s*<DOCUMENT(?:\s|>)", raw, re.IGNORECASE):
            raise DataError("공시 XML 형식을 읽을 수 없습니다. 원문 파일을 확인하세요.") from exc
        soup = BeautifulSoup(raw, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        text = soup.get_text(" ", strip=True)
    else:

        def text_parts(element):
            # Preserve paragraph/table boundaries and tails while excluding executable content.
            if element.tag.rsplit("}", 1)[-1].lower() not in {"script", "style"}:
                if element.text:
                    yield element.text
                for child in element:
                    yield from text_parts(child)
            if element.tail:
                yield element.tail

        text = " ".join(text_parts(root))
    return re.sub(r"\s+", " ", text).strip()


def chunks(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    if not 0 <= overlap < size:
        raise ValueError("invalid chunk parameters")
    return [text[i : i + size] for i in range(0, len(text), size - overlap) if text[i : i + size].strip()]


class Embedder:
    def __init__(self, config: Settings):
        self.config = config
        self.client = None
        if config.finsight_mode == "live":
            config.require_live(rag=True)
            self.client = OpenAI(
                api_key=config.openai_api_key.get_secret_value(),
                timeout=config.request_timeout,
                max_retries=2,
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.client:
            vectors = []
            try:
                for start in range(0, len(texts), 32):
                    result = self.client.embeddings.create(
                        model=self.config.embedding_model, input=texts[start : start + 32]
                    )
                    vectors.extend(
                        item.embedding for item in sorted(result.data, key=lambda item: item.index)
                    )
                return vectors
            except Exception as exc:
                raise DataError("OpenAI 임베딩 호출 실패: 키·한도·네트워크를 확인하세요.") from exc
        # Deterministic character hashing for offline plumbing tests, NOT semantic embeddings.
        vectors = []
        for text in texts:
            vector = [0.0] * 256
            compact = re.sub(r"\s+", "", text.lower())
            for i in range(max(1, len(compact) - 1)):
                token = compact[i : i + 2].encode()
                vector[int.from_bytes(hashlib.sha256(token).digest()[:2], "big") % 256] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            vectors.append([x / norm for x in vector])
        return vectors


class DisclosureStore:
    def __init__(self, config: Settings):
        self.config = config
        self.embedder = Embedder(config)
        from chromadb.config import Settings as ChromaSettings

        self.client = chromadb.PersistentClient(
            path=config.chroma_path, settings=ChromaSettings(anonymized_telemetry=False)
        )
        identity = f"{config.finsight_mode}-{config.embedding_model if config.finsight_mode == 'live' else 'hash-v1'}"
        name = "disclosures-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        self.collection = self.client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})

    def add(self, text: str, metadata: dict) -> int:
        source = Source.model_validate(metadata)
        if source.mode != self.config.finsight_mode:
            raise DataError("실제 데이터와 MOCK 문서는 같은 컬렉션에 저장할 수 없습니다.")
        parts = chunks(text)
        if not parts:
            raise DataError("정제된 공시 문서가 비어 있습니다.")
        if len(parts) > 3000:
            raise DataError("공시 청크 수가 수집 한도를 초과했습니다.")
        vectors = self.embedder.embed(parts)
        # Embed fully before replacing the receipt; same receipt updates are idempotent.
        self.collection.delete(where={"receipt": source.receipt})
        for start in range(0, len(parts), 100):
            ids = [f"{source.receipt}-{i}" for i in range(start, min(start + 100, len(parts)))]
            self.collection.upsert(
                ids=ids,
                documents=parts[start : start + 100],
                embeddings=vectors[start : start + 100],
                metadatas=[{**source.model_dump(), "chunk_index": i} for i in range(start, start + len(ids))],
            )
        return len(parts)

    def search(self, question: str, company: str, year: int) -> list[dict]:
        where = {"$and": [{"company": company}, {"year": year}, {"mode": self.config.finsight_mode}]}
        # Prefer latest corrected filing already ingested for this company and fiscal period.
        existing = self.collection.get(where=where, include=["metadatas"])
        if not existing["ids"]:
            return []
        latest = max(m["receipt"] for m in existing["metadatas"])
        result = self.collection.query(
            query_embeddings=self.embedder.embed([question]),
            n_results=3,
            where={"$and": [*where["$and"], {"receipt": latest}]},
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for id_, text, meta, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            # Hash fixtures test scope/plumbing only; a semantic cutoff is not meaningful for them.
            threshold = self.config.rag_max_distance if self.config.finsight_mode == "live" else 0.95
            if distance <= threshold:
                hits.append(
                    {
                        "id": id_,
                        "text": text,
                        "source": Source.model_validate(meta).model_dump(),
                        "distance": round(distance, 4),
                    }
                )
        return hits


def ingest(dart, store: DisclosureStore, company: str, year: int) -> dict:
    listing = dart.annual_disclosure(company, year)
    receipt = listing["rcept_no"]
    documents = dart.document(receipt)
    text = " ".join(clean_xml(doc) for doc in documents)
    source = Source(
        title=listing["report_nm"],
        receipt=receipt,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
        company=company,
        year=year,
        reference_date=f"{year}-12-31",
        retrieved_at=now_iso(),
        mode="live",
    )
    count = store.add(text, source.model_dump())
    return {"receipt": receipt, "chunks": count, "source": source.model_dump()}
