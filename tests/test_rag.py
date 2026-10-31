import warnings

import pytest

from finsight.config import Settings
from finsight.finance import DataError
from finsight.mock import mock_documents
from finsight.rag import DisclosureStore, chunks, clean_xml


def test_cleaning():
    assert clean_xml(b"<p>Hello</p><script>bad</script><p>world</p>") == "Hello world"
    with pytest.raises(DataError):
        clean_xml(b'<!DOCTYPE x [<!ENTITY attack "bad">]><x/>')
    assert chunks("abcdefghij", size=6, overlap=2) == ["abcdef", "efghij", "ij"]


def test_dart_xml_preserves_text_without_html_warning():
    raw = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<DOCUMENT><TITLE>실적 분석</TITLE><TABLE><TR><TD>매출액</TD>"
        "<TD>100 &amp; 200</TD></TR></TABLE><P>판매가격 상승</P>"
        "<SCRIPT>제외할 코드</SCRIPT><STYLE>제외할 스타일</STYLE></DOCUMENT>"
    ).encode()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert clean_xml(raw) == "실적 분석 매출액 100 & 200 판매가격 상승"


def test_malformed_declared_xml_is_not_silently_recovered():
    with pytest.raises(DataError, match="XML 형식"):
        clean_xml(b'<?xml version="1.0"?><DOCUMENT><P>broken</DOCUMENT>')


def test_xml_namespace_and_tail_text():
    assert (
        clean_xml(
            b'<d:DOCUMENT xmlns:d="urn:dart"><d:P>before<d:SCRIPT>bad</d:SCRIPT>after</d:P></d:DOCUMENT>'
        )
        == "before after"
    )


def test_real_dart_company_names_and_existing_entities_are_preserved():
    # Minimal reproductions of the original SK hynix/Samsung parse failures.
    raw = (
        '<?xml version="1.0" encoding="UTF-8"?><DOCUMENT>'
        '<TD>S&P</TD><TE>Samsung R&D Institute Ukraine (SRUKR)</TE>'
        '<TD>SK E&S㈜</TD><P>100 &amp; 200 &#38; 300 &#x26; 400</P></DOCUMENT>'
    ).encode()
    assert clean_xml(raw) == (
        "S&P Samsung R&D Institute Ukraine (SRUKR) SK E&S㈜ 100 & 200 & 300 & 400"
    )


def test_ampersand_repair_keeps_cdata_comments_and_attributes():
    raw = (
        b'<?xml version="1.0"?><DOCUMENT><!-- R&D -->'
        b'<P LABEL="R&D">S&P</P><![CDATA[R&D <literal> &amp;]]></DOCUMENT>'
    )
    assert clean_xml(raw) == "S&P R&D <literal> &amp;"


@pytest.mark.parametrize("entity", ["&unknown;", "&#0;", "&#x110000;"])
def test_invalid_xml_entities_are_still_rejected(entity):
    raw = f'<?xml version="1.0"?><DOCUMENT><P>S&P {entity}</P></DOCUMENT>'.encode()
    with pytest.raises(DataError, match="XML 형식"):
        clean_xml(raw)


def test_ampersand_repair_does_not_recover_broken_tags():
    with pytest.raises(DataError, match="XML 형식"):
        clean_xml(b'<?xml version="1.0"?><DOCUMENT><P>S&P</DOCUMENT>')


def test_dart_literal_heading_and_deletion_annotations_are_not_lost():
    raw = (
        '<?xml version="1.0"?><DOCUMENT><P>< TV 시장점유율 추이 ></P>'
        '<P> (5) <삭제 2012.3.5> (6) 해외증권의 발행 (7) <삭제 1999.4.9></P>'
        '<TD><이사ㆍ감사 전체의 보수현황></TD><TD>4.6점<평가항목>구성, 역할</TD>'
        '<P>- 제11회 <ACI 세미나></P></DOCUMENT>'
    ).encode()
    assert clean_xml(raw) == (
        '< TV 시장점유율 추이 > (5) <삭제 2012.3.5> (6) 해외증권의 발행 (7) <삭제 1999.4.9> '
        '<이사ㆍ감사 전체의 보수현황> 4.6점<평가항목>구성, 역할 - 제11회 <ACI 세미나>'
    )


def test_chroma_roundtrip_scope_idempotency(tmp_path):
    config = Settings(_env_file=None, chroma_path=str(tmp_path), rag_max_distance=1.0)
    store = DisclosureStore(config)
    docs = mock_documents()
    for text, meta in docs:
        store.add(text, meta)
    count = store.collection.count()
    store.add(*docs[0])
    assert store.collection.count() == count
    hits = store.search("삼성전자 2024년 매출 실적 변화 원인", "삼성전자", 2024)
    assert hits
    assert all(h["source"]["company"] == "삼성전자" and h["source"]["year"] == 2024 for h in hits)
    assert store.search("매출", "삼성전자", 2020) == []
    assert DisclosureStore(config).collection.count() == count
    with pytest.raises(DataError):
        store.add(docs[0][0], {**docs[0][1], "mode": "live"})
