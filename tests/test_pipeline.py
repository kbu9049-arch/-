"""수집 → 분류 → 집계 → 조회 전체 경로 통합 테스트.

네트워크 없이 돌아간다. 합성 픽스처를 임시 DB 에 적재한 뒤, 웹 API 가 쓰는
조회 함수들이 실제로 올바른 수치를 돌려주는지 확인한다.
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def check_true(name, cond, hint=""):
    if not cond:
        FAILS.append(f"{name}: 거짓{(' — ' + hint) if hint else ''}")


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="evidence-test-"))
    fixture = tmp / "fixture.jsonl"
    db = tmp / "test.db"
    env = {**os.environ, "EVIDENCE_DB": str(db), "PYTHONPATH": str(ROOT)}

    def run(*args):
        r = subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        if r.returncode != 0:
            FAILS.append(f"{' '.join(args)} 실패:\n{r.stdout}\n{r.stderr}")
        return r

    run("tests/fixtures/make_fixture.py", str(fixture))
    check_true("픽스처 생성", fixture.exists())
    run("-m", "ingest.build", "load-jsonl", str(fixture))
    run("-m", "ingest.build", "aggregate")
    check_true("DB 생성", db.exists())
    if FAILS:
        return

    # 파이프라인이 만든 DB 를 서버와 같은 코드로 읽는다.
    from server import queries
    conn = queries.connect(db)
    ing = json.loads((ROOT / "data" / "ingredients.json").read_text(encoding="utf-8"))["ingredients"]
    out = json.loads((ROOT / "data" / "outcomes.json").read_text(encoding="utf-8"))["outcomes"]
    ref = queries.Reference(ing, out)

    fixture_lines = sum(1 for _ in fixture.open(encoding="utf-8"))
    c = queries.corpus_summary(conn)
    check("코퍼스 논문 수", c["papers"], fixture_lines)
    check("픽스처 경고 카운트", c["fixture_papers"], fixture_lines)
    check_true("사람 대상 연구 존재", c["human_papers"] > 0)
    check_true("RCT 존재", c["rct_papers"] > 0)

    # 집계 수치가 원본 테이블과 일치하는지 (집계 오류 방지)
    row = conn.execute("""SELECT COUNT(*) c FROM paper_ingredient pi
                          JOIN papers p ON p.id = pi.paper_id
                          WHERE pi.ingredient_id = 'biotin'""").fetchone()
    st = conn.execute("SELECT total FROM ingredient_stats WHERE ingredient_id='biotin'").fetchone()
    check("집계 total 이 실제 행 수와 일치", st["total"], row["c"])

    # 성분 상세
    d = queries.ingredient_detail(conn, ref, "biotin")
    check_true("성분 상세 생성", d is not None)
    check("성분 상세 total", d["stats"]["total"], row["c"])
    check_true("요약 문장 존재", len(d["summary"]["lines"]) >= 2)
    check_true("대표 논문 존재", len(d["top_papers"]) > 0)
    # 대표 논문은 근거 위계 내림차순이어야 한다
    ranks = [p["study_type"] for p in d["top_papers"]]
    from ingest.classify import STUDY_TYPES
    vals = [STUDY_TYPES[r][1] for r in ranks]
    check("대표 논문 근거 위계 정렬", vals, sorted(vals, reverse=True))

    # 지표별 방향 합이 사람 대상 연구 수와 맞는지
    for o in d["outcomes"]:
        check(f"방향 합계({o['outcome_id']})",
              o["human_significant"] + o["human_null"] + o["human_unclear"], o["human"])

    # 색인에 없는 성분은 0 으로 나오고 지어내지 않는다
    empty = queries.ingredient_detail(conn, ref, "urolithin_a")
    check("미수집 성분 total", empty["stats"]["total"], 0)
    check_true("미수집 성분 안내문", "효과가 없다" in empty["summary"]["lines"][0])

    # 역방향 검색 (효능 → 성분)
    od = queries.outcome_detail(conn, ref, "lipid", min_human=1)
    check_true("역방향 검색 결과", len(od["ingredients"]) > 0)
    check_true("역방향 정렬(사람 연구 건수 내림차순)",
               all(od["ingredients"][i]["human"] >= od["ingredients"][i + 1]["human"]
                   for i in range(len(od["ingredients"]) - 1)))

    # 통합 검색: 한글 성분명 / 한글 효능어
    r1 = queries.unified_search(conn, ref, "비오틴")
    check("성분명 검색 모드", r1["mode"], "ingredient")
    check("성분명 검색 결과", r1["ingredients"][0]["id"], "biotin")
    r2 = queries.unified_search(conn, ref, "콜레스테롤")
    check("효능어 검색 모드", r2["mode"], "outcome")
    check("효능어 검색 결과", r2["outcomes"][0]["id"], "lipid")
    r3 = queries.unified_search(conn, ref, "탈모")
    check("효능 별칭 검색", r3["outcomes"][0]["id"], "hair")

    # 논문 목록 필터
    p_all = queries.ingredient_papers(conn, "biotin")
    p_human = queries.ingredient_papers(conn, "biotin", subject="human")
    check_true("사람 필터가 결과를 줄인다", p_human["total"] <= p_all["total"])
    check_true("논문 항목에 근거 문장 필드", "evidence" in (p_all["items"][0] if p_all["items"] else {}))

    # 전문검색
    fts = queries.fulltext_papers(conn, "cholesterol")
    check_true("FTS 동작", len(fts) > 0)
    # 사용자 입력에 FTS5 특수문자가 있어도 터지지 않아야 한다
    for bad in ['"', 'a AND', 'x*', '(', 'NEAR/2', "'"]:
        try:
            queries.fulltext_papers(conn, bad)
        except sqlite3.Error as e:
            FAILS.append(f"FTS 특수문자 처리 실패({bad!r}): {e}")

    # 논문 상세에 분류 근거가 붙는지
    pid = conn.execute("SELECT paper_id FROM paper_outcome LIMIT 1").fetchone()["paper_id"]
    detail = queries.paper_detail(conn, ref, pid)
    check_true("논문 상세 지표", len(detail["outcomes"]) > 0)
    check_true("논문 상세에 성분 연결", len(detail["ingredients"]) > 0)

    # 재분류를 돌려도 결과가 그대로인지 (멱등성)
    before = conn.execute("SELECT COUNT(*) c FROM paper_outcome").fetchone()["c"]
    conn.close()
    run("-m", "ingest.build", "classify")
    run("-m", "ingest.build", "aggregate")
    conn = queries.connect(db)
    after = conn.execute("SELECT COUNT(*) c FROM paper_outcome").fetchone()["c"]
    check("재분류 멱등성", after, before)
    conn.close()


if __name__ == "__main__":
    main()
    if FAILS:
        print(f"\n실패 {len(FAILS)}건:")
        for f in FAILS:
            print("  ✗", f)
        sys.exit(1)
    print("파이프라인 통합 테스트 전부 통과")
