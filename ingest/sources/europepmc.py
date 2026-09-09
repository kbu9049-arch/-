"""Europe PMC Articles RESTful API 클라이언트.

검색 엔드포인트: {base}/search
  - cursorMark 로 전체 결과를 넘긴다. 첫 요청은 '*', 이후 응답의 nextCursorMark 사용.
  - pageSize 범위 0~1000 (기본 25).
  - resultType: idlist | lite | core  (core 여야 초록·MeSH·publication type 이 온다)
문서: https://europepmc.org/RestfulWebService

API 키는 필요하지 않다.
"""
from __future__ import annotations

from typing import Iterator

from ingest import config
from ingest.sources.http import Client


def build_query(synonyms: list[str], tier_clause: str = "", extra: str = "") -> str:
    """성분 검색어 목록 → Europe PMC 질의 문자열.

    따옴표로 감싼 구(phrase) 검색만 쓴다. 필드 지정 문법에 의존하지 않으므로
    확실히 동작하고, 성분-논문 연결의 최종 판정은 수집 후 분류기가 다시 한다.
    SRC:MED 로 PubMed 수록 문헌으로 한정해 초록·MeSH 품질을 확보한다.
    """
    terms = " OR ".join(f'"{s}"' for s in synonyms)
    parts = [f"({terms})", "(SRC:MED)"]
    if tier_clause:
        parts.append(tier_clause)
    if extra:
        parts.append(f"({extra})")
    return " AND ".join(parts)


def _as_list(node, key: str) -> list:
    """Europe PMC 는 리스트가 1개일 때도 리스트로 주지만 방어적으로 처리한다."""
    if not node:
        return []
    val = node.get(key)
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def normalize(rec: dict) -> dict:
    """API 응답 1건 → 내부 표준 형태."""
    src = rec.get("source") or "MED"
    ext_id = str(rec.get("id") or rec.get("pmid") or "")
    pmid = str(rec.get("pmid") or "") or None
    pmcid = rec.get("pmcid") or None

    journal_info = rec.get("journalInfo") or {}
    journal = ((journal_info.get("journal") or {}).get("title")
               or rec.get("journalTitle") or "")

    year = rec.get("pubYear") or journal_info.get("yearOfPublication")
    try:
        year = int(str(year)[:4])
    except (TypeError, ValueError):
        year = None

    mesh = []
    for mh in _as_list(rec.get("meshHeadingList"), "meshHeading"):
        name = (mh or {}).get("descriptorName")
        if name:
            mesh.append(name)

    pub_types = [p for p in _as_list(rec.get("pubTypeList"), "pubType") if p]

    if pmid:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    elif pmcid:
        url = f"https://europepmc.org/article/PMC/{pmcid}"
    else:
        url = f"https://europepmc.org/article/{src}/{ext_id}"

    try:
        cited = int(rec.get("citedByCount") or 0)
    except (TypeError, ValueError):
        cited = 0

    return {
        "source": src,
        "ext_id": ext_id,
        "pmid": pmid,
        "pmcid": pmcid,
        "doi": rec.get("doi") or None,
        "title": (rec.get("title") or "").strip(),
        "abstract": (rec.get("abstractText") or "").strip(),
        "journal": journal,
        "year": year,
        "authors": (rec.get("authorString") or "").strip(),
        "pub_types": pub_types,
        "mesh": mesh,
        "cited_by": cited,
        "is_oa": 1 if str(rec.get("isOpenAccess", "")).upper() == "Y" else 0,
        "url": url,
    }


class EuropePMC:
    def __init__(self, client: Client | None = None, page_size: int | None = None):
        self.client = client or Client()
        self.page_size = min(page_size or config.EPMC_PAGE_SIZE, config.EPMC_MAX_PAGE_SIZE)

    def hit_count(self, query: str) -> int:
        """결과 건수만 확인한다 (resultType=idlist, pageSize=1 로 가볍게)."""
        data = self.client.get_json(f"{config.EUROPEPMC_BASE}/search", {
            "query": query, "format": "json", "resultType": "idlist", "pageSize": 1,
        })
        return int(data.get("hitCount") or 0)

    def search(self, query: str, limit: int, cursor: str = "*",
               result_type: str = "core") -> Iterator[tuple[list[dict], str, int]]:
        """(정규화된 논문 목록, 다음 커서, 전체 결과 수) 를 페이지 단위로 내보낸다."""
        fetched = 0
        seen_cursors = {cursor}
        while fetched < limit:
            page = min(self.page_size, limit - fetched)
            data = self.client.get_json(f"{config.EUROPEPMC_BASE}/search", {
                "query": query, "format": "json", "resultType": result_type,
                "pageSize": page, "cursorMark": cursor,
            })
            hit_count = int(data.get("hitCount") or 0)
            results = (data.get("resultList") or {}).get("result") or []
            if not results:
                yield [], "", hit_count
                return
            records = [normalize(r) for r in results]
            records = [r for r in records if r["ext_id"] and r["title"]]
            fetched += len(results)

            next_cursor = data.get("nextCursorMark") or ""
            # 커서가 제자리걸음이면 결과 끝. (무한 루프 방지)
            exhausted = (not next_cursor or next_cursor in seen_cursors
                         or fetched >= hit_count)
            seen_cursors.add(next_cursor)
            yield records, ("" if exhausted else next_cursor), hit_count
            if exhausted:
                return
            cursor = next_cursor
