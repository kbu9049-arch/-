"""정적 스냅샷 모드 == 서버 API 모드 동등성 테스트.

같은 화면 코드가 두 가지 방식으로 배포되므로(FastAPI 서버 / 정적 호스팅),
같은 질의에 같은 수치를 내는지 확인한다. 두 경로가 갈라지면 한쪽 배포에서만
틀린 숫자가 보이게 되는데, 그건 조용히 지나가기 쉬운 종류의 버그다.

playwright 가 없으면 건너뛴다:  pip install playwright
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PATHS = [
    "/api/meta",
    "/api/outcomes",
    "/api/outcomes/lipid?min_human=1&limit=80",
    "/api/outcomes/glucose?min_human=1&limit=80",
    "/api/ingredients?limit=60&offset=0",
    "/api/ingredients?q=%EB%B9%84%EC%98%A4%ED%8B%B4&limit=60",
    "/api/ingredients?category=mineral&limit=60",
    "/api/ingredients/biotin",
    "/api/ingredients/biotin/papers?page=1",
    "/api/ingredients/biotin/papers?outcome=glucose&page=1",
    "/api/ingredients/biotin/papers?subject=human&page=1",
    "/api/ingredients/biotin/papers?study_type=rct&page=1",
    "/api/ingredients/biotin/papers?direction=null&page=1",
    "/api/ingredients/copper",
    "/api/search?q=%EB%B9%84%EC%98%A4%ED%8B%B4",
    "/api/search?q=%ED%98%88%EB%8B%B9",
    "/api/search?q=%ED%83%88%EB%AA%A8",
]


def digest(path: str, d: dict):
    """비교할 핵심 수치만 뽑는다. 표현이 아니라 숫자가 같아야 한다."""
    if path.startswith("/api/meta"):
        c = d["corpus"]
        return [c["papers"], c["human_papers"], c["rct_papers"], c["ingredients_with_papers"]]
    if path == "/api/outcomes":
        return [[o["id"], o["ingredients"], o["human"]] for o in d["items"]]
    if path.startswith("/api/outcomes/"):
        return [d["label_ko"],
                [[i["id"], i["human"], i["human_significant"], i["human_null"]]
                 for i in d["ingredients"]],
                [p["title"] for p in d["top_papers"]]]
    if path.startswith("/api/ingredients?"):
        return [d["total"],
                [[i["id"], i["stats"]["total"], i["stats"]["human"]] for i in d["items"]]]
    if "/papers?" in path:
        return [d["total"], [p["title"] for p in d["items"]]]
    if path.startswith("/api/ingredients/"):
        return [d["stats"],
                [[o["outcome_id"], o["human"], o["human_significant"]] for o in d["outcomes"]],
                [p["title"] for p in d["top_papers"]], d["summary"]["lines"]]
    if path.startswith("/api/search"):
        return [d["mode"], [i["id"] for i in d["ingredients"]], [o["id"] for o in d["outcomes"]]]
    return d


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 30) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except urllib.error.HTTPError:
            return True                      # 503 도 '떠 있음'
        except Exception:
            time.sleep(0.3)
    return False


def chromium_path():
    for p in ("/opt/pw-browsers/chromium",):
        if pathlib.Path(p).exists():
            return p
    return None


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 없어 동등성 테스트를 건너뜁니다 (pip install playwright)")
        return 0

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="parity-"))
    db = tmp / "test.db"
    fixture = tmp / "fixture.jsonl"
    env = {**os.environ, "EVIDENCE_DB": str(db), "PYTHONPATH": str(ROOT), "LIVE_LOOKUP": "0"}

    def run(*args):
        r = subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        if r.returncode:
            print(f"준비 실패: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
            raise SystemExit(1)

    run("tests/fixtures/make_fixture.py", str(fixture))
    run("-m", "ingest.build", "load-jsonl", str(fixture))
    run("-m", "ingest.build", "aggregate")
    # 픽스처 코퍼스라 --allow-empty 로 내보내기 가드를 통과시킨다(테스트 목적).
    run("-m", "ingest.build", "export", str(tmp / "snapshot.json"),
        "--top-papers", "40", "--allow-empty")

    # 정적 배포를 하위 경로에 올린 상태를 재현한다 (GitHub Pages 의 /저장소명/)
    site = tmp / "site" / "repo-name"
    site.mkdir(parents=True)
    for f in ("index.html", "style.css", "app.js"):
        shutil.copy(ROOT / "web" / f, site / f)
    shutil.copy(tmp / "snapshot.json", site / "snapshot.json")

    api_port, static_port = free_port(), free_port()
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app",
                          "--port", str(api_port), "--log-level", "warning"],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, "-m", "http.server", str(static_port)],
                         cwd=tmp / "site", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    fails = []
    try:
        if not wait_http(f"http://127.0.0.1:{api_port}/api/health"):
            print("API 서버가 뜨지 않았습니다.")
            return 1
        if not wait_http(f"http://127.0.0.1:{static_port}/repo-name/"):
            print("정적 서버가 뜨지 않았습니다.")
            return 1

        with sync_playwright() as pw:
            exe = chromium_path()
            browser = pw.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe \
                else pw.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{static_port}/repo-name/", wait_until="networkidle")
            page.wait_for_selector("#ing-list .card", timeout=15000)
            if errors:
                fails.append(f"정적 모드 자바스크립트 오류: {errors}")

            for path in PATHS:
                static_res = page.evaluate("p => api(p)", path)
                with urllib.request.urlopen(f"http://127.0.0.1:{api_port}{path}", timeout=20) as r:
                    server_res = json.loads(r.read())
                a, b = digest(path, static_res), digest(path, server_res)
                if a != b:
                    fails.append(
                        f"{path}\n      정적: {json.dumps(a, ensure_ascii=False)[:200]}"
                        f"\n      서버: {json.dumps(b, ensure_ascii=False)[:200]}")
            browser.close()
    finally:
        for p in procs:
            p.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print(f"\n동등성 불일치 {len(fails)}건:")
        for f in fails:
            print("  ✗", f)
        return 1
    print(f"정적/서버 동등성 테스트 통과 ({len(PATHS)}개 경로)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
