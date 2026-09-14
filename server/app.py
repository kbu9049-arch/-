"""성분 근거 검색 웹서버.

  uvicorn server.app:app --reload --port 8000

색인 DB(data/evidence.db)가 없으면 서버는 그대로 뜨되 모든 통계가 0 으로 나오고,
프런트가 '아직 수집 전' 안내를 띄운다. 데이터를 지어내지 않는다.
"""
from __future__ import annotations

import json
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ingest import config
from ingest.classify import DIRECTIONS, STUDY_TYPES, SUBJECTS
from server import queries
from server.live import LiveLookup

WEB_DIR = config.ROOT / "web"
LIVE_ENABLED = os.environ.get("LIVE_LOOKUP", "1") != "0"

app = FastAPI(
    title="성분 근거 찾기 API",
    description="광고에서 본 성분의 논문 근거를 찾고, 반대로 효능으로 성분을 찾는 API. "
                "모든 수치는 수집된 논문 레코드를 실제로 센 값입니다.",
    version="1.0.0",
)

_ingredients = json.loads(config.INGREDIENTS_JSON.read_text(encoding="utf-8"))["ingredients"]
_outcomes = json.loads(config.OUTCOMES_JSON.read_text(encoding="utf-8"))["outcomes"]
REF = queries.Reference(_ingredients, _outcomes)
LIVE = LiveLookup(_ingredients, _outcomes, enabled=LIVE_ENABLED)

_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        if not config.DB_PATH.exists():
            raise HTTPException(
                status_code=503,
                detail={"error": "corpus_missing",
                        "message": "색인 DB가 없습니다. `python -m ingest.build all` 로 "
                                   "논문을 수집한 뒤 다시 시작하세요.",
                        "db_path": str(config.DB_PATH)})
        _conn = queries.connect(config.DB_PATH)
    return _conn


def corpus_ready() -> bool:
    return config.DB_PATH.exists()


# ── 메타 ─────────────────────────────────────────────────────────────────────
@app.get("/api/meta", summary="코퍼스 요약과 화면에서 쓰는 코드 표")
def api_meta():
    payload = {
        "corpus_ready": corpus_ready(),
        "categories": REF.categories,
        "outcome_families": REF.families,
        "study_types": {k: v[0] for k, v in STUDY_TYPES.items()},
        "subjects": SUBJECTS,
        "directions": DIRECTIONS,
        "outcome_count": len(REF.outcomes),
        "ingredient_count": len(REF.ingredients),
        "live_lookup": LIVE_ENABLED,
        "disclaimer": {
            "not_medical_advice": "이 서비스는 의학적 조언이 아닙니다. 건강 관련 결정은 "
                                  "의사·약사와 상의하세요.",
            "no_ranking": "성분에 점수나 등급을 매기지 않습니다. 목록 순서는 연구 '건수' 순이며 "
                          "효과의 우열이 아닙니다.",
            "publication_bias": "효과가 없다는 결과는 상대적으로 덜 출판되는 경향(출판 편향)이 "
                                "있어, 유의한 결과의 비율이 실제보다 높게 보일 수 있습니다.",
            "auto_classification": "연구유형·결과지표·결과방향은 초록 문구에 대한 규칙 기반 "
                                   "자동 분류이며, 각 판정의 근거 문장을 함께 제공합니다.",
        },
    }
    if corpus_ready():
        payload["corpus"] = queries.corpus_summary(db())
    else:
        payload["corpus"] = {"papers": 0}
    return payload


@app.get("/api/outcomes", summary="효능·결과지표 목록 (역방향 검색 진입점)")
def api_outcomes():
    if not corpus_ready():
        return {"items": [{"id": o["id"], "label_ko": o["label_ko"], "label_en": o["label_en"],
                           "aliases": o["ko_aliases"], "ingredients": 0, "papers": 0, "human": 0}
                          for o in _outcomes]}
    return {"items": queries.outcome_list(db(), REF)}


@app.get("/api/outcomes/{outcome_id}", summary="특정 효능을 측정한 성분들 (효능 → 성분)")
def api_outcome(outcome_id: str,
                min_human: int = Query(1, ge=0),
                limit: int = Query(60, ge=1, le=300),
                sort: str = Query("human", pattern="^(human|significant|total)$")):
    data = queries.outcome_detail(db(), REF, outcome_id, min_human=min_human,
                                  limit=limit, sort=sort)
    if data is None:
        raise HTTPException(404, f"알 수 없는 지표 id: {outcome_id}")
    return data


@app.get("/api/ingredients", summary="성분 목록·검색")
def api_ingredients(q: str = "", category: str = "",
                    limit: int = Query(60, ge=1, le=300), offset: int = Query(0, ge=0),
                    sort: str = Query("papers", pattern="^(papers|name)$")):
    if not corpus_ready():
        raise HTTPException(503, "색인 DB가 아직 없습니다.")
    return queries.ingredient_list(db(), REF, q=q, category=category,
                                   limit=limit, offset=offset, sort=sort)


@app.get("/api/ingredients/{ingredient_id}", summary="성분 상세 (성분 → 논문)")
def api_ingredient(ingredient_id: str, top_papers: int = Query(8, ge=1, le=50)):
    data = queries.ingredient_detail(db(), REF, ingredient_id, top_papers=top_papers)
    if data is None:
        raise HTTPException(404, f"알 수 없는 성분 id: {ingredient_id}")
    return data


@app.get("/api/ingredients/{ingredient_id}/papers", summary="성분별 논문 목록 (필터·페이지)")
def api_ingredient_papers(ingredient_id: str, outcome: str = "", subject: str = "",
                          study_type: str = "", direction: str = "",
                          page: int = Query(1, ge=1),
                          page_size: int = Query(queries.PAGE_SIZE, ge=1, le=100)):
    if ingredient_id not in REF.ingredients:
        raise HTTPException(404, f"알 수 없는 성분 id: {ingredient_id}")
    return queries.ingredient_papers(db(), ingredient_id, outcome=outcome, subject=subject,
                                     study_type=study_type, direction=direction,
                                     page=page, page_size=page_size)


@app.get("/api/papers/{paper_id}", summary="논문 상세 (분류 근거 포함)")
def api_paper(paper_id: int):
    data = queries.paper_detail(db(), REF, paper_id)
    if data is None:
        raise HTTPException(404, "논문을 찾지 못했습니다.")
    return data


@app.get("/api/search", summary="통합 검색 — 성분 이름이든 효능 표현이든 받는다")
def api_search(q: str, limit: int = Query(10, ge=1, le=50)):
    if not corpus_ready():
        raise HTTPException(503, "색인 DB가 아직 없습니다.")
    return queries.unified_search(db(), REF, q, limit=limit)


@app.get("/api/search/papers", summary="초록 전문검색")
def api_search_papers(q: str, limit: int = Query(30, ge=1, le=100)):
    return {"items": queries.fulltext_papers(db(), q, limit=limit)}


@app.get("/api/live", summary="색인에 없는 검색어를 문헌 DB 에 실시간 질의")
def api_live(term: str, limit: int = Query(40, ge=5, le=100)):
    return LIVE.search(term, limit=limit)


@app.get("/api/health")
def api_health():
    ready = corpus_ready()
    papers = queries.corpus_summary(db())["papers"] if ready else 0
    return JSONResponse({"status": "ok", "corpus_ready": ready, "papers": papers},
                        status_code=200 if ready else 503)


# ── 정적 파일 ────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
