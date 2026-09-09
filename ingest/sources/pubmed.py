"""NCBI E-utilities (PubMed) 클라이언트 — Europe PMC 의 대체 경로.

esearch 로 PMID 를 모으고 efetch 로 XML 상세를 받는다.
제약(공식 문서 기준):
  - API 키 없이 초당 3회, 키가 있으면 초당 10회.
    https://www.ncbi.nlm.nih.gov/books/NBK25497/
  - esearch 는 한 질의당 앞의 10,000건까지만 접근 가능
    (retmax <= 10000, retstart + retmax <= 10000).
    https://www.ncbi.nlm.nih.gov/books/NBK25499/
    → 이보다 많으면 연도 구간으로 잘라 여러 질의로 나눈다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterator

from ingest import config
from ingest.sources.http import Client

ESEARCH_MAX = 10_000
EFETCH_BATCH = 200


def _common_params() -> dict:
    p = {"tool": config.TOOL_NAME}
    if config.CONTACT_EMAIL:
        p["email"] = config.CONTACT_EMAIL
    if config.NCBI_API_KEY:
        p["api_key"] = config.NCBI_API_KEY
    return p


def build_query(synonyms: list[str], extra: str = "") -> str:
    terms = " OR ".join(f'"{s}"[Title/Abstract]' for s in synonyms)
    q = f"({terms}) AND hasabstract"
    if extra:
        q += f" AND ({extra})"
    return q


def _text(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _abstract(article) -> str:
    parts = []
    for ab in article.findall(".//Abstract/AbstractText"):
        label = ab.get("Label") or ab.get("NlmCategory")
        body = "".join(ab.itertext()).strip()
        if not body:
            continue
        parts.append(f"{label.upper()}: {body}" if label else body)
    return " ".join(parts)


def parse_articles(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = _text(art.find(".//MedlineCitation/PMID"))
        if not pmid:
            continue
        article = art.find(".//MedlineCitation/Article")
        if article is None:
            continue

        year = None
        for path in (".//Journal/JournalIssue/PubDate/Year",
                     ".//Journal/JournalIssue/PubDate/MedlineDate",
                     ".//PubMedPubDate[@PubStatus='pubmed']/Year"):
            raw = _text(art.find(path))
            if raw:
                digits = "".join(c for c in raw[:4] if c.isdigit())
                if len(digits) == 4:
                    year = int(digits)
                    break

        doi = pmcid = None
        for eid in art.findall(".//ArticleIdList/ArticleId"):
            if eid.get("IdType") == "doi":
                doi = _text(eid)
            elif eid.get("IdType") == "pmc":
                pmcid = _text(eid)

        authors = []
        for a in article.findall(".//AuthorList/Author")[:12]:
            last, initials = _text(a.find("LastName")), _text(a.find("Initials"))
            if last:
                authors.append(f"{last} {initials}".strip())

        out.append({
            "source": "MED",
            "ext_id": pmid,
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
            "title": _text(article.find("ArticleTitle")),
            "abstract": _abstract(article),
            "journal": _text(article.find(".//Journal/Title")),
            "year": year,
            "authors": ", ".join(authors),
            "pub_types": [_text(p) for p in article.findall(".//PublicationTypeList/PublicationType") if _text(p)],
            "mesh": [_text(d) for d in art.findall(".//MeshHeadingList/MeshHeading/DescriptorName") if _text(d)],
            "cited_by": 0,          # E-utilities 는 피인용 수를 주지 않는다
            "is_oa": 1 if pmcid else 0,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return out


class PubMed:
    def __init__(self, client: Client | None = None):
        rate = 10.0 if config.NCBI_API_KEY else 3.0
        self.client = client or Client(rate_per_sec=min(rate, config.RATE_LIMIT_PER_SEC or rate))

    def hit_count(self, query: str) -> int:
        data = self.client.get_json(f"{config.PUBMED_BASE}/esearch.fcgi", {
            **_common_params(), "db": "pubmed", "term": query,
            "retmode": "json", "retmax": 0,
        })
        return int(((data.get("esearchresult") or {}).get("count")) or 0)

    def pmids(self, query: str, limit: int) -> list[str]:
        ids, retstart = [], 0
        while len(ids) < limit and retstart < ESEARCH_MAX:
            retmax = min(limit - len(ids), ESEARCH_MAX - retstart, 5000)
            data = self.client.get_json(f"{config.PUBMED_BASE}/esearch.fcgi", {
                **_common_params(), "db": "pubmed", "term": query, "retmode": "json",
                "retmax": retmax, "retstart": retstart,
            })
            batch = (data.get("esearchresult") or {}).get("idlist") or []
            if not batch:
                break
            ids.extend(batch)
            retstart += len(batch)
        return ids[:limit]

    def fetch(self, pmids: list[str]) -> Iterator[list[dict]]:
        for i in range(0, len(pmids), EFETCH_BATCH):
            chunk = pmids[i:i + EFETCH_BATCH]
            raw = self.client.get(f"{config.PUBMED_BASE}/efetch.fcgi", {
                **_common_params(), "db": "pubmed", "id": ",".join(chunk), "retmode": "xml",
            })
            yield parse_articles(raw)

    def search(self, query: str, limit: int) -> Iterator[list[dict]]:
        ids = self.pmids(query, limit)
        if ids:
            yield from self.fetch(ids)
