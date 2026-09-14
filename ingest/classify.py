"""논문 메타데이터 → 성분·연구유형·결과지표·결과방향 규칙 기반 분류기.

설계 원칙
---------
1. 모든 판정에는 판정 근거가 되는 원문 조각(evidence)을 함께 남긴다. 화면에서
   "왜 이렇게 분류됐는지"를 초록 원문과 대조해 확인할 수 있어야 한다.
2. 결과 방향은 '효과 있음/없음'이 아니라 '통계적으로 유의한 결과가 보고됨 /
   유의차 없음 / 판정 불가' 세 가지로만 판정한다. 규칙 기반 문장 매칭으로
   '개선'인지 '악화'인지까지 단정하는 것은 근거가 부족하기 때문이다.
3. 사람 대상 연구와 동물·시험관 연구를 항상 분리한다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ── 연구 유형 ────────────────────────────────────────────────────────────────
# (id, 화면에 나갈 말, 근거가 센 정도) — 뒤 숫자는 '대표 논문' 정렬에만 쓴다.
# 화면에 나가는 말은 연구 용어를 모르는 사람이 그대로 읽을 수 있어야 한다.
# 정식 용어를 쓰고 설명을 따로 띄우는 대신, 말 자체를 쉬운 쪽으로 고른다.
STUDY_TYPES = {
    "meta_analysis":     ("여러 연구 종합", 6),
    "systematic_review": ("논문 모아 정리", 5),
    "rct":               ("무작위 배정 시험", 4),
    "clinical_trial":    ("사람 대상 시험", 3),
    "observational":     ("관찰 연구", 2),
    "review":            ("해설 글", 1),
    "preclinical":       ("동물·세포 실험", 0),
    "other":             ("기타", 0),
}

SUBJECTS = {
    "human": "사람",
    "animal": "동물",
    "invitro": "세포·시험관",
    "unknown": "대상 모름",
}

DIRECTIONS = {
    "significant": "차이 있었음",
    "null": "차이 없었음",
    "unclear": "알 수 없음",
}


# ── 결과 방향 판정 문구 ──────────────────────────────────────────────────────
# '유의차 없음'을 먼저 본다. 이 표현들이 더 구체적이라 오탐이 적다.
NULL_PATTERNS = [
    r"no significant difference",
    r"no statistically significant",
    r"not statistically significant",
    r"no significant (?:effect|change|improvement|reduction|increase|difference|association|impact|benefit)",
    r"did not (?:significantly|differ|reach|show|improve|reduce|change|affect|alter|produce)",
    r"was not significantly",
    r"were not significantly",
    r"failed to (?:show|demonstrate|reach|improve|reduce|produce|significantly)",
    r"no (?:apparent|detectable|measurable|clear|meaningful) (?:effect|benefit|difference)",
    r"non-?significant",
    r"comparable (?:between|to|with) (?:the )?(?:placebo|control)",
    r"similar (?:between|in) (?:both|the two) groups",
    r"no benefit",
    r"no evidence (?:of|for|to support)",
    r"without (?:any )?(?:a )?significant",
    r"neither .{0,60}? nor",
    r"\bp\s*[=＝]\s*0?\.[1-9]",          # p = .12 등 유의하지 않은 p값
    r"\bp\s*>\s*0?\.05",
]

SIGNIFICANT_PATTERNS = [
    r"significantly (?:improved|increased|decreased|reduced|lowered|higher|lower|greater|enhanced|attenuated|ameliorated|elevated|shortened|prolonged|better)",
    r"significant (?:improvement|reduction|increase|decrease|decline|difference|effect|change|benefit|association|correlation)",
    r"(?:improved|increased|decreased|reduced|lowered|enhanced|attenuated) significantly",
    r"statistically significant",
    r"\bp\s*[<＜]\s*0?\.0*[015]",         # p < .05, p < .01, p < .001
    r"was (?:effective|superior) (?:in|for|to|compared)",
    r"were (?:effective|superior) (?:in|for|to|compared)",
    r"beneficial effect",
    r"significant(?:ly)? (?:more|less) than (?:the )?(?:placebo|control)",
]

# 결론 구간을 잡아내는 구조화 초록 라벨
CONCLUSION_RE = re.compile(
    r"\b(?:conclusions?|conclusion and relevance|interpretation|in conclusion|"
    r"conclusions?/?(?:significance|implications)?)\b\s*[:.\-–]\s*",
    re.I,
)
RESULTS_RE = re.compile(r"\b(?:results?|findings?|outcomes?)\b\s*[:.\-–]\s*", re.I)

# ── 연구 유형 판정 ───────────────────────────────────────────────────────────
PUBTYPE_MAP = {
    "meta-analysis": "meta_analysis",
    "systematic review": "systematic_review",
    "randomized controlled trial": "rct",
    "controlled clinical trial": "clinical_trial",
    "clinical trial": "clinical_trial",
    "clinical trial, phase i": "clinical_trial",
    "clinical trial, phase ii": "clinical_trial",
    "clinical trial, phase iii": "clinical_trial",
    "clinical trial, phase iv": "clinical_trial",
    "pragmatic clinical trial": "clinical_trial",
    "equivalence trial": "clinical_trial",
    "observational study": "observational",
    "comparative study": "observational",
    "review": "review",
    "journal article": None,
}

TEXT_STUDY_RULES = [
    ("meta_analysis",     r"\bmeta-?analys[ie]s\b|\bnetwork meta-?analysis\b"),
    ("systematic_review", r"\bsystematic (?:review|literature review)\b|\bscoping review\b|\bumbrella review\b"),
    ("rct",               r"\brandomi[sz]ed[, ]|\brandomi[sz]ed\b.{0,40}\btrial\b|double-?blind|placebo-?controlled|\brct\b|cross-?over trial"),
    ("clinical_trial",    r"\bclinical trial\b|\bopen-?label\b|\bsingle-?arm\b|\bpilot (?:study|trial)\b|\bintervention study\b"),
    ("observational",     r"\bcohort stud|\bcase-?control\b|\bcross-?sectional\b|\bprospective stud|\bretrospective stud|\bnhanes\b"),
    ("review",            r"\bnarrative review\b|\ba review\b|\breview of the literature\b"),
]

RETRACTION_RE = re.compile(
    r"^retracted[:\s]|^\[retracted|retraction of|retracted article", re.I)
RETRACT_PUBTYPES = {"retracted publication", "retraction of publication"}

# ── 연구 대상(사람/동물/시험관) 판정 ─────────────────────────────────────────
MESH_HUMAN = {"humans", "adult", "middle aged", "aged", "young adult", "child",
              "adolescent", "female", "male", "infant"}
MESH_ANIMAL = {"animals", "mice", "rats", "rats, wistar", "rats, sprague-dawley",
               "mice, inbred c57bl", "swine", "rabbits", "dogs", "zebrafish",
               "disease models, animal", "caenorhabditis elegans", "drosophila melanogaster"}

ANIMAL_TEXT_RE = re.compile(
    r"\b(?:mice|mouse|rats?|murine|rodents?|zebrafish|c57bl|sprague-?dawley|wistar|"
    r"rabbits?|piglets?|broilers?|c\.\s?elegans|caenorhabditis|drosophila|"
    r"animal model|in vivo model)\b", re.I)
INVITRO_TEXT_RE = re.compile(
    r"\bin vitro\b|\bcell line\b|\bcultured cells?\b|\bhepg2\b|\bcaco-?2\b|\braw ?264\.7\b|"
    r"\b3t3-?l1\b|\bhacat\b|\bmolecular docking\b|\bcell-?free\b", re.I)
HUMAN_TEXT_RE = re.compile(
    r"\b(?:patients?|participants?|volunteers?|subjects were randomi|healthy (?:men|women|adults|subjects)|"
    r"human subjects?|men and women|outpatients?|in humans)\b", re.I)


def _norm(text: str) -> str:
    """비교용 정규화: NFKC + 소문자 + 유니코드 대시/따옴표를 ASCII 로."""
    text = unicodedata.normalize("NFKC", text or "")
    text = (text.replace("‐", "-").replace("‑", "-").replace("‒", "-")
                .replace("–", "-").replace("—", "-").replace("−", "-")
                .replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"'))
    return text.lower()


TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """영숫자 낱말 목록. 공백·하이픈·문장부호는 전부 구분자로 본다."""
    return TOKEN_RE.findall(_norm(text))


class PhraseIndex:
    """다중 구(phrase) 동시 매칭용 색인.

    검색어가 1,000개를 넘어가면 거대한 정규식 교대(alternation)는 초록 한 건마다
    수십 밀리초를 잡아먹는다. 대신 본문을 낱말로 한 번만 쪼갠 뒤, 각 낱말을
    '그 낱말로 시작하는 구' 목록에서 조회한다. 본문 길이에 선형이라 훨씬 빠르고,
    낱말 단위로 비교하므로 'vitamin d' 가 'vitamin d3' 를 가로채지 않는다.
    """

    __slots__ = ("by_first", "_seen")

    def __init__(self):
        self.by_first: dict[str, list[tuple[tuple[str, ...], str]]] = {}
        self._seen: set[tuple[tuple[str, ...], str]] = set()

    def add(self, phrase: str, key: str, *, unique_phrase: bool = False) -> None:
        toks = tuple(tokenize(phrase))
        if not toks:
            return
        if unique_phrase and any(toks == t for t, _ in self.by_first.get(toks[0], [])):
            return          # 같은 표현이 이미 다른 키에 잡혀 있으면 먼저 등록된 쪽을 둔다
        if (toks, key) in self._seen:
            return
        self._seen.add((toks, key))
        self.by_first.setdefault(toks[0], []).append((toks, key))

    def finalize(self) -> "PhraseIndex":
        # 같은 위치에서는 가장 긴 구를 먼저 시도한다.
        for lst in self.by_first.values():
            lst.sort(key=lambda x: -len(x[0]))
        return self

    def find(self, tokens: list[str]) -> list[tuple[str, str]]:
        """(키, 매칭된 표현) 목록. 한 위치에서 가장 긴 구 하나만 잡는다."""
        out: list[tuple[str, str]] = []
        first = self.by_first
        n = len(tokens)
        for i, tok in enumerate(tokens):
            cands = first.get(tok)
            if not cands:
                continue
            for toks, key in cands:
                ln = len(toks)
                if ln == 1 or (i + ln <= n and tuple(tokens[i:i + ln]) == toks):
                    out.append((key, " ".join(toks)))
                    break
        return out


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    # 약어(e.g., i.e., vs., no.) 뒤에서 잘리지 않도록 최소한의 보호를 둔다.
    protected = re.sub(r"\b(e\.g|i\.e|vs|no|fig|approx|ca|cf|et al)\.", r"\1<DOT>", text, flags=re.I)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", protected)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


@dataclass
class OutcomeHit:
    outcome_id: str
    score: int
    matched: list[str]
    direction: str = "unclear"
    evidence: str = ""


@dataclass
class Classified:
    ingredients: list[tuple[str, str]] = field(default_factory=list)  # (id, 매칭된 표현)
    study_type: str = "other"
    subject: str = "unknown"
    outcomes: list[OutcomeHit] = field(default_factory=list)
    retracted: bool = False
    evidence_rank: int = 0


class Classifier:
    def __init__(self, ingredients: list[dict], outcomes: list[dict],
                 outcome_threshold: int = 2, max_outcomes: int = 4):
        self.outcome_threshold = outcome_threshold
        self.max_outcomes = max_outcomes

        # 성분: 검색어 → 성분 id (같은 표현이 겹치면 사전에 먼저 나온 성분을 쓴다)
        self._ing_idx = PhraseIndex()
        for ing in ingredients:
            for term in ing["synonyms"]:
                self._ing_idx.add(term, ing["id"], unique_phrase=True)
        self._ing_idx.finalize()

        # 결과지표: 본문 표현 → (지표 id, 가중치). 측정도구 3, MeSH 2, 일반어 1.
        self._out_idx = PhraseIndex()
        self._out_weight: dict[str, list[tuple[str, int]]] = {}
        for oc in outcomes:
            for term, weight in ([(t, 3) for t in oc["measures"]]
                                 + [(t, 1) for t in oc["terms"]]):
                toks = tuple(tokenize(term))
                if not toks:
                    continue
                phrase = " ".join(toks)
                self._out_idx.add(term, phrase)
                entry = (oc["id"], weight)
                bucket = self._out_weight.setdefault(phrase, [])
                if entry not in bucket:
                    bucket.append(entry)
        self._out_idx.finalize()

        self._mesh_lookup: dict[str, list[str]] = {}
        for oc in outcomes:
            for mh in oc["mesh"]:
                self._mesh_lookup.setdefault(_norm(mh), []).append(oc["id"])

        self._null_re = re.compile("|".join(NULL_PATTERNS), re.I)
        self._sig_re = re.compile("|".join(SIGNIFICANT_PATTERNS), re.I)

    # ── 성분 ────────────────────────────────────────────────────────────────
    def match_ingredients(self, title: str, abstract: str) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for iid, phrase in self._ing_idx.find(tokenize(f"{title}\n{abstract}")):
            found.setdefault(iid, phrase)
        return sorted(found.items())

    # ── 연구 유형 ───────────────────────────────────────────────────────────
    def study_type(self, pub_types: list[str], title: str, abstract: str) -> str:
        pts = {_norm(p) for p in (pub_types or [])}
        best = None
        for pt in pts:
            mapped = PUBTYPE_MAP.get(pt)
            if mapped and (best is None or STUDY_TYPES[mapped][1] > STUDY_TYPES[best][1]):
                best = mapped
        # RCT/메타분석은 초록 문구가 publication type 보다 이른 시점에 확실할 때가 많다.
        text = f"{title} {abstract}"
        # TEXT_STUDY_RULES 는 근거 위계 내림차순이므로 첫 매칭이 가장 강한 단서다.
        for st, pattern in TEXT_STUDY_RULES:
            if re.search(pattern, text, re.I):
                if best is None or STUDY_TYPES[st][1] > STUDY_TYPES[best][1]:
                    best = st
                break
        return best or "other"

    # ── 연구 대상 ───────────────────────────────────────────────────────────
    def subject(self, mesh: list[str], title: str, abstract: str) -> str:
        mh = {_norm(m) for m in (mesh or [])}
        has_human = bool(mh & MESH_HUMAN)
        has_animal = bool(mh & MESH_ANIMAL)
        if has_human and not has_animal:
            return "human"
        if has_animal and not has_human:
            return "animal"
        if has_human and has_animal:
            # 사람 MeSH 가 함께 붙은 동물 논문은 드물다. 본문으로 다시 판정.
            text = f"{title} {abstract}"
            return "human" if HUMAN_TEXT_RE.search(text) else "animal"

        text = f"{title} {abstract}"
        if INVITRO_TEXT_RE.search(text) and not HUMAN_TEXT_RE.search(text):
            return "invitro"
        if ANIMAL_TEXT_RE.search(text) and not HUMAN_TEXT_RE.search(text):
            return "animal"
        if HUMAN_TEXT_RE.search(text):
            return "human"
        return "unknown"

    # ── 결과지표 ────────────────────────────────────────────────────────────
    def match_outcomes(self, title: str, abstract: str, mesh: list[str]) -> list[OutcomeHit]:
        scores: dict[str, int] = {}
        matched: dict[str, list[str]] = {}

        seen_terms: set[str] = set()
        for phrase, _ in self._out_idx.find(tokenize(f"{title}\n{abstract}")):
            if phrase in seen_terms:
                continue              # 같은 표현의 반복은 한 번만 센다
            seen_terms.add(phrase)
            for oid, weight in self._out_weight.get(phrase, ()):
                scores[oid] = scores.get(oid, 0) + weight
                matched.setdefault(oid, []).append(phrase)

        for mh in (mesh or []):
            for oid in self._mesh_lookup.get(_norm(mh), []):
                scores[oid] = scores.get(oid, 0) + 2
                matched.setdefault(oid, []).append(f"MeSH:{mh}")

        hits = [OutcomeHit(oid, sc, matched.get(oid, [])[:6])
                for oid, sc in scores.items() if sc >= self.outcome_threshold]
        hits.sort(key=lambda h: (-h.score, h.outcome_id))
        return hits[:self.max_outcomes]

    # ── 결과 방향 ───────────────────────────────────────────────────────────
    def direction(self, abstract: str, outcome_terms: list[str]) -> tuple[str, str]:
        """(방향, 근거 문장). 결론 구간을 우선 보고, 없으면 결과 구간을 본다."""
        if not abstract:
            return "unclear", ""

        segment, sentences = self._conclusion_segment(abstract)
        # 해당 결과지표를 실제로 언급한 문장을 우선한다.
        keys = [re.sub(r"[\s\-]+", " ", _norm(t)) for t in outcome_terms
                if not t.startswith("MeSH:")]
        ranked: list[str] = []
        rest: list[str] = []
        for sent in sentences:
            ns = re.sub(r"[\s\-]+", " ", _norm(sent))
            (ranked if any(k and k in ns for k in keys) else rest).append(sent)
        candidates = ranked + rest

        for sent in candidates:
            verdict = self._verdict(sent)
            if verdict:
                return verdict, sent.strip()

        # 결론 구간에서 못 찾으면 초록 전체를 마지막으로 훑는다.
        if segment != abstract:
            verdict = self._verdict(abstract)
            if verdict:
                m = (self._null_re if verdict == "null" else self._sig_re).search(abstract)
                return verdict, self._sentence_around(abstract, m.start() if m else 0)
        return "unclear", ""

    def _verdict(self, sentence: str) -> str | None:
        """한 문장의 판정. 없으면 None.

        'no significant difference' 는 유의 표현 'significant difference' 를 통째로
        품고 있다. 그래서 부정 표현이 차지한 구간을 공백으로 가린 뒤에야 유의 표현을
        찾는다. 이렇게 해야 부정문이 유의 판정으로 뒤집히지 않는다.
        """
        spans = [m.span() for m in self._null_re.finditer(sentence)]
        masked = sentence
        for a, b in reversed(spans):
            masked = masked[:a] + " " * (b - a) + masked[b:]
        has_sig = bool(self._sig_re.search(masked))
        has_null = bool(spans)
        if has_null and not has_sig:
            return "null"
        if has_sig and not has_null:
            return "significant"
        if has_sig and has_null:
            return "unclear"     # 지표마다 결과가 갈린 문장
        return None

    @staticmethod
    def _sentence_around(text: str, pos: int) -> str:
        start = max(text.rfind(". ", 0, pos) + 1, 0)
        end = text.find(". ", pos)
        end = len(text) if end == -1 else end + 1
        return text[start:end].strip()

    @staticmethod
    def _conclusion_segment(abstract: str) -> tuple[str, list[str]]:
        m = None
        for m in CONCLUSION_RE.finditer(abstract):
            pass                      # 마지막 CONCLUSION 라벨을 쓴다
        if m:
            seg = abstract[m.end():]
            if len(seg) > 25:
                return seg, split_sentences(seg)
        r = None
        for r in RESULTS_RE.finditer(abstract):
            pass
        if r:
            seg = abstract[r.end():]
            if len(seg) > 25:
                return seg, split_sentences(seg)
        sents = split_sentences(abstract)
        # 구조화되지 않은 초록은 뒤쪽 절반이 결론일 가능성이 높다.
        return abstract, sents[len(sents) // 2:] or sents

    # ── 전체 ────────────────────────────────────────────────────────────────
    def classify(self, paper: dict) -> Classified:
        title = paper.get("title") or ""
        abstract = paper.get("abstract") or ""
        mesh = paper.get("mesh") or []
        pub_types = paper.get("pub_types") or []

        res = Classified()
        res.retracted = bool(
            RETRACTION_RE.search(title)
            or ({_norm(p) for p in pub_types} & RETRACT_PUBTYPES)
        )
        res.ingredients = self.match_ingredients(title, abstract)
        res.study_type = self.study_type(pub_types, title, abstract)
        res.subject = self.subject(mesh, title, abstract)
        res.outcomes = self.match_outcomes(title, abstract, mesh)

        # 동물·시험관 연구는 연구유형을 preclinical 로 눌러 근거 위계를 낮춘다.
        if res.subject in ("animal", "invitro") and res.study_type in ("other", "observational", "clinical_trial"):
            res.study_type = "preclinical"

        for hit in res.outcomes:
            hit.direction, hit.evidence = self.direction(abstract, hit.matched)

        res.evidence_rank = STUDY_TYPES[res.study_type][1] * 10 + (5 if res.subject == "human" else 0)
        return res
