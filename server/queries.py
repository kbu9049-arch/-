"""SQLite 색인 조회 로직. FastAPI 라우터와 정적 스냅샷 내보내기가 함께 쓴다.

여기서 만들어 내보내는 모든 수치는 papers / paper_ingredient / paper_outcome
테이블의 실제 행 수를 센 값이다. 추정하거나 보정하는 값은 하나도 없다.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sqlite3
import unicodedata

from ingest.classify import DIRECTIONS, STUDY_TYPES, SUBJECTS

PAGE_SIZE = 20


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", (text or "")).strip().lower()


# ── 레퍼런스 로딩 ────────────────────────────────────────────────────────────
def _load_palette() -> dict | None:
    """계통 묶음표를 읽는다. 없으면 색 없이도 화면은 그대로 돈다."""
    import ingest.config as cfg
    try:
        return json.loads(cfg.PALETTE_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Reference:
    """성분·지표 사전을 메모리에 올려 두고 이름 검색에 쓴다."""

    def __init__(self, ingredients: list[dict], outcomes: list[dict]):
        self.ingredients = {i["id"]: i for i in ingredients}
        self.outcomes = {o["id"]: o for o in outcomes}
        self.categories: dict[str, str] = {}
        for i in ingredients:
            self.categories[i["category"]] = i["category_ko"]

        # 측정 항목 30가지를 몸의 계통으로 묶은 표. scripts/gen_colors.py 가 만든다.
        # 화면에서 항목마다 계통 이름과 색을 함께 보여 주는 데 쓴다.
        self.families: dict[str, str] = {}
        self.family_of: dict[str, str] = {}
        pal = _load_palette()
        if pal:
            self.families = {k: v["ko"] for k, v in pal["outcome_families"].items()}
            self.family_of = pal["outcome_family_of"]

        # 성분 검색: 한글명·영문명·검색어를 모두 색인
        self._ing_index: list[tuple[str, str, int]] = []   # (표기, 성분 id, 가중치)
        for i in ingredients:
            self._ing_index.append((norm(i["name_ko"]), i["id"], 3))
            self._ing_index.append((norm(i["name_en"]), i["id"], 3))
            for s in i["synonyms"]:
                self._ing_index.append((norm(s), i["id"], 2))
            # 괄호 안 별칭도 따로 색인: "커큐민(강황)" → "강황"
            for part in re.findall(r"\(([^)]+)\)", i["name_ko"]):
                self._ing_index.append((norm(part), i["id"], 3))
            base = re.sub(r"\([^)]*\)", "", i["name_ko"]).strip()
            if base and base != i["name_ko"]:
                self._ing_index.append((norm(base), i["id"], 3))

        # 지표 검색: 한글 라벨·별칭·영문 표현
        self._out_index: list[tuple[str, str, int]] = []
        for o in outcomes:
            self._out_index.append((norm(o["label_ko"]), o["id"], 3))
            self._out_index.append((norm(o["label_en"]), o["id"], 3))
            for a in o["ko_aliases"]:
                self._out_index.append((norm(a), o["id"], 3))
            for t in o["measures"] + o["terms"]:
                self._out_index.append((norm(t), o["id"], 1))

    def search_index(self) -> dict[str, list[list]]:
        """정적 배포용 표기 색인. 브라우저가 서버와 똑같은 검색 규칙을 쓰게 한다."""
        return {
            "ingredients": [[lbl, key, w] for lbl, key, w in self._ing_index if lbl],
            "outcomes": [[lbl, key, w] for lbl, key, w in self._out_index if lbl],
        }

    def find_ingredients(self, q: str, limit: int = 12) -> list[tuple[str, int]]:
        return self._find(self._ing_index, q, limit)

    def find_outcomes(self, q: str, limit: int = 5) -> list[tuple[str, int]]:
        return self._find(self._out_index, q, limit)

    @staticmethod
    def _find(index, q: str, limit: int) -> list[tuple[str, int]]:
        q = norm(q)
        if not q:
            return []
        scores: dict[str, int] = {}
        for label, key, weight in index:
            if not label:
                continue
            if label == q:
                score = 100 * weight
            elif label.startswith(q):
                score = 60 * weight
            elif q in label:
                score = 30 * weight
            elif len(q) >= 3 and q.replace(" ", "") in label.replace(" ", ""):
                score = 20 * weight
            else:
                continue
            scores[key] = max(scores.get(key, 0), score)
        return sorted(scores.items(), key=lambda kv: -kv[1])[:limit]


# ── 공통 직렬화 ──────────────────────────────────────────────────────────────
def paper_row(r: sqlite3.Row, *, with_evidence: bool = False) -> dict:
    out = {
        "id": r["id"],
        "pmid": r["pmid"],
        "doi": r["doi"],
        "title": r["title"],
        "journal": r["journal"],
        "year": r["year"],
        "authors": r["authors"],
        "url": r["url"],
        "study_type": r["study_type"],
        "study_type_ko": STUDY_TYPES.get(r["study_type"], (r["study_type"], 0))[0],
        "subject": r["subject"],
        "subject_ko": SUBJECTS.get(r["subject"], r["subject"]),
        "retracted": bool(r["retracted"]),
        "cited_by": r["cited_by"],
        "is_oa": bool(r["is_oa"]),
    }
    keys = r.keys()
    if "direction" in keys and r["direction"]:
        out["direction"] = r["direction"]
        out["direction_ko"] = DIRECTIONS.get(r["direction"], r["direction"])
    if with_evidence and "evidence" in keys:
        out["evidence"] = r["evidence"] or ""
    if "outcome_id" in keys:
        out["outcome_id"] = r["outcome_id"]
    return out


def attach_top_outcome(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """논문마다 점수가 가장 높은 결과지표 하나를 붙인다.

    지표 필터 없이 논문을 나열할 때도 '어떤 항목으로 분류됐고 그 근거 문장이
    무엇인지'가 보이도록 하기 위한 것이다. 이미 지표가 붙어 있으면 건드리지 않는다.
    페이지에 실린 논문 id 에 대해서만 한 번 더 조회하므로 비용이 페이지 크기에 비례한다.
    """
    need = [it["id"] for it in items if "direction" not in it]
    if not need:
        return items
    placeholders = ",".join("?" * len(need))
    best: dict[int, sqlite3.Row] = {}
    for r in conn.execute(
            f"""SELECT paper_id, outcome_id, direction, evidence, score
                FROM paper_outcome WHERE paper_id IN ({placeholders})
                ORDER BY score DESC, outcome_id""", need):
        best.setdefault(r["paper_id"], r)
    for it in items:
        r = best.get(it["id"])
        if r is not None and "direction" not in it:
            it["outcome_id"] = r["outcome_id"]
            it["direction"] = r["direction"]
            it["direction_ko"] = DIRECTIONS.get(r["direction"], r["direction"])
            it["evidence"] = r["evidence"] or ""
    return items


def _stats_row(r: sqlite3.Row | None) -> dict:
    if r is None:
        return {"total": 0, "human": 0, "systematic": 0, "rct": 0, "preclinical": 0,
                "retracted": 0, "year_min": None, "year_max": None, "hit_count": 0}
    return {k: r[k] for k in ("total", "human", "systematic", "rct", "preclinical",
                              "retracted", "year_min", "year_max", "hit_count")}


# ── 코퍼스 요약 ──────────────────────────────────────────────────────────────
def corpus_summary(conn: sqlite3.Connection) -> dict:
    def one(sql, default=0):
        row = conn.execute(sql).fetchone()
        return (row[0] if row and row[0] is not None else default)

    meta = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM meta")}
    return {
        "papers": one("SELECT COUNT(*) FROM papers"),
        "human_papers": one("SELECT COUNT(*) FROM papers WHERE subject = 'human'"),
        "systematic_papers": one(
            "SELECT COUNT(*) FROM papers WHERE study_type IN ('meta_analysis','systematic_review')"),
        "rct_papers": one("SELECT COUNT(*) FROM papers WHERE study_type = 'rct'"),
        "retracted_papers": one("SELECT COUNT(*) FROM papers WHERE retracted = 1"),
        "ingredients_with_papers": one("SELECT COUNT(DISTINCT ingredient_id) FROM paper_ingredient"),
        "outcomes_with_papers": one("SELECT COUNT(DISTINCT outcome_id) FROM paper_outcome"),
        "year_min": one("SELECT MIN(year) FROM papers WHERE year IS NOT NULL", None),
        "year_max": one("SELECT MAX(year) FROM papers WHERE year IS NOT NULL", None),
        "last_harvest": meta.get("last_harvest"),
        "last_aggregate": meta.get("last_aggregate"),
        "harvest_source": meta.get("harvest_source"),
        # 테스트 픽스처가 DB 에 섞여 있으면 화면에 경고를 띄우기 위한 값.
        # 실제 문헌은 source 가 MED/PMC/PPR 이고, 픽스처만 FIXTURE 다.
        "fixture_papers": one("SELECT COUNT(*) FROM papers WHERE source = 'FIXTURE'"),
    }


# ── 성분 목록 / 검색 ─────────────────────────────────────────────────────────
def ingredient_list(conn, ref: Reference, *, category: str = "", q: str = "",
                    limit: int = 60, offset: int = 0, sort: str = "papers") -> dict:
    stats = {r["ingredient_id"]: r for r in conn.execute("SELECT * FROM ingredient_stats")}

    if q:
        ranked = ref.find_ingredients(q, limit=400)
        order = {iid: n for n, (iid, _) in enumerate(ranked)}
        ids = [iid for iid, _ in ranked]
    else:
        ids = list(ref.ingredients)
        order = {}

    items = []
    for iid in ids:
        ing = ref.ingredients.get(iid)
        if not ing or (category and ing["category"] != category):
            continue
        st = _stats_row(stats.get(iid))
        items.append({
            "id": iid,
            "name_ko": ing["name_ko"],
            "name_en": ing["name_en"],
            "category": ing["category"],
            "category_ko": ing["category_ko"],
            "synonyms": ing["synonyms"],
            "stats": st,
            "indexed": st["total"] > 0,
        })

    if q:
        items.sort(key=lambda it: (order.get(it["id"], 9999), -it["stats"]["total"]))
    elif sort == "name":
        items.sort(key=lambda it: it["name_ko"])
    else:
        # 동점 처리는 id(ASCII)로 한다. 한글 이름으로 정렬하면 파이썬과 브라우저의
        # 로케일 규칙이 달라 서버 배포와 정적 배포의 목록 순서가 어긋난다.
        items.sort(key=lambda it: (-it["stats"]["human"], -it["stats"]["total"], it["id"]))

    return {"total": len(items), "items": items[offset:offset + limit]}


# ── 성분 상세 ────────────────────────────────────────────────────────────────
def ingredient_detail(conn, ref: Reference, iid: str, *, top_papers: int = 8) -> dict | None:
    ing = ref.ingredients.get(iid)
    if not ing:
        return None

    st = _stats_row(conn.execute(
        "SELECT * FROM ingredient_stats WHERE ingredient_id = ?", (iid,)).fetchone())

    outcomes = []
    for r in conn.execute(
            """SELECT * FROM ingredient_outcome_stats WHERE ingredient_id = ?
               ORDER BY human DESC, total DESC""", (iid,)):
        oc = ref.outcomes.get(r["outcome_id"])
        if not oc:
            continue
        outcomes.append({
            "outcome_id": r["outcome_id"],
            "label_ko": oc["label_ko"],
            "family": ref.family_of.get(r["outcome_id"], ""),
            "label_en": oc["label_en"],
            "total": r["total"],
            "human": r["human"],
            "human_significant": r["human_sig"],
            "human_null": r["human_null"],
            "human_unclear": r["human_unclear"],
        })

    # 대표 논문: 근거 위계(메타분석 > 체계적 문헌고찰 > RCT …) → 피인용 → 최신 순
    papers = attach_top_outcome(conn, [paper_row(r) for r in conn.execute(
        """SELECT p.* FROM papers p JOIN paper_ingredient pi ON pi.paper_id = p.id
           WHERE pi.ingredient_id = ? AND p.retracted = 0
           ORDER BY p.evidence_rank DESC, p.cited_by DESC, p.year DESC
           LIMIT ?""", (iid, top_papers))])

    by_type = {r["study_type"]: r["c"] for r in conn.execute(
        """SELECT p.study_type, COUNT(*) c FROM papers p
           JOIN paper_ingredient pi ON pi.paper_id = p.id
           WHERE pi.ingredient_id = ? GROUP BY 1""", (iid,))}

    by_year = [{"year": r["year"], "count": r["c"]} for r in conn.execute(
        """SELECT p.year, COUNT(*) c FROM papers p
           JOIN paper_ingredient pi ON pi.paper_id = p.id
           WHERE pi.ingredient_id = ? AND p.year IS NOT NULL
           GROUP BY 1 ORDER BY 1""", (iid,))]

    return {
        "id": iid,
        "name_ko": ing["name_ko"],
        "name_en": ing["name_en"],
        "category": ing["category"],
        "category_ko": ing["category_ko"],
        "synonyms": ing["synonyms"],
        "stats": st,
        "by_study_type": [
            {"study_type": k, "label_ko": STUDY_TYPES.get(k, (k, 0))[0], "count": v}
            for k, v in sorted(by_type.items(), key=lambda kv: -STUDY_TYPES.get(kv[0], ("", 0))[1])],
        "by_year": by_year,
        "outcomes": outcomes,
        "top_papers": papers,
        "summary": build_summary(ing, st, outcomes, papers),
    }


def build_summary(ing: dict, st: dict, outcomes: list[dict], papers: list[dict]) -> dict:
    """집계된 숫자만으로 한국어 요약을 만든다. 새로운 주장은 넣지 않는다."""
    if not st["total"]:
        note = ("논문이 없다는 건 '효과가 없다'는 뜻이 아니라 "
                "'아직 여기 못 모았다'는 뜻입니다.")
        return {
            "headline": f"{ing['name_ko']}은(는) 아직 모은 논문이 없습니다.",
            "lines": [note], "lede": note, "small": [],
        }
    lines = [
        f"모은 논문 {st['total']:,}건 중 사람에게 한 연구는 {st['human']:,}건입니다."
    ]
    if st["systematic"] or st["rct"]:
        lines.append(
            f"믿을 만한 연구로는 여러 연구 종합 {st['systematic']:,}건, "
            f"무작위 배정 시험 {st['rct']:,}건이 있습니다.")
    if st["year_min"] and st["year_max"]:
        lines.append(f"논문이 나온 해는 {st['year_min']}년부터 {st['year_max']}년까지입니다.")

    top = [o for o in outcomes if o["human"] > 0][:3]
    if top:
        parts = [f"{o['label_ko']} {o['human']:,}건" for o in top]
        lines.append("사람에게 한 연구가 가장 많이 재 본 것은 " + ", ".join(parts) + " 입니다.")
        o = top[0]
        lines.append(
            f"이 중 {o['label_ko']} 연구 {o['human']:,}건은 "
            f"차이 있었음 {o['human_significant']:,}건, "
            f"차이 없었음 {o['human_null']:,}건, "
            f"알 수 없음 {o['human_unclear']:,}건으로 갈립니다.")
    else:
        lines.append("사람에게 한 연구에서 잡힌 항목이 아직 없습니다.")

    if st["retracted"]:
        lines.append(f"나중에 취소된 논문 {st['retracted']:,}건은 숫자에서 뺐습니다.")

    # 화면 상단에 크게 놓을 한 문단(lede)과, 그 아래 작게 붙일 부속 정보(small).
    # 논문 총계·사람 대상 수는 표제 숫자와 표에서 이미 보이므로 lede 에서 뺀다.
    if top:
        o = top[0]
        lede = (f"가장 많이 재 본 것은 {o['label_ko']}입니다. "
                f"사람에게 한 연구 {o['human']:,}건 중에 "
                f"차이가 있었다는 논문이 {o['human_significant']:,}건, "
                f"차이가 없었다는 논문이 {o['human_null']:,}건입니다.")
    else:
        lede = "사람에게 한 연구에서 잡힌 항목이 아직 없습니다."

    small = []
    if st["year_min"] and st["year_max"]:
        small.append(f"{st['year_min']}–{st['year_max']}년")
    if st["systematic"]:
        small.append(f"여러 연구 종합 {st['systematic']:,}")
    if st["rct"]:
        small.append(f"무작위 배정 시험 {st['rct']:,}")
    if st["preclinical"]:
        small.append(f"동물·세포 {st['preclinical']:,}")
    if st["retracted"]:
        small.append(f"취소된 논문 {st['retracted']:,} (숫자에서 뺌)")

    headline = (f"{ing['name_ko']}({ing['name_en']}) — 논문 {st['total']:,}건, "
                f"사람 {st['human']:,}건")
    return {"headline": headline, "lines": lines, "lede": lede, "small": small,
            "representative_titles": [p["title"] for p in papers[:3]]}


# ── 성분별 논문 목록 ─────────────────────────────────────────────────────────
def ingredient_papers(conn, iid: str, *, outcome: str = "", subject: str = "",
                      study_type: str = "", direction: str = "",
                      page: int = 1, page_size: int = PAGE_SIZE) -> dict:
    where = ["pi.ingredient_id = ?"]
    params: list = [iid]
    joins = "JOIN paper_ingredient pi ON pi.paper_id = p.id"
    select_extra = ""

    if outcome:
        joins += " JOIN paper_outcome po ON po.paper_id = p.id AND po.outcome_id = ?"
        params.insert(0, outcome)
        select_extra = ", po.direction, po.evidence, po.outcome_id"
        if direction:
            where.append("po.direction = ?")
            params.append(direction)
    elif direction:
        # 지표를 고르지 않았다면 그 논문의 대표 지표(점수 최상위, 동점이면 id 순)
        # 방향으로 거른다. attach_top_outcome 이 화면에 보여주는 그 방향이다.
        where.append("""(SELECT po2.direction FROM paper_outcome po2
                         WHERE po2.paper_id = p.id
                         ORDER BY po2.score DESC, po2.outcome_id LIMIT 1) = ?""")
        params.append(direction)
    if subject:
        where.append("p.subject = ?")
        params.append(subject)
    if study_type:
        where.append("p.study_type = ?")
        params.append(study_type)

    clause = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) c FROM papers p {joins} WHERE {clause}", params).fetchone()["c"]
    offset = max(0, (page - 1) * page_size)
    rows = conn.execute(
        f"""SELECT p.*{select_extra} FROM papers p {joins} WHERE {clause}
            ORDER BY p.evidence_rank DESC, p.cited_by DESC, p.year DESC
            LIMIT ? OFFSET ?""", [*params, page_size, offset]).fetchall()
    items = [paper_row(r, with_evidence=True) for r in rows]
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": attach_top_outcome(conn, items),
    }


# ── 지표(효능) 목록 / 역방향 검색 ────────────────────────────────────────────
def outcome_list(conn, ref: Reference) -> list[dict]:
    agg = {r["outcome_id"]: r for r in conn.execute(
        """SELECT outcome_id, COUNT(*) ingredients, SUM(total) papers, SUM(human) human
           FROM ingredient_outcome_stats GROUP BY outcome_id""")}
    items = []
    for oid, oc in ref.outcomes.items():
        a = agg.get(oid)
        items.append({
            "id": oid,
            "label_ko": oc["label_ko"],
            "label_en": oc["label_en"],
            "family": ref.family_of.get(oid, ""),
            "family_ko": ref.families.get(ref.family_of.get(oid, ""), ""),
            "aliases": oc["ko_aliases"],
            "ingredients": a["ingredients"] if a else 0,
            "papers": a["papers"] if a else 0,
            "human": a["human"] if a else 0,
        })
    items.sort(key=lambda it: (-it["human"], -it["papers"], it["label_ko"]))
    return items


def outcome_detail(conn, ref: Reference, oid: str, *, min_human: int = 1,
                   limit: int = 60, sort: str = "human") -> dict | None:
    oc = ref.outcomes.get(oid)
    if not oc:
        return None

    order = {
        "human": "human DESC, total DESC",
        "significant": "human_sig DESC, human DESC",
        "total": "total DESC, human DESC",
    }.get(sort, "human DESC, total DESC")

    rows = conn.execute(
        f"""SELECT * FROM ingredient_outcome_stats
            WHERE outcome_id = ? AND human >= ?
            ORDER BY {order} LIMIT ?""", (oid, min_human, limit)).fetchall()

    items = []
    for r in rows:
        ing = ref.ingredients.get(r["ingredient_id"])
        if not ing:
            continue
        items.append({
            "id": r["ingredient_id"],
            "name_ko": ing["name_ko"],
            "name_en": ing["name_en"],
            "category": ing["category"],
            "category_ko": ing["category_ko"],
            "total": r["total"],
            "human": r["human"],
            "human_significant": r["human_sig"],
            "human_null": r["human_null"],
            "human_unclear": r["human_unclear"],
        })

    top = [paper_row(r, with_evidence=True) for r in conn.execute(
        """SELECT p.*, po.direction, po.evidence FROM papers p
           JOIN paper_outcome po ON po.paper_id = p.id
           WHERE po.outcome_id = ? AND p.retracted = 0 AND p.subject = 'human'
           ORDER BY p.evidence_rank DESC, p.cited_by DESC, p.year DESC LIMIT 10""", (oid,))]

    return {
        "id": oid,
        "label_ko": oc["label_ko"],
        "label_en": oc["label_en"],
        "family": ref.family_of.get(oid, ""),
        "family_ko": ref.families.get(ref.family_of.get(oid, ""), ""),
        "aliases": oc["ko_aliases"],
        "measures": oc["measures"][:8],
        "ingredients": items,
        "top_papers": top,
        "note": "연구가 몇 건인지로만 줄 세웠습니다. 위에 있다고 효과가 큰 게 아닙니다.",
    }


# ── 통합 검색 ────────────────────────────────────────────────────────────────
def unified_search(conn, ref: Reference, q: str, *, limit: int = 10) -> dict:
    """성분 이름이면 성분을, 효능 표현이면 지표를 우선 돌려준다.

    둘 다 아니면 초록 전문검색으로 넘어가 관련 성분을 모아 준다.
    """
    q = (q or "").strip()
    result = {"query": q, "ingredients": [], "outcomes": [], "fulltext": [], "mode": "empty"}
    if not q:
        return result

    stats = {r["ingredient_id"]: r for r in conn.execute("SELECT * FROM ingredient_stats")}
    for iid, score in ref.find_ingredients(q, limit=limit):
        ing = ref.ingredients[iid]
        st = _stats_row(stats.get(iid))
        result["ingredients"].append({
            "id": iid, "name_ko": ing["name_ko"], "name_en": ing["name_en"],
            "category": ing["category"], "category_ko": ing["category_ko"],
            "score": score, "stats": st,
        })

    out_stats = {r["outcome_id"]: r for r in conn.execute(
        """SELECT outcome_id, COUNT(*) ingredients, SUM(human) human
           FROM ingredient_outcome_stats GROUP BY outcome_id""")}
    for oid, score in ref.find_outcomes(q, limit=5):
        oc = ref.outcomes[oid]
        a = out_stats.get(oid)
        result["outcomes"].append({
            "id": oid, "label_ko": oc["label_ko"], "label_en": oc["label_en"],
            "score": score,
            "ingredients": a["ingredients"] if a else 0,
            "human": a["human"] if a else 0,
        })

    if result["ingredients"] and (not result["outcomes"]
                                  or result["ingredients"][0]["score"] >= result["outcomes"][0]["score"]):
        result["mode"] = "ingredient"
    elif result["outcomes"]:
        result["mode"] = "outcome"
    else:
        result["mode"] = "fulltext"
        result["fulltext"] = fulltext_ingredients(conn, ref, q, limit=limit)
    return result


def _fts_query(q: str) -> str:
    """사용자 입력을 FTS5 가 안전하게 받아들이는 형태로 바꾼다."""
    tokens = re.findall(r"[0-9A-Za-z가-힣\-]+", q)
    return " OR ".join(f'"{t}"' for t in tokens if len(t) > 1)


def fulltext_ingredients(conn, ref: Reference, q: str, *, limit: int = 10) -> list[dict]:
    match = _fts_query(q)
    if not match:
        return []
    try:
        rows = conn.execute(
            """SELECT pi.ingredient_id AS iid, COUNT(*) c,
                      SUM(p.subject = 'human') human
               FROM papers_fts f
               JOIN papers p            ON p.id = f.rowid
               JOIN paper_ingredient pi ON pi.paper_id = p.id
               WHERE papers_fts MATCH ? AND p.retracted = 0
               GROUP BY 1 ORDER BY human DESC, c DESC LIMIT ?""",
            (match, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        ing = ref.ingredients.get(r["iid"])
        if ing:
            out.append({"id": r["iid"], "name_ko": ing["name_ko"], "name_en": ing["name_en"],
                        "category": ing["category"], "category_ko": ing["category_ko"],
                        "papers": r["c"], "human": r["human"]})
    return out


def fulltext_papers(conn, q: str, *, limit: int = 30) -> list[dict]:
    match = _fts_query(q)
    if not match:
        return []
    try:
        rows = conn.execute(
            """SELECT p.* FROM papers_fts f JOIN papers p ON p.id = f.rowid
               WHERE papers_fts MATCH ? AND p.retracted = 0
               ORDER BY p.evidence_rank DESC, p.cited_by DESC LIMIT ?""",
            (match, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return attach_top_outcome(conn, [paper_row(r) for r in rows])


def paper_detail(conn, ref: Reference, pid: int) -> dict | None:
    r = conn.execute("SELECT * FROM papers WHERE id = ?", (pid,)).fetchone()
    if not r:
        return None
    d = paper_row(r)
    d["abstract"] = r["abstract"]
    d["mesh"] = json.loads(r["mesh"] or "[]")
    d["pub_types"] = json.loads(r["pub_types"] or "[]")
    d["ingredients"] = [
        {"id": x["ingredient_id"],
         "name_ko": ref.ingredients.get(x["ingredient_id"], {}).get("name_ko", x["ingredient_id"]),
         "matched_term": x["matched_term"]}
        for x in conn.execute(
            "SELECT * FROM paper_ingredient WHERE paper_id = ?", (pid,))]
    d["outcomes"] = [
        {"id": x["outcome_id"],
         "label_ko": ref.outcomes.get(x["outcome_id"], {}).get("label_ko", x["outcome_id"]),
         "direction": x["direction"],
         "direction_ko": DIRECTIONS.get(x["direction"], x["direction"]),
         "evidence": x["evidence"],
         "matched": json.loads(x["matched"] or "[]")}
        for x in conn.execute("SELECT * FROM paper_outcome WHERE paper_id = ?", (pid,))]
    return d


# ── 정적 사이트 내보내기 ─────────────────────────────────────────────────────
# 서버 없이 도는 배포를 위해 색인 하나와 상세 파일 여러 개로 나눠 쓴다.
# 예전에는 전부를 한 파일에 담느라 성분당 상위 40건만 실었는데, 그러면 "뼈 건강
# (233)" 을 골라도 그 40건 안에 든 2건만 나와 목록과 숫자가 어긋났다. 지금은
# 성분 상세를 열 때 그 성분 파일만 받아오므로 논문을 전부 실을 수 있다.

SNAPSHOT_PAPER_CAP = 2000        # 병적으로 큰 성분 하나가 파일을 키우지 않도록


def _site_papers(conn, iid: str, limit: int) -> tuple[list[dict], bool]:
    """정적 배포용 논문 목록과 잘렸는지 여부.

    서버가 없으면 페이지네이션 질의를 못 하므로 브라우저가 걸러 쓴다. 그래서 각
    논문에 그 논문이 분류된 지표 목록을 함께 넣는다(지표 필터가 동작해야 하므로).
    """
    total = conn.execute(
        "SELECT COUNT(*) c FROM paper_ingredient WHERE ingredient_id = ?", (iid,)
    ).fetchone()["c"]
    rows = conn.execute(
        """SELECT p.* FROM papers p JOIN paper_ingredient pi ON pi.paper_id = p.id
           WHERE pi.ingredient_id = ?
           ORDER BY p.retracted ASC, p.evidence_rank DESC, p.cited_by DESC, p.year DESC
           LIMIT ?""", (iid, limit)).fetchall()
    items = attach_top_outcome(conn, [paper_row(r, with_evidence=True) for r in rows])
    if items:
        ids = [it["id"] for it in items]
        placeholders = ",".join("?" * len(ids))
        per: dict[int, list[str]] = {}
        for r in conn.execute(
                f"SELECT paper_id, outcome_id FROM paper_outcome WHERE paper_id IN ({placeholders})",
                ids):
            per.setdefault(r["paper_id"], []).append(r["outcome_id"])
        for it in items:
            it["outcome_ids"] = per.get(it["id"], [])
    return items, total > len(items)


def export_site(conn, out_dir, *, paper_cap: int = SNAPSHOT_PAPER_CAP,
                outcome_limit: int = 200, top_papers: int = 8) -> dict:
    """정적 배포용 파일 묶음을 out_dir 에 쓴다.

        index.json          코퍼스 요약·성분 목록·지표 목록·검색 색인
        i/<성분id>.json      성분 상세 + 그 성분의 논문 전부
        o/<지표id>.json      지표 상세 (효능 → 성분)

    web/app.js 가 이 구조를 읽어 /api/* 응답을 그대로 흉내 낸다. 따라서 화면
    코드는 서버 배포와 정적 배포에서 완전히 동일하다.
    """
    import ingest.config as cfg
    from ingest.classify import DIRECTIONS, STUDY_TYPES, SUBJECTS

    out_dir = pathlib.Path(out_dir)
    (out_dir / "i").mkdir(parents=True, exist_ok=True)
    (out_dir / "o").mkdir(parents=True, exist_ok=True)

    ingredients = json.loads(cfg.INGREDIENTS_JSON.read_text(encoding="utf-8"))["ingredients"]
    outcomes = json.loads(cfg.OUTCOMES_JSON.read_text(encoding="utf-8"))["outcomes"]
    ref = Reference(ingredients, outcomes)

    def write(rel: str, payload) -> int:
        path = out_dir / rel
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        return path.stat().st_size

    ing_list, ing_bytes, max_papers, truncated = [], 0, 0, []
    for iid in ref.ingredients:
        d = ingredient_detail(conn, ref, iid, top_papers=top_papers)
        d["papers"], d["papers_truncated"] = _site_papers(conn, iid, paper_cap)
        if d["papers_truncated"]:
            truncated.append(iid)
        max_papers = max(max_papers, len(d["papers"]))
        ing_bytes += write(f"i/{iid}.json", d)
        ing_list.append({
            "id": iid, "name_ko": d["name_ko"], "name_en": d["name_en"],
            "category": d["category"], "category_ko": d["category_ko"],
            "synonyms": d["synonyms"], "stats": d["stats"],
            "indexed": d["stats"]["total"] > 0,
        })

    out_bytes = 0
    for oid in ref.outcomes:
        out_bytes += write(f"o/{oid}.json",
                           outcome_detail(conn, ref, oid, min_human=1, limit=outcome_limit))

    index = {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "corpus": corpus_summary(conn),
        "meta": {
            "categories": ref.categories,
            "outcome_families": ref.families,
            "study_types": {k: v[0] for k, v in STUDY_TYPES.items()},
            "subjects": SUBJECTS,
            "directions": DIRECTIONS,
            "ingredient_count": len(ref.ingredients),
            "outcome_count": len(ref.outcomes),
            "paper_cap": paper_cap,
        },
        "outcomes": outcome_list(conn, ref),
        "ingredients": ing_list,
        # 검색은 브라우저에서 한다. 서버와 같은 표기 색인을 그대로 넘겨준다.
        "search_index": ref.search_index(),
    }
    index_bytes = write("index.json", index)

    return {
        "out_dir": str(out_dir),
        "index_bytes": index_bytes,
        "ingredient_files": len(ing_list), "ingredient_bytes": ing_bytes,
        "outcome_files": len(ref.outcomes), "outcome_bytes": out_bytes,
        "max_papers_in_one_file": max_papers,
        "truncated": truncated,
        "papers": index["corpus"]["papers"],
        "fixture_papers": index["corpus"].get("fixture_papers", 0),
    }
