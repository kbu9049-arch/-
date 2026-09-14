#!/usr/bin/env python3
"""성분 근거 코퍼스 구축 CLI.

  python -m ingest.build probe                 # 문헌 API 연결·질의 문법 점검
  python -m ingest.build harvest --target 100000
  python -m ingest.build classify              # 저장된 논문 재분류
  python -m ingest.build aggregate             # 집계 테이블·전문검색 색인 생성
  python -m ingest.build all --target 100000   # harvest → classify → aggregate
  python -m ingest.build stats
  python -m ingest.build load-jsonl FILE       # 내려받아 둔 JSONL 을 같은 경로로 적재
  python -m ingest.build export web/data       # 정적 배포용 파일 묶음

harvest 는 언제든 중단했다가 다시 실행할 수 있다. 진행 상태(커서)는 harvest_state
테이블에 저장된다.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone

from ingest import config
from ingest.classify import DIRECTIONS as DIRECTION_LABEL
from ingest.classify import STUDY_TYPES, Classifier
from ingest.sources.europepmc import EuropePMC, build_query
from ingest.sources.http import Client
from ingest.sources.pubmed import PubMed
from ingest.sources.pubmed import build_query as pubmed_query


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── DB ───────────────────────────────────────────────────────────────────────
def open_db(path=None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((config.ROOT / "ingest" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def require_db() -> sqlite3.Connection:
    """이미 있는 색인 DB 만 연다. 읽기 전용 명령이 빈 DB 를 새로 만들지 않게 한다."""
    if not config.DB_PATH.exists():
        raise SystemExit(
            f"색인 DB가 없습니다: {config.DB_PATH}\n"
            "  먼저 논문을 수집하세요:  python -m ingest.build all --target 100000")
    return open_db()


def load_reference() -> tuple[list[dict], list[dict]]:
    ing = json.loads(config.INGREDIENTS_JSON.read_text(encoding="utf-8"))["ingredients"]
    out = json.loads(config.OUTCOMES_JSON.read_text(encoding="utf-8"))["outcomes"]
    return ing, out


def set_meta(conn, key: str, value) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


# ── 저장 + 분류 ──────────────────────────────────────────────────────────────
def store_paper(conn: sqlite3.Connection, clf: Classifier, paper: dict) -> tuple[int, bool]:
    """논문 1건을 분류해 저장한다. (paper_id, 새로 추가되었는지) 를 돌려준다."""
    res = clf.classify(paper)
    existed = conn.execute("SELECT 1 FROM papers WHERE source = ? AND ext_id = ?",
                           (paper["source"], paper["ext_id"])).fetchone() is not None

    row = conn.execute(
        """INSERT INTO papers (source, ext_id, pmid, pmcid, doi, title, abstract, journal,
                               year, authors, pub_types, mesh, study_type, subject,
                               evidence_rank, retracted, cited_by, is_oa, url, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (source, ext_id) DO UPDATE SET
               cited_by      = MAX(excluded.cited_by, papers.cited_by),
               abstract      = COALESCE(NULLIF(excluded.abstract, ''), papers.abstract),
               mesh          = CASE WHEN excluded.mesh = '[]' THEN papers.mesh ELSE excluded.mesh END,
               study_type    = excluded.study_type,
               subject       = excluded.subject,
               evidence_rank = excluded.evidence_rank,
               retracted     = MAX(excluded.retracted, papers.retracted)
           RETURNING id""",
        (paper["source"], paper["ext_id"], paper.get("pmid"), paper.get("pmcid"),
         paper.get("doi"), paper["title"], paper.get("abstract", ""), paper.get("journal", ""),
         paper.get("year"), paper.get("authors", ""),
         json.dumps(paper.get("pub_types") or [], ensure_ascii=False),
         json.dumps(paper.get("mesh") or [], ensure_ascii=False),
         res.study_type, res.subject, res.evidence_rank, int(res.retracted),
         paper.get("cited_by", 0), paper.get("is_oa", 0), paper.get("url", ""),
         paper.get("fetched_at") or now()),
    ).fetchone()
    pid, is_new = row["id"], not existed

    conn.execute("DELETE FROM paper_ingredient WHERE paper_id = ?", (pid,))
    conn.executemany(
        "INSERT OR REPLACE INTO paper_ingredient (paper_id, ingredient_id, matched_term) VALUES (?,?,?)",
        [(pid, iid, term) for iid, term in res.ingredients])

    conn.execute("DELETE FROM paper_outcome WHERE paper_id = ?", (pid,))
    conn.executemany(
        "INSERT OR REPLACE INTO paper_outcome (paper_id, outcome_id, score, direction, evidence, matched) "
        "VALUES (?,?,?,?,?,?)",
        [(pid, h.outcome_id, h.score, h.direction, h.evidence[:600],
          json.dumps(h.matched, ensure_ascii=False)) for h in res.outcomes])
    return pid, is_new


# ── probe ────────────────────────────────────────────────────────────────────
def cmd_probe(args) -> int:
    """API 도달 가능 여부와 질의 문법이 실제로 먹히는지 확인한다."""
    ingredients, _ = load_reference()
    sample = next(i for i in ingredients if i["id"] == args.ingredient) \
        if args.ingredient else ingredients[0]
    epmc = EuropePMC(Client(verbose=True))

    print(f"Europe PMC 점검 — 성분: {sample['name_ko']} ({sample['name_en']})")
    ok = True
    base = build_query(sample["synonyms"])
    try:
        t0 = time.time()
        base_hits = epmc.hit_count(base)
        print(f"  기본 질의            {base_hits:>9,}건  ({time.time() - t0:.1f}초)")
        print(f"    → {base}")
        if base_hits == 0:
            print("  ✗ 결과가 0건입니다. 검색어를 확인하세요.")
            ok = False
    except Exception as e:
        print(f"  ✗ 연결 실패: {e}")
        return 2

    for name, clause, _ in config.QUERY_TIERS:
        if not clause:
            continue
        try:
            hits = epmc.hit_count(build_query(sample["synonyms"], clause))
            flag = "" if hits else "   ← 0건: PUB_TYPE 필터가 먹지 않을 수 있음"
            print(f"  {name:<10} 필터   {hits:>9,}건{flag}")
            if not hits:
                ok = False
        except Exception as e:
            print(f"  {name:<10} 필터   실패: {e}")
            ok = False

    # 실제 레코드를 1건 받아 core 필드가 오는지 본다.
    try:
        page, _, _ = next(epmc.search(base, limit=1))
        if page:
            r = page[0]
            print(f"  레코드 예시          PMID {r['pmid']} / {r['year']} / "
                  f"초록 {len(r['abstract'])}자 / MeSH {len(r['mesh'])}개 / "
                  f"pubType {len(r['pub_types'])}개")
            if not r["abstract"]:
                print("  ! 초록이 비어 있습니다. resultType=core 응답인지 확인하세요.")
        else:
            print("  ! 레코드를 받지 못했습니다.")
            ok = False
    except Exception as e:
        print(f"  ✗ 레코드 조회 실패: {e}")
        ok = False

    if ok and not args.no_tier_fallback:
        print("\n점검 통과. `python -m ingest.build all --target 100000` 로 수집하세요.")
    elif not ok:
        print("\nPUB_TYPE 필터가 동작하지 않으면 --filter-profile basic 으로 실행하세요.")
    return 0 if ok else 1


# ── harvest ──────────────────────────────────────────────────────────────────
def cmd_harvest(args) -> int:
    ingredients, outcomes = load_reference()
    if args.ingredients:
        wanted = {s.strip() for s in args.ingredients.split(",") if s.strip()}
        ingredients = [i for i in ingredients if i["id"] in wanted]
        if not ingredients:
            print(f"성분 id 를 찾지 못했습니다: {sorted(wanted)}", file=sys.stderr)
            return 2

    # 수집 대상은 좁힐 수 있어도 성분 매칭은 항상 전체 사전으로 한다.
    # 한 논문이 여러 성분을 다루면 그 연결을 모두 남겨야 하기 때문이다.
    all_ingredients, _ = load_reference()
    clf = Classifier(all_ingredients, outcomes)

    conn = open_db()
    client = Client(rate_per_sec=args.rate)
    source = PubMed(client) if args.source == "pubmed" else EuropePMC(client)

    tiers = config.QUERY_TIERS if args.filter_profile == "tiered" else [("all", "", 1.0)]
    total_unique = conn.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
    started, added_run, fetched_run = time.time(), 0, 0
    print(f"수집 시작 — 성분 {len(ingredients)}종 / 목표 {args.target:,}건 / "
          f"성분당 최대 {args.limit_per_ingredient:,}건 / 프로파일 {args.filter_profile}")
    print(f"현재 DB 보유: {total_unique:,}건\n")

    try:
        for n, ing in enumerate(ingredients, 1):
            if total_unique >= args.target:
                print(f"\n목표 {args.target:,}건 도달 — 수집을 멈춥니다.")
                break
            ing_added = ing_fetched = 0
            for tier_name, clause, ratio in tiers:
                budget = max(1, int(args.limit_per_ingredient * ratio))
                key = f"{ing['id']}:{tier_name}:{args.source}"
                state = conn.execute("SELECT * FROM harvest_state WHERE query_key = ?",
                                     (key,)).fetchone()
                if state and state["done"] and not args.refresh:
                    ing_fetched += state["fetched"]
                    continue
                cursor = (state["cursor"] if state and state["cursor"] and not args.refresh else "*")
                already = state["fetched"] if state and not args.refresh else 0
                remaining = budget - already
                if remaining <= 0:
                    continue

                if args.source == "pubmed":
                    query = pubmed_query(ing["synonyms"])
                    pages = ((page, "", 0) for page in source.search(query, remaining))
                else:
                    query = build_query(ing["synonyms"], clause)
                    pages = source.search(query, remaining, cursor=cursor)

                hit_count, got = 0, 0
                try:
                    for records, next_cursor, hits in pages:
                        hit_count = hits or hit_count
                        for rec in records:
                            rec["fetched_at"] = now()
                            _, is_new = store_paper(conn, clf, rec)
                            if is_new:
                                total_unique += 1
                                added_run += 1
                                ing_added += 1
                        got += len(records)
                        fetched_run += len(records)
                        conn.execute(
                            """INSERT INTO harvest_state
                               (query_key, ingredient_id, tier, query, cursor, hit_count,
                                fetched, done, updated_at)
                               VALUES (?,?,?,?,?,?,?,?,?)
                               ON CONFLICT (query_key) DO UPDATE SET
                                 cursor=excluded.cursor, hit_count=excluded.hit_count,
                                 fetched=excluded.fetched, done=excluded.done,
                                 updated_at=excluded.updated_at""",
                            (key, ing["id"], tier_name, query, next_cursor, hit_count,
                             already + got, int(not next_cursor), now()))
                        conn.commit()
                        if total_unique >= args.target:
                            break
                except Exception as e:
                    conn.commit()
                    print(f"  ! {ing['id']}/{tier_name} 실패: {e}")
                    conn.execute(
                        "INSERT INTO harvest_state (query_key, ingredient_id, tier, query, "
                        "note, updated_at) VALUES (?,?,?,?,?,?) "
                        "ON CONFLICT (query_key) DO UPDATE SET note=excluded.note, "
                        "updated_at=excluded.updated_at",
                        (key, ing["id"], tier_name, query, str(e)[:300], now()))
                    conn.commit()
                    if args.stop_on_error:
                        return 1
                ing_fetched += got

            elapsed = time.time() - started
            rate = fetched_run / elapsed if elapsed else 0
            print(f"[{n:>3}/{len(ingredients)}] {ing['name_ko']:<16} "
                  f"수집 {ing_fetched:>5,} / 신규 {ing_added:>5,} | "
                  f"누적 {total_unique:>7,}건 | {rate:5.1f}건/초")
    except KeyboardInterrupt:
        conn.commit()
        print("\n중단됨 — 진행 상태는 저장되었습니다. 같은 명령으로 이어서 실행하세요.")

    set_meta(conn, "last_harvest", now())
    set_meta(conn, "harvest_source", args.source)
    conn.commit()
    print(f"\n수집 종료: 이번 실행 {fetched_run:,}건 조회 / 신규 {added_run:,}건 / "
          f"DB 총 {total_unique:,}건 / 요청 {client.requests:,}회")
    return 0


# ── load-jsonl ───────────────────────────────────────────────────────────────
def cmd_load_jsonl(args) -> int:
    """JSONL 파일을 수집과 동일한 분류·저장 경로로 적재한다.

    Europe PMC/PubMed 응답을 따로 내려받아 두었거나, 기관 내부 문헌 덤프를 쓸 때 사용.
    한 줄에 논문 1건: {"source","ext_id","pmid","title","abstract","journal","year",
                       "authors","pub_types":[],"mesh":[],"cited_by","url"}
    """
    ingredients, outcomes = load_reference()
    clf = Classifier(ingredients, outcomes)
    conn = open_db()
    added = seen = skipped = 0
    with open(args.path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  {line_no}행 JSON 오류: {e}", file=sys.stderr)
                skipped += 1
                continue
            if not rec.get("ext_id") or not rec.get("title"):
                skipped += 1
                continue
            rec.setdefault("source", "MED")
            rec.setdefault("fetched_at", now())
            _, is_new = store_paper(conn, clf, rec)
            seen += 1
            added += int(is_new)
            if seen % 2000 == 0:
                conn.commit()
                print(f"  {seen:,}건 처리…")
    conn.commit()
    print(f"적재 완료: {seen:,}건 처리 / 신규 {added:,}건 / 건너뜀 {skipped:,}건")
    return 0


# ── classify ─────────────────────────────────────────────────────────────────
def cmd_classify(args) -> int:
    ingredients, outcomes = load_reference()
    clf = Classifier(ingredients, outcomes)
    conn = open_db()
    total = conn.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
    print(f"{total:,}건 재분류 중…")
    done = 0
    batch = conn.execute("SELECT id, title, abstract, pub_types, mesh FROM papers")
    for row in batch.fetchall():
        res = clf.classify({
            "title": row["title"], "abstract": row["abstract"],
            "pub_types": json.loads(row["pub_types"] or "[]"),
            "mesh": json.loads(row["mesh"] or "[]"),
        })
        conn.execute("UPDATE papers SET study_type=?, subject=?, evidence_rank=?, retracted=? "
                     "WHERE id=?",
                     (res.study_type, res.subject, res.evidence_rank, int(res.retracted), row["id"]))
        conn.execute("DELETE FROM paper_ingredient WHERE paper_id=?", (row["id"],))
        conn.executemany("INSERT OR REPLACE INTO paper_ingredient VALUES (?,?,?)",
                         [(row["id"], iid, t) for iid, t in res.ingredients])
        conn.execute("DELETE FROM paper_outcome WHERE paper_id=?", (row["id"],))
        conn.executemany("INSERT OR REPLACE INTO paper_outcome VALUES (?,?,?,?,?,?)",
                         [(row["id"], h.outcome_id, h.score, h.direction, h.evidence[:600],
                           json.dumps(h.matched, ensure_ascii=False)) for h in res.outcomes])
        done += 1
        if done % 5000 == 0:
            conn.commit()
            print(f"  {done:,}/{total:,}")
    conn.commit()
    print(f"재분류 완료: {done:,}건")
    return 0


# ── aggregate ────────────────────────────────────────────────────────────────
def cmd_aggregate(args) -> int:
    conn = open_db()
    print("집계 테이블 생성 중…")
    conn.execute("DELETE FROM ingredient_stats")
    conn.execute("""
        INSERT INTO ingredient_stats
          (ingredient_id, total, human, systematic, rct, preclinical, retracted, year_min, year_max)
        SELECT pi.ingredient_id,
               COUNT(*),
               SUM(p.subject = 'human'),
               SUM(p.study_type IN ('meta_analysis','systematic_review')),
               SUM(p.study_type = 'rct'),
               SUM(p.study_type = 'preclinical'),
               SUM(p.retracted),
               MIN(p.year), MAX(p.year)
        FROM paper_ingredient pi JOIN papers p ON p.id = pi.paper_id
        GROUP BY pi.ingredient_id""")
    # 문헌 DB 가 보고한 전체 검색 결과 수(수집 상한과 무관한 '실제 논문 수')
    conn.execute("""
        UPDATE ingredient_stats SET hit_count = COALESCE((
            SELECT MAX(hs.hit_count) FROM harvest_state hs
            WHERE hs.ingredient_id = ingredient_stats.ingredient_id AND hs.tier = 'all'), 0)""")

    conn.execute("DELETE FROM ingredient_outcome_stats")
    conn.execute("""
        INSERT INTO ingredient_outcome_stats
          (ingredient_id, outcome_id, total, human, human_sig, human_null, human_unclear)
        SELECT pi.ingredient_id, po.outcome_id,
               COUNT(*),
               SUM(p.subject = 'human'),
               SUM(p.subject = 'human' AND po.direction = 'significant'),
               SUM(p.subject = 'human' AND po.direction = 'null'),
               SUM(p.subject = 'human' AND po.direction = 'unclear')
        FROM paper_ingredient pi
        JOIN paper_outcome po ON po.paper_id = pi.paper_id
        JOIN papers p         ON p.id = pi.paper_id
        WHERE p.retracted = 0
        GROUP BY pi.ingredient_id, po.outcome_id""")

    print("전문검색 색인 재구축 중…")
    conn.execute("INSERT INTO papers_fts (papers_fts) VALUES ('rebuild')")
    set_meta(conn, "last_aggregate", now())
    conn.execute("ANALYZE")
    conn.commit()
    print("완료.")
    return cmd_stats(args)


# ── stats ────────────────────────────────────────────────────────────────────
def cmd_stats(args) -> int:
    conn = require_db()

    def q(sql):
        return conn.execute(sql).fetchone()[0]

    total = q("SELECT COUNT(*) FROM papers")
    print("\n" + "─" * 62)
    print(f"논문 총계          {total:>10,}")
    if not total:
        print("아직 수집된 논문이 없습니다. `python -m ingest.build all` 을 실행하세요.")
        print("─" * 62)
        return 0

    with_abstract = q("SELECT COUNT(*) FROM papers WHERE abstract <> ''")
    human = q("SELECT COUNT(*) FROM papers WHERE subject = 'human'")
    retracted = q("SELECT COUNT(*) FROM papers WHERE retracted = 1")
    pi_rows = q("SELECT COUNT(*) FROM paper_ingredient")
    pi_ings = q("SELECT COUNT(DISTINCT ingredient_id) FROM paper_ingredient")
    po_rows = q("SELECT COUNT(*) FROM paper_outcome")
    po_outs = q("SELECT COUNT(DISTINCT outcome_id) FROM paper_outcome")
    y_min = q("SELECT MIN(year) FROM papers WHERE year IS NOT NULL")
    y_max = q("SELECT MAX(year) FROM papers WHERE year IS NOT NULL")

    print(f"  초록 있음        {with_abstract:>10,}")
    print(f"  사람 대상        {human:>10,}")
    print(f"  철회 논문        {retracted:>10,}")
    print(f"성분 연결          {pi_rows:>10,}")
    print(f"  연결된 성분 수   {pi_ings:>10,}")
    print(f"지표 연결          {po_rows:>10,}")
    print(f"  연결된 지표 수   {po_outs:>10,}")
    print(f"연도 범위          {y_min} ~ {y_max}")

    print("\n연구 유형별")
    for r in conn.execute("SELECT study_type, COUNT(*) c FROM papers GROUP BY 1 ORDER BY c DESC"):
        label = STUDY_TYPES.get(r["study_type"], (r["study_type"], 0))[0]
        print(f"  {label:<18} {r['c']:>8,}")

    print("\n사람 대상 연구의 결과 방향")
    for r in conn.execute("""SELECT po.direction, COUNT(*) c FROM paper_outcome po
                             JOIN papers p ON p.id = po.paper_id
                             WHERE p.subject = 'human' GROUP BY 1 ORDER BY c DESC"""):
        print(f"  {DIRECTION_LABEL.get(r['direction'], r['direction']):<18} {r['c']:>8,}")

    rows = conn.execute("""SELECT ingredient_id, total, human FROM ingredient_stats
                           ORDER BY total DESC LIMIT 10""").fetchall()
    if rows:
        print("\n논문이 많은 성분 상위 10")
        for r in rows:
            print(f"  {r['ingredient_id']:<22} 총 {r['total']:>6,}  사람 {r['human']:>6,}")
    print("─" * 62)
    return 0


# ── export ───────────────────────────────────────────────────────────────────
def cmd_export(args) -> int:
    """정적 배포용 파일 묶음. 서버 없이도 프런트를 띄울 수 있다."""
    from server import queries          # 서버와 같은 조회 로직을 쓴다
    conn = require_db()
    summary = queries.corpus_summary(conn)

    if not summary["papers"] and not args.allow_empty:
        raise SystemExit(
            "코퍼스가 비어 있어 내보내지 않았습니다.\n"
            "  그대로 내보내면 백지 사이트가 배포됩니다.\n"
            "  먼저 수집하세요:  python -m ingest.build all --target 100000\n"
            "  (의도한 것이라면 --allow-empty)")
    if summary.get("fixture_papers") and not args.allow_empty:
        raise SystemExit(
            f"합성 테스트 레코드 {summary['fixture_papers']:,}건이 섞여 있어 "
            "내보내지 않았습니다.\n  실제 논문이 아니므로 공개 배포하면 안 됩니다.\n"
            "  (화면 확인 목적이라면 --allow-empty)")

    out_dir = config.ROOT / args.path
    r = queries.export_site(conn, out_dir, paper_cap=args.paper_cap)
    mb = (r["index_bytes"] + r["ingredient_bytes"] + r["outcome_bytes"]) / 1e6
    print(f"{out_dir}")
    print(f"  index.json      {r['index_bytes'] / 1e6:.2f} MB  (첫 화면에서 이것만 받는다)")
    print(f"  i/*.json        {r['ingredient_files']}개 · {r['ingredient_bytes'] / 1e6:.2f} MB "
          f"(한 파일 최대 논문 {r['max_papers_in_one_file']:,}건)")
    print(f"  o/*.json        {r['outcome_files']}개 · {r['outcome_bytes'] / 1e6:.2f} MB")
    print(f"  합계            {mb:.2f} MB · 논문 {r['papers']:,}건")
    if r["truncated"]:
        print(f"  ! 논문이 {args.paper_cap:,}건을 넘어 잘린 성분 {len(r['truncated'])}종: "
              f"{', '.join(r['truncated'][:6])}"
              f"{' …' if len(r['truncated']) > 6 else ''}")
    return 0


# ── all ──────────────────────────────────────────────────────────────────────
def cmd_all(args) -> int:
    rc = cmd_harvest(args)
    if rc:
        return rc
    return cmd_aggregate(args)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ingest.build", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_harvest_args(sp):
        sp.add_argument("--target", type=int, default=config.DEFAULT_TARGET_PAPERS,
                        help="수집할 고유 논문 수 상한 (기본 %(default)s)")
        sp.add_argument("--limit-per-ingredient", type=int,
                        default=config.DEFAULT_LIMIT_PER_INGREDIENT,
                        help="성분 하나당 최대 수집 건수 (기본 %(default)s)")
        sp.add_argument("--ingredients", default="", help="쉼표로 구분한 성분 id (기본: 전체)")
        sp.add_argument("--source", choices=("europepmc", "pubmed"), default="europepmc")
        sp.add_argument("--filter-profile", choices=config.FILTER_PROFILES,
                        default=config.DEFAULT_FILTER_PROFILE)
        sp.add_argument("--rate", type=float, default=config.RATE_LIMIT_PER_SEC,
                        help="초당 요청 수 (기본 %(default)s)")
        sp.add_argument("--refresh", action="store_true", help="저장된 진행 상태를 무시하고 처음부터")
        sp.add_argument("--stop-on-error", action="store_true")

    sp = sub.add_parser("probe", help="API 연결과 질의 문법 점검")
    sp.add_argument("--ingredient", default="", help="점검에 쓸 성분 id")
    sp.add_argument("--no-tier-fallback", action="store_true")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("harvest", help="논문 수집 (재실행 가능)")
    add_harvest_args(sp)
    sp.set_defaults(func=cmd_harvest)

    sp = sub.add_parser("all", help="harvest → aggregate")
    add_harvest_args(sp)
    sp.set_defaults(func=cmd_all)

    sp = sub.add_parser("classify", help="저장된 논문 재분류")
    sp.set_defaults(func=cmd_classify)

    sp = sub.add_parser("aggregate", help="집계 테이블·전문검색 색인 생성")
    sp.set_defaults(func=cmd_aggregate)

    sp = sub.add_parser("stats", help="DB 요약")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("load-jsonl", help="JSONL 파일 적재")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_load_jsonl)

    sp = sub.add_parser("export", help="정적 배포용 파일 묶음")
    sp.add_argument("path", nargs="?", default="web/data")
    sp.add_argument("--paper-cap", type=int, default=2000,
                    help="성분 한 종당 담을 논문 수 상한 (기본 %(default)s)")
    sp.add_argument("--allow-empty", action="store_true",
                    help="빈 코퍼스나 테스트 픽스처도 내보낸다 (공개 배포 금지)")
    sp.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
