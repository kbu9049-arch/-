PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- 문헌 DB 에서 받아온 논문 원본 메타데이터 + 분류 결과.
CREATE TABLE IF NOT EXISTS papers (
  id            INTEGER PRIMARY KEY,
  source        TEXT NOT NULL,   -- Europe PMC source 코드 (MED = PubMed, PMC, PPR 등)
  ext_id        TEXT NOT NULL,   -- 해당 소스에서의 ID
  pmid          TEXT,
  pmcid         TEXT,
  doi           TEXT,
  title         TEXT NOT NULL,
  abstract      TEXT,
  journal       TEXT,
  year          INTEGER,
  authors       TEXT,
  pub_types     TEXT,            -- JSON 배열
  mesh          TEXT,            -- JSON 배열
  study_type    TEXT,
  subject       TEXT,
  evidence_rank INTEGER DEFAULT 0,
  retracted     INTEGER DEFAULT 0,
  cited_by      INTEGER DEFAULT 0,
  is_oa         INTEGER DEFAULT 0,
  url           TEXT,
  fetched_at    TEXT,
  UNIQUE (source, ext_id)
);
CREATE INDEX IF NOT EXISTS idx_papers_year  ON papers (year);
CREATE INDEX IF NOT EXISTS idx_papers_type  ON papers (study_type);
CREATE INDEX IF NOT EXISTS idx_papers_rank  ON papers (evidence_rank DESC);
CREATE INDEX IF NOT EXISTS idx_papers_pmid  ON papers (pmid);

CREATE TABLE IF NOT EXISTS paper_ingredient (
  paper_id      INTEGER NOT NULL REFERENCES papers (id) ON DELETE CASCADE,
  ingredient_id TEXT    NOT NULL,
  matched_term  TEXT,
  PRIMARY KEY (paper_id, ingredient_id)
);
CREATE INDEX IF NOT EXISTS idx_pi_ing ON paper_ingredient (ingredient_id);

CREATE TABLE IF NOT EXISTS paper_outcome (
  paper_id   INTEGER NOT NULL REFERENCES papers (id) ON DELETE CASCADE,
  outcome_id TEXT    NOT NULL,
  score      INTEGER NOT NULL,
  direction  TEXT    NOT NULL,   -- significant | null | unclear
  evidence   TEXT,               -- 판정 근거가 된 초록 문장 (검증용)
  matched    TEXT,               -- 지표로 잡힌 표현 (JSON 배열)
  PRIMARY KEY (paper_id, outcome_id)
);
CREATE INDEX IF NOT EXISTS idx_po_out ON paper_outcome (outcome_id);

-- 재실행 가능한 수집을 위한 진행 상태.
CREATE TABLE IF NOT EXISTS harvest_state (
  query_key     TEXT PRIMARY KEY,
  ingredient_id TEXT,
  tier          TEXT,
  query         TEXT,
  cursor        TEXT,
  hit_count     INTEGER DEFAULT 0,
  fetched       INTEGER DEFAULT 0,
  done          INTEGER DEFAULT 0,
  updated_at    TEXT,
  note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_hs_ing ON harvest_state (ingredient_id);

-- 집계 결과 (aggregate 단계에서 매번 새로 만든다).
CREATE TABLE IF NOT EXISTS ingredient_stats (
  ingredient_id TEXT PRIMARY KEY,
  total         INTEGER DEFAULT 0,
  human         INTEGER DEFAULT 0,
  systematic    INTEGER DEFAULT 0,   -- 메타분석 + 체계적 문헌고찰
  rct           INTEGER DEFAULT 0,
  preclinical   INTEGER DEFAULT 0,
  retracted     INTEGER DEFAULT 0,
  year_min      INTEGER,
  year_max      INTEGER,
  hit_count     INTEGER DEFAULT 0    -- 문헌 DB 가 보고한 전체 검색 결과 수
);

CREATE TABLE IF NOT EXISTS ingredient_outcome_stats (
  ingredient_id TEXT NOT NULL,
  outcome_id    TEXT NOT NULL,
  total         INTEGER DEFAULT 0,
  human         INTEGER DEFAULT 0,
  human_sig     INTEGER DEFAULT 0,
  human_null    INTEGER DEFAULT 0,
  human_unclear INTEGER DEFAULT 0,
  PRIMARY KEY (ingredient_id, outcome_id)
);
CREATE INDEX IF NOT EXISTS idx_ios_out ON ingredient_outcome_stats (outcome_id);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts
  USING fts5 (title, abstract, content='papers', content_rowid='id');
