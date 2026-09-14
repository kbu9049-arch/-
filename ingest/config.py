"""수집 파이프라인 설정."""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = pathlib.Path(os.environ.get("EVIDENCE_DB", DATA / "evidence.db"))
INGREDIENTS_JSON = DATA / "ingredients.json"
OUTCOMES_JSON = DATA / "outcomes.json"
PALETTE_JSON = DATA / "palette.json"

# ── 문헌 DB 엔드포인트 ───────────────────────────────────────────────────────
EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# API 예절: 요청자 식별용. 비워 두면 도구 이름만 보낸다.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
TOOL_NAME = "ingredient-evidence-search"
USER_AGENT = (f"{TOOL_NAME}/1.0 (+https://github.com/) "
              f"{'mailto:' + CONTACT_EMAIL if CONTACT_EMAIL else 'no-contact-set'}")

# NCBI E-utilities 는 API 키 없이 초당 3회, 키가 있으면 초당 10회까지 허용한다.
# 근거: https://www.ncbi.nlm.nih.gov/books/NBK25497/
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()

# Europe PMC 는 pageSize 최대 1000, cursorMark 로 전체 결과를 넘길 수 있다.
# 근거: https://europepmc.org/RestfulWebService
EPMC_PAGE_SIZE = int(os.environ.get("EPMC_PAGE_SIZE", "1000"))
EPMC_MAX_PAGE_SIZE = 1000

# 초당 요청 수 (기본값은 보수적으로 잡았다)
RATE_LIMIT_PER_SEC = float(os.environ.get("RATE_LIMIT_PER_SEC", "3"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "60"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

# ── 수집 규모 ────────────────────────────────────────────────────────────────
DEFAULT_TARGET_PAPERS = 100_000
DEFAULT_LIMIT_PER_INGREDIENT = 500

# ── 질의 필터 프로파일 ───────────────────────────────────────────────────────
# basic  : 따옴표 구 검색 + SRC:MED 만 사용한다. Europe PMC 의 가장 기본적인 문법만
#          쓰므로 확실히 동작한다. 나머지 선별은 수집 후 분류기가 담당한다.
# tiered : 위에 더해 PUB_TYPE 필터로 근거 수준이 높은 논문부터 먼저 채운다.
#          수집 상한이 있을 때 같은 건수로 훨씬 쓸모 있는 코퍼스가 된다.
#          PUB_TYPE 은 Europe PMC 검색 문법 문서에 명시된 필드다.
FILTER_PROFILES = ("tiered", "basic")
DEFAULT_FILTER_PROFILE = os.environ.get("FILTER_PROFILE", "tiered")

# tiered 프로파일의 수집 순서. (이름, PUB_TYPE 절, 배분 비율)
QUERY_TIERS = [
    ("systematic",
     '(PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Systematic Review")', 0.20),
    ("trial",
     '(PUB_TYPE:"Randomized Controlled Trial" OR PUB_TYPE:"Clinical Trial" '
     'OR PUB_TYPE:"Controlled Clinical Trial")', 0.50),
    ("all", "", 0.30),
]
