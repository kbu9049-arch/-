"""분류기 단위 테스트.

여기 쓰인 초록 문장은 **분류 규칙을 시험하기 위해 작성한 테스트 문자열**이며
실제 논문이 아니다. 실제 논문이라고 오인될 수 없도록 pmid 를 TEST-* 로 둔다.
이 문자열은 테스트에서만 쓰이고 서비스 DB 에는 들어가지 않는다.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ingest.classify import Classifier, split_sentences  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ING = json.loads((ROOT / "data" / "ingredients.json").read_text(encoding="utf-8"))["ingredients"]
OUT = json.loads((ROOT / "data" / "outcomes.json").read_text(encoding="utf-8"))["outcomes"]
C = Classifier(ING, OUT)

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


# ── 성분 매칭 ────────────────────────────────────────────────────────────────
def test_ingredient_matching():
    ids = dict(C.match_ingredients(
        "Effect of Korean red ginseng and coenzyme Q10 on fatigue", ""))
    check("red_ginseng 매칭", "red_ginseng" in ids, True)
    check("coq10 매칭", "coq10" in ids, True)

    # 하이픈/공백 표기 차이 흡수
    check("beta-alanine", "beta_alanine" in dict(C.match_ingredients("Beta alanine loading", "")), True)
    check("omega-3", "omega3" in dict(C.match_ingredients("Omega 3 fatty acid intake", "")), True)

    # 단일 일반명사는 보충제 맥락에서만 잡혀야 한다
    check("구리 오탐 방지", dict(C.match_ingredients("Copper wire corrosion in reactors", "")), {})
    check("구리 정탐", "copper" in dict(C.match_ingredients("Copper supplementation in adults", "")), True)

    # 접두 일치로 인한 오탐 방지
    check("vitamin d ≠ vitamin d3 오탐", dict(C.match_ingredients("Vitamin D3 dosing", "")).get("vitamin_d"), "vitamin d3")


# ── 연구 유형 ────────────────────────────────────────────────────────────────
def test_study_type():
    check("RCT(pubtype)", C.study_type(["Randomized Controlled Trial", "Journal Article"], "x", ""), "rct")
    check("RCT(본문)", C.study_type([], "A double-blind, placebo-controlled study of lutein", ""), "rct")
    check("메타분석", C.study_type([], "Curcumin and CRP: a systematic review and meta-analysis", ""), "meta_analysis")
    check("체계적 문헌고찰", C.study_type([], "A systematic review of probiotics for constipation", ""), "systematic_review")
    check("관찰연구", C.study_type([], "Dietary magnesium and stroke risk: a prospective cohort study", ""), "observational")
    # publication type 이 더 강할 때는 그쪽을 택한다
    check("pubtype 우선", C.study_type(["Meta-Analysis"], "A cross-sectional analysis", ""), "meta_analysis")


# ── 연구 대상 ────────────────────────────────────────────────────────────────
def test_subject():
    check("MeSH Humans", C.subject(["Humans", "Adult", "Male"], "t", "a"), "human")
    check("MeSH Animals", C.subject(["Animals", "Mice"], "t", "a"), "animal")
    check("본문 동물", C.subject([], "Effects in high-fat diet fed C57BL/6 mice", ""), "animal")
    check("본문 시험관", C.subject([], "Antioxidant activity in vitro using HepG2 cell line", ""), "invitro")
    check("본문 사람", C.subject([], "Sixty healthy adults received the supplement", "Patients were followed"), "human")
    check("불명", C.subject([], "Chemical characterization of the extract", ""), "unknown")


# ── 결과지표 ─────────────────────────────────────────────────────────────────
def test_outcomes():
    hits = C.match_outcomes(
        "Effect of psyllium on LDL cholesterol and fasting blood glucose", "", [])
    ids = {h.outcome_id for h in hits}
    check("지질 지표", "lipid" in ids, True)
    check("혈당 지표", "glucose" in ids, True)

    # 측정도구 한 개(가중치 3)만으로도 분류된다
    hits = C.match_outcomes("Sleep study", "PSQI scores were assessed at week 8.", [])
    check("PSQI 단독 분류", {h.outcome_id for h in hits}, {"sleep"})

    # 일반어 한 개(가중치 1)만으로는 분류되지 않는다
    hits = C.match_outcomes("A note on inflammation", "", [])
    check("일반어 단독 미분류", hits, [])

    # MeSH 단독(가중치 2)으로 분류된다
    hits = C.match_outcomes("Untitled", "", ["Bone Density"])
    check("MeSH 단독 분류", {h.outcome_id for h in hits}, {"bone"})


# ── 결과 방향 ────────────────────────────────────────────────────────────────
def test_direction():
    d, ev = C.direction(
        "METHODS: Ninety adults were randomized. RESULTS: LDL fell by 8 mg/dL. "
        "CONCLUSIONS: Supplementation significantly reduced LDL cholesterol (p<0.01).",
        ["ldl cholesterol"])
    check("유의 판정", d, "significant")
    check("유의 근거문장", "significantly reduced" in ev, True)

    d, ev = C.direction(
        "CONCLUSIONS: There was no significant difference in body weight between groups.",
        ["body weight"])
    check("유의차 없음 판정", d, "null")
    check("무효 근거문장", "no significant difference" in ev, True)

    d, _ = C.direction(
        "CONCLUSIONS: Sleep latency improved significantly, but no significant difference "
        "was seen in total sleep time.", ["sleep latency"])
    check("혼재 시 판정불가", d, "unclear")

    d, _ = C.direction("CONCLUSIONS: Further studies are warranted.", ["fatigue"])
    check("근거 없으면 판정불가", d, "unclear")

    # 결론 라벨이 없는 초록도 뒤쪽 문장에서 판정한다
    d, _ = C.direction(
        "We enrolled 40 men. Grip strength was measured. Handgrip strength increased "
        "significantly in the treatment arm (p < 0.05).", ["handgrip strength"])
    check("비구조화 초록", d, "significant")

    # 결론이 무효인데 결과 구간에 유의 표현이 섞인 경우 결론을 우선한다
    d, _ = C.direction(
        "RESULTS: CRP decreased significantly at week 4. "
        "CONCLUSIONS: The supplement did not significantly reduce CRP over 12 weeks.",
        ["c-reactive protein"])
    check("결론 우선", d, "null")


# ── 철회 논문 ────────────────────────────────────────────────────────────────
def test_retraction():
    r = C.classify({"pmid": "TEST-0001", "title": "RETRACTED: Zinc supplementation and the common cold",
                    "abstract": "", "mesh": [], "pub_types": []})
    check("철회 표시(제목)", r.retracted, True)
    r = C.classify({"pmid": "TEST-0002", "title": "Zinc and colds", "abstract": "",
                    "mesh": [], "pub_types": ["Retracted Publication"]})
    check("철회 표시(pubtype)", r.retracted, True)
    r = C.classify({"pmid": "TEST-0003", "title": "Zinc supplementation and colds", "abstract": "",
                    "mesh": [], "pub_types": ["Journal Article"]})
    check("정상 논문", r.retracted, False)


# ── 통합 ─────────────────────────────────────────────────────────────────────
def test_classify_end_to_end():
    r = C.classify({
        "pmid": "TEST-0100",
        "title": "Effect of curcumin supplementation on C-reactive protein: a randomized, "
                 "double-blind, placebo-controlled trial",
        "abstract": "BACKGROUND: Chronic inflammation is common. METHODS: Eighty patients were "
                    "randomized to curcumin or placebo for 12 weeks. RESULTS: hs-CRP declined. "
                    "CONCLUSIONS: Curcumin significantly reduced C-reactive protein levels "
                    "compared with placebo (p < 0.01).",
        "mesh": ["Humans", "C-Reactive Protein", "Inflammation", "Adult"],
        "pub_types": ["Randomized Controlled Trial", "Journal Article"],
    })
    check("성분", [i for i, _ in r.ingredients], ["curcumin"])
    check("연구유형", r.study_type, "rct")
    check("대상", r.subject, "human")
    check("지표", [h.outcome_id for h in r.outcomes], ["inflammation"])
    check("방향", r.outcomes[0].direction, "significant")
    check("근거문장 저장", bool(r.outcomes[0].evidence), True)

    # 동물 연구는 근거 위계가 낮아진다
    r2 = C.classify({
        "pmid": "TEST-0101",
        "title": "Quercetin improves glucose tolerance in db/db mice",
        "abstract": "Mice were fed quercetin for 8 weeks. Fasting blood glucose was "
                    "significantly decreased (p<0.05).",
        "mesh": ["Animals", "Mice", "Blood Glucose"], "pub_types": ["Journal Article"],
    })
    check("동물 대상", r2.subject, "animal")
    check("전임상으로 강등", r2.study_type, "preclinical")
    check("동물 근거점수 < 사람 RCT", r2.evidence_rank < r.evidence_rank, True)


def test_sentence_split():
    s = split_sentences("Dose was 500 mg (e.g., twice daily). CRP fell. No harm was seen.")
    check("문장 분리 개수", len(s), 3)


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if FAILS:
        print(f"\n실패 {len(FAILS)}건:")
        for f in FAILS:
            print("  ✗", f)
        sys.exit(1)
    print("분류기 테스트 전부 통과")
