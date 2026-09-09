"""색인에 없는 검색어를 문헌 DB 에 실시간으로 물어보는 경로.

사전에 없는 성분을 검색했을 때 "자료 없음"으로 끝내지 않기 위한 보조 기능이다.
결과는 색인된 통계와 섞지 않고 항상 '실시간 조회' 로 구분해 내보낸다.
"""
from __future__ import annotations

import json
import threading
import time

from ingest.classify import DIRECTIONS, STUDY_TYPES, SUBJECTS, Classifier
from ingest.sources.europepmc import EuropePMC, build_query
from ingest.sources.http import Client

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60 * 30
_LOCK = threading.Lock()


class LiveLookup:
    def __init__(self, ingredients: list[dict], outcomes: list[dict],
                 enabled: bool = True, rate: float = 2.0):
        self.enabled = enabled
        self.clf = Classifier(ingredients, outcomes)
        self.outcomes = {o["id"]: o for o in outcomes}
        self._epmc = EuropePMC(Client(rate_per_sec=rate, max_retries=1, verbose=False))

    def search(self, term: str, limit: int = 40) -> dict:
        term = (term or "").strip()
        if not self.enabled:
            return {"available": False, "reason": "실시간 조회가 꺼져 있습니다.", "term": term}
        if len(term) < 2:
            return {"available": False, "reason": "검색어가 너무 짧습니다.", "term": term}

        key = f"{term.lower()}::{limit}"
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and time.time() - hit[0] < _CACHE_TTL:
                return hit[1]

        query = build_query([term])
        try:
            page, _, hit_count = next(self._epmc.search(query, limit=limit))
        except StopIteration:
            page, hit_count = [], 0
        except Exception as e:
            return {"available": False, "term": term,
                    "reason": f"문헌 DB 에 연결하지 못했습니다: {e}"}

        papers, direction_counts, outcome_counts = [], {"significant": 0, "null": 0, "unclear": 0}, {}
        human = 0
        for rec in page:
            res = self.clf.classify(rec)
            if res.subject == "human":
                human += 1
            top = res.outcomes[0] if res.outcomes else None
            if top and res.subject == "human":
                direction_counts[top.direction] = direction_counts.get(top.direction, 0) + 1
            for h in res.outcomes:
                oc = outcome_counts.setdefault(h.outcome_id, {"total": 0, "human": 0})
                oc["total"] += 1
                oc["human"] += int(res.subject == "human")
            papers.append({
                "pmid": rec["pmid"], "title": rec["title"], "journal": rec["journal"],
                "year": rec["year"], "url": rec["url"], "cited_by": rec["cited_by"],
                "study_type": res.study_type,
                "study_type_ko": STUDY_TYPES[res.study_type][0],
                "subject": res.subject, "subject_ko": SUBJECTS[res.subject],
                "retracted": res.retracted,
                "evidence_rank": res.evidence_rank,
                "direction": top.direction if top else None,
                "direction_ko": DIRECTIONS[top.direction] if top else None,
                "evidence": top.evidence if top else "",
                "outcome_id": top.outcome_id if top else None,
                "outcome_ko": self.outcomes[top.outcome_id]["label_ko"] if top else None,
            })
        papers.sort(key=lambda p: (-p["evidence_rank"], -(p["cited_by"] or 0), -(p["year"] or 0)))

        payload = {
            "available": True,
            "term": term,
            "query": query,
            "hit_count": hit_count,
            "fetched": len(papers),
            "human": human,
            "direction_counts": direction_counts,
            "outcomes": sorted(
                ({"outcome_id": oid,
                  "label_ko": self.outcomes[oid]["label_ko"], **v}
                 for oid, v in outcome_counts.items()),
                key=lambda o: (-o["human"], -o["total"]))[:8],
            "papers": papers[:20],
            "note": "색인에 없는 검색어라 문헌 DB 에 실시간으로 질의한 결과입니다. "
                    "가져온 상위 일부만 분석했으므로 색인된 성분의 통계와 직접 비교하지 마세요.",
        }
        with _LOCK:
            _CACHE[key] = (time.time(), payload)
        return payload
