PY ?= python3
PORT ?= 8000
TARGET ?= 100000

.PHONY: help install probe harvest ingest serve dev stats test clean reset fixture snapshot site

help:
	@echo "make install    의존성 설치 (웹서버용, 수집은 표준 라이브러리만 사용)"
	@echo "make probe      문헌 API 연결·질의 문법 점검 (수집 전에 먼저 실행)"
	@echo "make ingest     논문 수집 → 분류 → 색인  (TARGET=$(TARGET))"
	@echo "make serve      웹서버 실행  (PORT=$(PORT))"
	@echo "make dev        자동 리로드 개발 서버"
	@echo "make stats      현재 색인 상태 출력"
	@echo "make test       테스트 실행"
	@echo "make fixture    테스트용 합성 코퍼스로 화면 확인 (실제 데이터 아님)"
	@echo "make site       정적 사이트 빌드 → _site/ (그대로 올리면 됨)"
	@echo "make reset      색인 DB 삭제"

install:
	$(PY) -m pip install -r requirements.txt

probe:
	$(PY) -m ingest.build probe

harvest:
	$(PY) -m ingest.build harvest --target $(TARGET)

ingest:
	$(PY) -m ingest.build all --target $(TARGET)

serve:
	$(PY) -m uvicorn server.app:app --host 0.0.0.0 --port $(PORT)

dev:
	$(PY) -m uvicorn server.app:app --reload --port $(PORT)

stats:
	$(PY) -m ingest.build stats

test:
	$(PY) tests/test_classify.py
	$(PY) tests/test_pipeline.py
	$(PY) tests/test_parity.py

snapshot: site

# 서버 없이 어디든 올릴 수 있는 정적 사이트. GitHub Pages, Netlify, Vercel,
# S3, 심지어 USB 에 넣어도 열린다.
# 색인 하나와 성분·지표별 상세 파일로 나뉘어 있어, 첫 화면에서는 색인만 받는다.
site:
	rm -rf _site && mkdir -p _site
	cp web/index.html web/style.css web/app.js _site/
	$(PY) -m ingest.build export _site/data
	touch _site/.nojekyll
	@echo "\n_site/ 준비 완료 ($$(du -sh _site | cut -f1))"
	@echo "확인:  python3 -m http.server -d _site 8080"

# 실제 논문 없이 화면만 확인할 때. 만들어지는 레코드는 전부 합성이며
# 화면 상단에 빨간 경고가 뜬다.
fixture:
	$(PY) tests/fixtures/make_fixture.py /tmp/fixture.jsonl
	EVIDENCE_DB=data/fixture.db $(PY) -m ingest.build load-jsonl /tmp/fixture.jsonl
	EVIDENCE_DB=data/fixture.db $(PY) -m ingest.build aggregate
	@echo "\n실행: EVIDENCE_DB=data/fixture.db make serve"

reset:
	rm -f data/evidence.db data/evidence.db-wal data/evidence.db-shm

clean: reset
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
