# 성분 근거 찾기

광고나 제품 라벨에서 본 **성분**을 검색하면 그 성분에 대해 어떤 항목을 측정한 연구가
몇 건 있고 결과가 어떻게 갈렸는지 보여주고, 반대로 **효능**으로 성분을 찾을 수 있는 웹사이트입니다.

모든 논문 메타데이터는 [Europe PMC](https://europepmc.org/RestfulWebService) 와
[PubMed(NCBI E-utilities)](https://www.ncbi.nlm.nih.gov/books/NBK25501/) 의 공개 API 응답을
그대로 저장한 것이고, 화면의 모든 건수는 저장된 논문 레코드를 실제로 센 값입니다.
추정하거나 보정한 수치는 하나도 없습니다.

---

## ⚠️ 먼저 읽어 주세요 — 지금 이 저장소에 논문 데이터는 들어 있지 않습니다

**논문을 수집하는 것은 여러분 몫입니다.** 이유는 두 가지입니다.

1. 이 코드를 작성한 실행 환경은 조직 이그레스 정책 때문에 `www.ebi.ac.uk` 와
   `eutils.ncbi.nlm.nih.gov` 접속이 차단되어 있었습니다(둘 다 `403`). 그래서 여기서는
   실제 수집을 돌릴 수 없었습니다.
2. 그렇다고 **가짜 논문 데이터를 채워 넣지는 않았습니다.** 수집 전에는 화면이
   "아직 수집 전"이라고 정직하게 표시합니다.

대신 **수집 파이프라인이 완성되어 있습니다.** 두 가지 방법 중 하나를 쓰면 됩니다.

**가장 쉬운 방법 — 아무것도 설치하지 않아도 됩니다.** 저장소 Settings → Pages → Source 를
`GitHub Actions` 로 바꾼 뒤, Actions 탭에서 **"논문 수집 후 사이트 배포"** 를 실행하세요.
GitHub 러너가 논문을 수집해 공개 주소가 있는 사이트까지 만들어 줍니다
(→ [온라인 웹사이트로 올리기](#온라인-웹사이트로-올리기)).

**직접 실행하려면**, 네트워크가 열린 곳에서 아래를 실행하면 이 사이트가 실데이터로 채워집니다.

```bash
make install
make probe                 # ① API 연결·질의 문법이 실제로 먹는지 먼저 확인
make ingest TARGET=100000  # ② 수집 → 분류 → 색인
make serve                 # ③ http://localhost:8000
```

`make probe` 를 반드시 먼저 돌리세요. 연결이 되는지, `PUB_TYPE` 같은 필터가 실제로
동작하는지 몇 초 만에 확인해 주고, 안 되면 어떤 옵션으로 바꿔야 하는지 알려줍니다.

수집 소요 시간(참고): 네트워크 15~40분 + 분류 약 1분 + 색인 수 초.
중간에 끊어도 됩니다 — 진행 커서가 저장되어 같은 명령으로 이어서 실행됩니다.

논문 없이 화면만 먼저 보고 싶다면:

```bash
make fixture   # 합성 테스트 코퍼스. 화면 상단에 빨간 경고가 자동으로 뜹니다.
EVIDENCE_DB=data/fixture.db make serve
```

---

## 무엇을 보여주나

### 성분 → 논문 (광고에서 본 성분 확인하기)

성분을 검색하면:

- 색인된 논문 수, 그중 **사람 대상 연구** 수, 메타분석·체계적 문헌고찰 수, RCT 수, 동물·시험관 연구 수
- **어떤 항목을 측정했나** — 결과지표별 연구 건수 막대. 각 막대는
  `유의한 결과 보고 / 유의차 없음 / 판정 불가` 세 구간으로 나뉩니다.
- **대표 논문** — 근거 위계(메타분석 → 체계적 문헌고찰 → RCT → 임상시험 → 관찰연구)와
  피인용 수 순. 제목은 PubMed 원문으로 바로 연결됩니다.
- 연도별 논문 수 분포
- 항목·연구유형·대상·결과별 필터가 붙은 논문 전체 목록

### 효능 → 성분 (역방향 검색)

"혈당", "수면", "탈모", "관절" 처럼 원하는 효능을 고르면 그 항목을 **실제로 측정한**
사람 대상 연구가 있는 성분들이 나옵니다. 각 성분마다 결과 방향 분포가 함께 보이고,
그 항목의 대표 논문도 볼 수 있습니다.

정렬은 **사람 대상 연구 건수 순**이며 효과의 크기나 순위가 아닙니다. 화면에도 그렇게 적혀 있습니다.

### 색인에 없는 검색어

사전에 없는 성분을 검색하면 "자료 없음"으로 끝내지 않고 문헌 DB 에 **실시간으로** 질의해
상위 논문을 그 자리에서 분류해 보여줍니다. 색인 통계와는 항상 구분해서 표시합니다.

---

## 이 도구가 하지 않는 것

이 부분이 설계의 핵심입니다.

| 하지 않음 | 대신 하는 것 |
|---|---|
| "이 성분은 ○○에 효과가 있다" 판정 | "○○를 측정한 사람 대상 연구가 N건이고 그중 유의한 결과 보고가 M건" |
| 성분에 점수·등급·순위 매기기 | 연구 건수만 제시하고, 순서가 우열이 아님을 명시 |
| "개선/악화" 방향 단정 | `유의한 결과 보고 / 유의차 없음 / 판정 불가` 3분류만 |
| 판정 근거 감추기 | 모든 판정에 **근거가 된 초록 문장**을 함께 표시 |
| 철회 논문 섞기 | 철회 논문은 표시하고 집계에서 제외 |
| 데이터 없을 때 빈칸 메우기 | "연구 없음 ≠ 효과 없음" 이라고 명시 |

“개선/악화”를 단정하지 않는 이유: 규칙 기반 문장 매칭으로는 `significantly reduced` 가
LDL 콜레스테롤에서는 개선이고 HDL 에서는 악화라는 것을 구분할 수 없습니다.
단정할 수 없는 것은 단정하지 않습니다.

---

## 데이터가 어디서 오나

| 구성요소 | 출처 | 성격 |
|---|---|---|
| 논문 메타데이터 (제목·초록·MeSH·publication type·피인용) | Europe PMC / PubMed API 응답 | **원본 그대로 저장** |
| 논문 수, 연구유형 분포, 결과 방향 분포 | 저장된 레코드를 SQL 로 집계 | **실제 계수** |
| 성분 234종의 한글명·분류 | 국내 통용 건강기능식품 원료명 기준 편집 큐레이션 | 편집 자료 |
| 성분 영문 검색어 (synonyms) | 위와 동일 | 편집 자료 — **문헌 검색은 이것으로만 수행** |
| 결과지표 30종 | MeSH 표준 용어 + 분야별 표준 측정도구(PSQI, WOMAC, IPSS, HOMA-IR 등) | 편집 자료 |
| 연구유형·대상·지표·결과방향 분류 | 초록 문구에 대한 공개된 규칙 | **자동 분류 + 근거 문장 첨부** |

한글명은 사람이 정한 것이지만, 문헌 검색과 논문–성분 연결은 **영문 검색어로만** 이루어집니다.
따라서 화면의 논문 수치 자체는 한글명 선택과 무관하게 문헌 DB 응답에서만 나옵니다.

### "10만 개 데이터를 학습시킨다"에 대하여

학습된 모델을 쓰지 않았습니다. 대신 **재현 가능한 색인 + 공개된 규칙**으로 만들었습니다.
같은 요구를 더 잘 만족시키기 때문입니다.

- 모든 숫자를 실제 PMID 까지 역추적할 수 있습니다.
- 분류가 왜 그렇게 됐는지 근거 문장이 함께 나옵니다.
- `python -m ingest.build classify` 로 규칙을 고쳐 언제든 다시 돌릴 수 있습니다.
- 모델이 없으니 **없는 논문을 지어낼 수 없습니다.** 이게 의학 정보에서 제일 중요합니다.

---

## 구조

```
data/
  ingredients.json     성분 사전 234종 (scripts/gen_ingredients.py 로 생성)
  outcomes.json        결과지표 30종 · 매칭 표현 632개
  evidence.db          수집된 코퍼스 (git 에 넣지 않음, make ingest 로 생성)
ingest/                수집 파이프라인 — 표준 라이브러리만 사용
  sources/http.py        속도 제한 + 지수 백오프 재시도 HTTP 클라이언트
  sources/europepmc.py   cursorMark 페이징, resultType=core
  sources/pubmed.py      E-utilities esearch/efetch (대체 경로)
  classify.py            규칙 기반 분류기 (성분·연구유형·대상·지표·결과방향)
  schema.sql             SQLite 스키마 + FTS5 전문검색
  build.py               CLI (probe/harvest/classify/aggregate/stats/export)
server/
  queries.py             조회 로직 (API 와 정적 스냅샷이 공유)
  live.py                색인 밖 검색어의 실시간 조회
  app.py                 FastAPI
web/                   정적 프런트엔드 (빌드 도구·외부 CDN 없음)
tests/                 분류기 단위 테스트 + 파이프라인 통합 테스트
```

### 수집 전략

성분당 수집 상한이 있을 때 같은 건수로 더 쓸모 있는 코퍼스가 되도록,
근거 수준이 높은 논문부터 채웁니다.

| 순서 | 질의 | 배분 |
|---|---|---|
| 1 | `PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Systematic Review"` | 20% |
| 2 | `PUB_TYPE:"Randomized Controlled Trial" OR "Clinical Trial"` | 50% |
| 3 | 필터 없음 (나머지 전부) | 30% |

`PUB_TYPE` 필터가 동작하지 않는 환경이라면 `--filter-profile basic` 으로 끄면 됩니다
(`make probe` 가 알려줍니다).

질의는 따옴표 구 검색 + `SRC:MED` 만 씁니다. 필드 지정 문법에 의존하지 않아 확실히 동작하고,
논문–성분 연결의 최종 판정은 수집 후 분류기가 본문 낱말 단위로 다시 합니다.

---

## 명령

```bash
make probe                          # API 연결·질의 문법 점검
make ingest TARGET=100000           # 전체 수집 (재실행 가능)
make stats                          # 현재 색인 상태
make test                           # 테스트
make serve PORT=8000                # 웹서버
make site                           # 정적 사이트 빌드 → _site/

python -m ingest.build harvest --ingredients lutein,curcumin --limit-per-ingredient 200
python -m ingest.build harvest --source pubmed        # PubMed 경로로 수집
python -m ingest.build classify                       # 규칙만 고쳐 재분류
python -m ingest.build load-jsonl dump.jsonl          # 내려받아 둔 덤프 적재
```

### 환경변수

`.env.example` 참고. 주요 항목:

- `CONTACT_EMAIL` — API 예절상 대량 수집 시 채우는 것이 좋습니다.
- `NCBI_API_KEY` — 있으면 PubMed 경로가 초당 3회 → 10회
  ([NCBI 문서](https://www.ncbi.nlm.nih.gov/books/NBK25497/))
- `RATE_LIMIT_PER_SEC` — 기본 3
- `EVIDENCE_DB` — 색인 DB 경로
- `LIVE_LOOKUP=0` — 실시간 조회 끄기

---

## API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/meta` | 코퍼스 요약, 분류 코드표, 주의사항 문구 |
| `GET /api/search?q=` | 통합 검색 — 성분명이든 효능 표현이든 받음 |
| `GET /api/ingredients?q=&category=` | 성분 목록·검색 |
| `GET /api/ingredients/{id}` | 성분 상세 (요약·지표 분포·대표 논문) |
| `GET /api/ingredients/{id}/papers?outcome=&subject=&study_type=&direction=&page=` | 논문 목록 |
| `GET /api/outcomes` | 효능·결과지표 목록 |
| `GET /api/outcomes/{id}?min_human=&sort=` | **역방향 검색** — 그 항목을 측정한 성분들 |
| `GET /api/papers/{id}` | 논문 상세 (초록·MeSH·분류 근거) |
| `GET /api/live?term=` | 색인 밖 검색어의 실시간 조회 |
| `GET /api/health` | 상태 확인 |

대화형 문서: 서버 실행 후 `/docs`

---

## 온라인 웹사이트로 올리기

두 가지 방법이 있습니다. **A안이 훨씬 쉽고, 논문 수집까지 GitHub이 대신 해 줍니다.**

### A안 — GitHub Pages (무료 · 서버 불필요 · 수집도 자동)

GitHub Actions 러너는 Europe PMC 와 PubMed 에 접속할 수 있습니다. 그래서 **여러분 컴퓨터에서는
아무것도 실행하지 않아도** 됩니다.

1. 저장소 **Settings → Pages → Source** 를 `GitHub Actions` 로 바꿉니다.
2. **Actions 탭 → "논문 수집 후 사이트 배포" → Run workflow** 를 누릅니다.
3. 30~60분 뒤 `https://<사용자명>.github.io/<저장소명>/` 에 사이트가 뜹니다.

워크플로가 하는 일: 논문 수집 → 분류 → 색인 → 정적 파일 생성 → Pages 배포.

**첫 실행 이후로는 버튼을 누를 일이 없습니다.** 기본 브랜치에 푸시하면 자동으로
다시 배포됩니다. 논문은 캐시에서 그대로 가져오므로 수집 단계를 사실상 건너뛰고
30초쯤이면 끝납니다. 매월 1일에는 새 논문을 이어받아 갱신합니다.

`Run workflow` 를 직접 누르는 건 **논문을 더 깊이 모으고 싶을 때**뿐입니다
(→ [논문을 더 모으려면](#논문을-더-모으려면)).

빈 사이트가 배포되는 사고를 막기 위해 **검증 단계**를 둡니다 — 논문이 1,000건 미만이거나,
연결된 성분이 50종 미만이거나, 합성 테스트 레코드가 섞여 있으면 배포를 중단합니다.

로컬에서 정적 사이트를 직접 만들려면:

```bash
make site                              # → _site/
python3 -m http.server -d _site 8080   # 확인
```

`_site/` 폴더를 Netlify·Vercel·S3 등 아무 정적 호스팅에나 올려도 그대로 동작합니다.

`_site/` 는 이렇게 생겼습니다.

```
_site/
  index.html  style.css  app.js
  data/
    index.json        코퍼스 요약·성분 목록·지표 목록·검색 색인 (첫 화면에서 이것만 받음)
    i/<성분>.json      성분 상세 + 그 성분의 논문 전부   (성분을 열 때만 받음)
    o/<지표>.json      지표 상세                        (지표를 열 때만 받음)
```

한 파일에 다 담으면 성분당 몇십 건밖에 못 실어서 "뼈 건강 (233)" 을 골라도 몇 건만
나오게 됩니다. 나눠 두면 첫 화면은 가볍고 논문은 전부 실을 수 있습니다.

**정적 배포의 제약** — 색인에 없는 검색어를 문헌 DB 에 **실시간 조회하는 기능**과
**초록 전문검색**은 서버 배포에서만 됩니다. 그 외 성분 검색, 효능 역방향 검색,
지표·연구방식·결과 필터는 **전부 동일하게 동작합니다.**
`tests/test_parity.py` 가 정적 모드와 서버 모드가 같은 수치를 내는지 매번 검사합니다.

### B안 — 서버 배포 (실시간 조회 + 전체 논문)

`render.yaml`, `fly.toml`, `Procfile`, `Dockerfile` 이 들어 있습니다.

```bash
# Fly.io
fly launch --no-deploy --copy-config
fly volumes create corpus --size 2
fly deploy
fly ssh console -C "python -m ingest.build all --target 100000"

# Render — 대시보드에서 Blueprint 로 render.yaml 을 가리킨 뒤, Shell 에서
python -m ingest.build all --target 100000

# Docker
docker build -t ingredient-evidence .
docker run -v $(pwd)/data:/app/data ingredient-evidence python -m ingest.build all
docker run -p 8000:8000 -v $(pwd)/data:/app/data ingredient-evidence
```

코퍼스 DB 는 이미지에 넣지 않고 디스크 볼륨에 둡니다. 재배포해도 수집한 논문이 유지됩니다.

### 어느 쪽을 고를까

| | GitHub Pages (A) | 서버 배포 (B) |
|---|---|---|
| 비용 | 무료 | 유료 (디스크 필요) |
| 수집 실행 | GitHub 가 대신 | 직접 한 번 실행 |
| 성분·효능 검색 | ✅ | ✅ |
| 성분별 논문 | 전체 | 전체 |
| 실시간 문헌 조회 | ❌ | ✅ |
| 초록 전문검색 | ❌ | ✅ |
| 첫 화면 전송량 | 색인만 (수백 KB) | API 응답 |

## 논문을 더 모으려면

수집은 **이어받기**입니다. 성분마다 어디까지 받았는지 커서를 저장해 두므로,
상한을 올려 다시 돌리면 처음부터 다시 받지 않고 그 지점부터 더 깊이 파고듭니다.

```bash
python -m ingest.build harvest --target 300000 --limit-per-ingredient 1500
python -m ingest.build aggregate
```

GitHub Actions 로 돌린다면 **Run workflow** 화면에서 `target` 과
`limit_per_ingredient` 값만 올려 실행하면 됩니다. 이전 코퍼스는 캐시에서 복원되므로
늘어난 몫만 새로 받습니다.

성분 하나에 논문이 많이 달릴수록 정적 배포의 성분 파일이 커집니다. `export` 는
성분당 2,000건에서 자르고(`--paper-cap`), 잘린 성분이 있으면 알려 줍니다.

## 한계

- **출판 편향** — 효과가 없다는 결과는 덜 출판되는 경향이 있어 유의한 결과의 비율이
  실제보다 높게 보일 수 있습니다. 화면에도 명시되어 있습니다.
- **초록만 읽습니다** — 전문(full text)을 읽지 않으므로 초록에 결론이 명확히 안 적힌
  논문은 "판정 불가"로 남습니다.
- **효과 크기를 다루지 않습니다** — 통계적 유의성만 봅니다. 유의하지만 임상적으로
  무의미한 크기일 수 있습니다.
- **용량·제형·대상 집단을 구분하지 않습니다** — 같은 성분이라도 용량과 대상에 따라
  결과가 달라집니다.
- **연구 품질을 평가하지 않습니다** — 연구 유형만 구분하고 편향 위험(risk of bias)은
  보지 않습니다.
- **영문 문헌만 다룹니다** — 국내 학술지 등재 논문은 포함되지 않습니다.
- 규칙 기반 분류이므로 오분류가 있습니다. 그래서 **모든 판정에 근거 문장을 붙여**
  사용자가 직접 확인할 수 있게 했습니다.
- **논문 제목과 인용 문장은 번역하지 않습니다.** 옮기는 과정에서 뜻이 달라지면
  근거로서 값어치가 없어지기 때문입니다. 대신 연구 방식·대상·결과는 쉬운 한국어로
  표시하고, 용어를 누르면 설명이 나옵니다.

**이 사이트는 의학적 조언이 아닙니다. 질병의 진단·치료·예방을 목적으로 사용할 수 없습니다.
건강 관련 판단은 의사·약사와 상의하세요.**
