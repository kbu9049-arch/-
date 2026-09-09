#!/usr/bin/env python3
"""테스트용 논문 픽스처 생성기.

여기서 만드는 레코드는 **실제 논문이 아니다.** 파이프라인·API·화면이 제대로
동작하는지 확인하기 위한 합성 데이터이며, 실제 근거로 오인되지 않도록:
  - source 를 'FIXTURE' 로 둔다 (실제 문헌은 MED/PMC/PPR).
  - ext_id 를 'FIXTURE-*' 로 둔다 (PMID 자리에는 아무것도 넣지 않는다).
  - 제목 앞에 '[테스트 픽스처]' 를 붙인다.
  - url 을 비워 둔다 (실제 논문 링크로 연결되지 않게).
서버는 source='FIXTURE' 인 논문 수를 세어 화면 상단에 경고를 띄운다.
"""
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ING = json.loads((ROOT / "data" / "ingredients.json").read_text(encoding="utf-8"))["ingredients"]
OUT = json.loads((ROOT / "data" / "outcomes.json").read_text(encoding="utf-8"))["outcomes"]

DESIGNS = [
    ("randomized, double-blind, placebo-controlled trial",
     ["Randomized Controlled Trial", "Journal Article"], ["Humans", "Adult", "Male", "Female"]),
    ("systematic review and meta-analysis of randomized controlled trials",
     ["Meta-Analysis", "Systematic Review", "Journal Article"], ["Humans"]),
    ("open-label clinical trial", ["Clinical Trial", "Journal Article"], ["Humans", "Adult"]),
    ("prospective cohort study", ["Observational Study", "Journal Article"], ["Humans", "Aged"]),
    ("study in high-fat diet fed C57BL/6 mice", ["Journal Article"], ["Animals", "Mice"]),
    ("in vitro study using HepG2 cells", ["Journal Article"], []),
]

CONCLUSIONS = [
    ("significant", "CONCLUSIONS: {agent} significantly improved {measure} compared with "
                    "placebo (p < 0.01)."),
    ("significant", "CONCLUSIONS: A statistically significant reduction in {measure} was "
                    "observed in the treatment arm (p = 0.003)."),
    ("null", "CONCLUSIONS: There was no significant difference in {measure} between the "
             "{agent} and placebo groups."),
    ("null", "CONCLUSIONS: {agent} did not significantly change {measure} over the study period "
             "(p = 0.42)."),
    ("unclear", "CONCLUSIONS: Effects on {measure} were inconsistent across trials and further "
                "research is needed."),
]


def build(n_ingredients=40, per_ingredient=30, seed=20260909):
    rng = random.Random(seed)
    outs = {o["id"]: o for o in OUT}
    picked = ING[:n_ingredients]
    records, counter = [], 0

    for ing in picked:
        # 성분마다 2~4개의 지표에 연구가 몰리도록 한다 (실제 분포와 비슷하게)
        topics = rng.sample(OUT, rng.randint(2, 4))
        for _ in range(per_ingredient):
            counter += 1
            oc = rng.choice(topics)
            measure = rng.choice(oc["measures"])
            design, pubtypes, mesh = rng.choice(DESIGNS)
            _, template = rng.choice(CONCLUSIONS)
            agent = ing["name_en"]
            term = rng.choice(ing["synonyms"])
            year = rng.randint(2005, 2025)

            title = (f"[테스트 픽스처] Effect of {term} on {measure}: a {design}")
            abstract = (
                f"BACKGROUND: {agent} is widely marketed for {oc['label_en'].lower()}. "
                f"METHODS: This was a {design} evaluating {term} supplementation. "
                f"{measure.capitalize()} was the primary outcome. "
                f"RESULTS: Changes in {measure} were recorded at baseline and follow-up. "
                + template.format(agent=agent, measure=measure)
            )
            records.append({
                "source": "FIXTURE",
                "ext_id": f"FIXTURE-{counter:06d}",
                "pmid": None,
                "pmcid": None,
                "doi": None,
                "title": title,
                "abstract": abstract,
                "journal": "테스트 픽스처 (실제 학술지 아님)",
                "year": year,
                "authors": "픽스처 생성기",
                "pub_types": pubtypes,
                "mesh": mesh + [m for m in oc["mesh"][:1]],
                "cited_by": rng.randint(0, 200),
                "is_oa": 0,
                "url": "",
            })
    return records


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
        pathlib.Path(__file__).parent / "sample_papers.jsonl")
    recs = build()
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                   encoding="utf-8")
    print(f"{out}: {len(recs):,}건 (전부 합성 테스트 데이터)")
