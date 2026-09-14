#!/usr/bin/env python3
"""성분 분류 색 생성기.

화면에서 색을 쓰는 곳은 두 군데뿐이다.

1. 성분 분류 12종의 이름표 — 이 스크립트가 만든다.
2. 결과 방향 3색 — 표준 팔레트 값을 그대로 쓰고, 주변 색만 여기서 계산한다.

측정 항목의 계통 묶음(30 → 8)도 여기서 정하지만 색은 주지 않는다.
계통은 화면에 글자로만 나온다. data/palette.json 으로 내보낸다.
색은 OKLCH(사람 눈이 느끼는 밝기 기준 색 공간)에서 계산한다.
밝기(L)와 진하기(C)를 고정하고 색상(H)만 돌리므로,
어떤 색을 골라도 화면에서 느껴지는 무게가 같다.

- 라이트/다크 두 벌을 따로 계산한다.
- 글자로 쓰는 색(ink)은 배경 대비 4.5:1 을 만족할 때까지 밝기를 자동으로 조정한다.
- sRGB 밖으로 나가는 색은 진하기를 줄여 안으로 들여보낸다.

출력: web/colors.css  (직접 고치지 말고 이 스크립트를 고칠 것)
결과의 대비값은 --report 로 확인할 수 있다.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── OKLab / OKLCH ↔ sRGB ────────────────────────────────────────────────
# Björn Ottosson, "A perceptual color space for image processing" (2020)
# https://bottosson.github.io/posts/oklab/


def _oklab_to_lrgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _degamma(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def oklch_to_lrgb(L: float, C: float, H: float) -> tuple[float, float, float]:
    h = math.radians(H)
    return _oklab_to_lrgb(L, C * math.cos(h), C * math.sin(h))


def in_gamut(lrgb: tuple[float, float, float], eps: float = 1e-4) -> bool:
    return all(-eps <= v <= 1 + eps for v in lrgb)


def oklch_to_hex(L: float, C: float, H: float) -> str:
    """색역 밖이면 진하기를 이분 탐색으로 줄여 sRGB 안으로 들여보낸다."""
    if not in_gamut(oklch_to_lrgb(L, C, H)):
        lo, hi = 0.0, C
        for _ in range(30):
            mid = (lo + hi) / 2
            if in_gamut(oklch_to_lrgb(L, mid, H)):
                lo = mid
            else:
                hi = mid
        C = lo
    r, g, b = oklch_to_lrgb(L, C, H)
    out = []
    for v in (r, g, b):
        v = min(1.0, max(0.0, v))
        out.append(round(_gamma(v) * 255))
    return "#%02x%02x%02x" % tuple(out)


# ── 색 구분 정도 (ΔE) 와 색각 이상 시뮬레이션 ────────────────────────────
# Machado, Oliveira & Fernandes (2009), 강도 1.0, 선형 sRGB 기준 행렬.
# https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html

MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868],
               [0.114503, 0.786281, 0.099216],
               [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968],
               [0.280085, 0.672501, 0.047413],
               [-0.011820, 0.042940, 0.968881]],
}


def _lrgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _simulate(lrgb: tuple[float, float, float], vision: str) -> tuple[float, float, float]:
    m = MACHADO[vision]
    return tuple(min(1.0, max(0.0, sum(m[i][j] * lrgb[j] for j in range(3))))  # type: ignore[return-value]
                 for i in range(3))


def delta_e(a: str, b: str, vision: str | None = None) -> float:
    """OKLab 유클리드 거리 ×100. 두 색이 얼마나 달라 보이는지."""
    la = tuple(_degamma(v) for v in hex_to_rgb(a))
    lb = tuple(_degamma(v) for v in hex_to_rgb(b))
    if vision:
        la, lb = _simulate(la, vision), _simulate(lb, vision)
    x, y = _lrgb_to_oklab(*la), _lrgb_to_oklab(*lb)
    return 100 * math.sqrt(sum((x[i] - y[i]) ** 2 for i in range(3)))


def hex_to_oklch(hx: str) -> tuple[float, float, float]:
    L, a, b = _lrgb_to_oklab(*(_degamma(v) for v in hex_to_rgb(hx)))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def worst_pair(colors: list[str], vision: str | None = None) -> tuple[float, str, str]:
    return min((delta_e(colors[i], colors[j], vision), colors[i], colors[j])
               for i in range(len(colors)) for j in range(i + 1, len(colors)))


# ── 대비 (WCAG 2.1 상대 휘도) ────────────────────────────────────────────


def hex_to_rgb(hx: str) -> tuple[float, float, float]:
    hx = hx.lstrip("#")
    return tuple(int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(hx: str) -> float:
    r, g, b = (_degamma(v) for v in hex_to_rgb(hx))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ink_for(hue: float, chroma: float, bg: str, *, start: float, step: float,
            floor: float = 4.5, limit: int = 200) -> tuple[str, float, float]:
    """배경(bg) 대비 floor 를 넘을 때까지 밝기를 step 씩 옮긴다."""
    L = start
    for _ in range(limit):
        hx = oklch_to_hex(L, chroma, hue)
        if contrast(hx, bg) >= floor:
            return hx, L, contrast(hx, bg)
        L += step
        if not (0.02 <= L <= 0.99):
            break
    hx = oklch_to_hex(L, chroma, hue)
    return hx, L, contrast(hx, bg)


# ── 색상 배치 ────────────────────────────────────────────────────────────
# 유채색 11칸을 색상환에 고르게 놓는다(약 32.7도 간격). '기타'는 색을 거의 빼서
# 남은 분류를 가리지 않게 한다. 색은 이름표일 뿐이고 화면에는 언제나 글자가 함께 나온다.

CATEGORY_HUES: dict[str, float] = {
    "amino":      15,    # 아미노산·단백질
    "carotenoid": 48,    # 카로티노이드
    "vitamin":    80,    # 비타민
    "fiber":      113,   # 식이섬유·유산균
    "herb":       146,   # 약용식물·허브
    "algae":      179,   # 해조류·미세조류
    "mineral":    211,   # 미네랄
    "fatty_acid": 244,   # 지방산·지질
    "polyphenol": 277,   # 폴리페놀·플라보노이드
    "mushroom":   310,   # 버섯
    "animal":     342,   # 동물성 원료
    "other":      250,   # 기타 — 아래 MUTED 로 진하기를 낮춘다
}
MUTED = {"other"}

# 밝기를 번갈아 주는 폭. scripts/gen_colors.py --sweep 로 고른 값.
CATEGORY_DELTA = 0.06

# 측정 항목 30가지를 몸의 계통 8개로 묶는다. 묶음은 편집 판단이며,
# 화면에는 계통 '이름'만 글자로 나온다. 색은 주지 않는다 —
# 색은 성분 분류에만 쓴다는 원칙이 있고, 여덟 색을 더 얹으면 그 원칙이 무너진다.
# (가운데 숫자는 예전에 색상으로 쓰던 값이다. 지금은 목록 순서를 잡는 데만 쓴다.)
OUTCOME_FAMILIES: dict[str, tuple[str, float, list[str]]] = {
    "metabolic":  ("혈액·대사", 22,  ["lipid", "glucose", "blood_pressure", "weight",
                                      "blood_flow", "cardio_event", "anemia"]),
    "organ":      ("소화·간·콩팥", 68, ["liver", "gut", "kidney"]),
    "defense":    ("면역·염증", 112, ["inflammation", "oxidative", "immune", "allergy"]),
    "breath":     ("호흡기", 158, ["respiratory"]),
    "mind":       ("뇌·마음", 205, ["cognition", "mood", "sleep", "fatigue"]),
    "movement":   ("근육·뼈·관절", 250, ["muscle", "joint", "bone"]),
    "surface":    ("피부·머리·눈·입", 295, ["skin", "hair", "eye", "oral"]),
    "hormone":    ("호르몬·비뇨생식", 338, ["menopause", "prostate", "sexual", "thyroid"]),
}

# 결과 방향 3색. 이 색만이 '뜻을 나르는' 색이다.
# 값은 data-viz 표준 팔레트에서 그대로 가져왔고(1번 파랑, 2번 주황), 손대지 않는다.
# 검사 결과: 색각 이상에서도 최소 ΔE 24.7(라이트) / 26.8(다크) — 충분히 갈린다.
RESULT = {
    "light": {"sig": "#2a78d6", "null": "#eb6834", "unclear": "#c2c2ca"},
    "dark":  {"sig": "#3987e5", "null": "#d95926", "unclear": "#55555e"},
}

# 라이트/다크 각각의 목표값. ink 는 대비를 보고 자동으로 다시 잡는다.
THEMES = {
    "light": dict(surface="#f5f5f7", bg="#ffffff", tint_L=0.962, tint_C=0.030, ink_L=0.53, ink_C=0.150,
                  ink_step=-0.01, vivid_L=0.615, vivid_C=0.170, edge_L=0.86, edge_C=0.060),
    "dark":  dict(surface="#1d1d1f", bg="#000000", tint_L=0.248, tint_C=0.045, ink_L=0.80, ink_C=0.115,
                  ink_step=+0.01, vivid_L=0.665, vivid_C=0.155, edge_L=0.38, edge_C=0.075),
}


def shifts_for(keys: list[str], delta: float) -> dict[str, float]:
    """색상환을 도는 순서대로 밝기를 0, +d, -d 로 번갈아 준다.

    같은 밝기로 색상만 돌리면 색상이 가까운 두 칸이 색각 이상에서 겹친다.
    이웃끼리 밝기까지 어긋나게 두면 색을 구분하기 어려운 사람도 나눌 수 있고,
    세 단계를 도는 방식이라 전체 무게는 그대로 균형이 잡힌다."""
    pattern = (0.0, +1.0, -1.0)
    return {k: pattern[i % 3] * delta for i, k in enumerate(keys)}


def build(theme: str, hues: dict[str, float], muted: set[str],
          delta: float = 0.0) -> tuple[dict, list]:
    t = THEMES[theme]
    shifts = shifts_for(list(hues), delta)
    css: dict[str, str] = {}
    report = []
    for key, hue in hues.items():
        soft = key in muted
        dl = 0.0 if soft else shifts[key]
        tint_C = t["tint_C"] * (0.30 if soft else 1.0)
        ink_C = t["ink_C"] * (0.22 if soft else 1.0)
        vivid_C = t["vivid_C"] * (0.22 if soft else 1.0)
        edge_C = t["edge_C"] * (0.25 if soft else 1.0)

        tint = oklch_to_hex(t["tint_L"] + dl * 0.10, tint_C, hue)
        ink, inkL, ratio = ink_for(hue, ink_C, tint, start=t["ink_L"] + dl * 0.35,
                                   step=t["ink_step"])
        # 채워 쓰는 색은 글자가 아니므로 3:1 만 넘으면 된다(WCAG 1.4.11).
        vivid, vividL, _ = ink_for(hue, vivid_C, t["bg"], start=t["vivid_L"] + dl,
                                   step=t["ink_step"], floor=3.0)
        # 그러데이션 두 번째 정지점: 같은 계열 안에서 색상만 살짝 돌린다.
        vivid2 = oklch_to_hex(vividL + (0.05 if theme == "light" else 0.04),
                              vivid_C * 0.92, (hue + 20) % 360)
        edge = oklch_to_hex(t["edge_L"] + dl * 0.25, edge_C, hue)

        css[f"--c-{key}-tint"] = tint
        css[f"--c-{key}-edge"] = edge
        css[f"--c-{key}-ink"] = ink
        css[f"--c-{key}-vivid"] = vivid
        css[f"--c-{key}-vivid2"] = vivid2
        report.append(dict(theme=theme, key=key, hue=hue, ink=ink, ink_L=round(inkL, 3),
                           tint=tint, vivid=vivid,
                           ink_on_tint=round(ratio, 2),
                           ink_on_bg=round(contrast(ink, t["bg"]), 2),
                           vivid_on_bg=round(contrast(vivid, t["bg"]), 2)))
    return css, report


def audit(name: str, colors: list[str], surface: str) -> list[str]:
    """색끼리 얼마나 구분되는지, 바탕과 얼마나 대비되는지 재서 표로 돌려준다."""
    lines = []
    for vision, label in ((None, "보통 시각"), ("protan", "적색약"), ("deutan", "녹색약")):
        d, a, b = worst_pair(colors, vision)
        lines.append(f"  {name:22} {label:6} 최소 ΔE {d:5.1f}   {a} ↔ {b}")
    lo = min(contrast(c, surface) for c in colors)
    lines.append(f"  {name:22} {'바탕 대비':6} 최소 {lo:5.2f}:1")
    return lines


def build_result(theme: str) -> tuple[dict, list[str]]:
    """결과 3색과, 그 색으로 쓰는 글자색을 정한다.

    본색은 표준 팔레트 값 그대로 두고 손대지 않는다.
    막대는 페이지 바탕(--bg) 위에 놓이고, 글자는 카드 바탕(--bg-2) 위에도 놓인다.
    그래서 막대는 페이지 바탕 기준 3:1(WCAG 1.4.11), 글자는 둘 중 더 빡빡한
    카드 바탕 기준 4.5:1 을 확인한다."""
    t = THEMES[theme]
    surface, page = t["surface"], t["bg"]
    css: dict[str, str] = {}
    notes = []
    for key, base in RESULT[theme].items():
        L, C, H = hex_to_oklch(base)
        if key == "unclear":
            # 판정 불가는 색이 아니라 '색 없음'이다. 회색으로 두되,
            # 카드 바탕에 묻히지 않을 만큼만 진하게 잡는다.
            base = ink_for(H, 0.004, page, start=L, step=t["ink_step"], floor=3.0)[0]
        css[f"--{key}"] = base
        chroma = 0.004 if key == "unclear" else t["ink_C"]
        ink, _, ratio = ink_for(H, chroma, surface, start=t["ink_L"], step=t["ink_step"])
        css[f"--{key}-ink"] = ink
        notes.append(f"  {theme:5} {key:8} 막대 {base} (페이지 바탕 대비 "
                     f"{contrast(base, page):.2f}:1) · 글자 {ink} (카드 바탕 대비 {ratio:.2f}:1)")
    return css, notes


def emit(pairs: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}{k}:{v};" for k, v in pairs.items())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "web" / "colors.css"))
    ap.add_argument("--report", action="store_true", help="대비값을 표로 출력")
    ap.add_argument("--audit", action="store_true", help="색 구분 정도(ΔE)를 측정해 출력")
    ap.add_argument("--sweep", action="store_true", help="밝기 폭 후보를 훑어 최소 ΔE 비교")
    args = ap.parse_args()

    if args.sweep:
        print("밝기 폭별 최소 ΔE — 성분 분류 12종 (라이트/다크 중 나쁜 쪽)")
        print(f"{'폭':>6} | {'보통시각':>8} {'색각이상':>9}")
        for d in [round(x / 200, 3) for x in range(0, 29, 2)]:
            norm, cvd = [], []
            for theme in ("light", "dark"):
                css, _ = build(theme, CATEGORY_HUES, MUTED, d)
                cols = [v for k, v in css.items() if k.endswith("-vivid")]
                norm.append(worst_pair(cols)[0])
                cvd.append(min(worst_pair(cols, v)[0] for v in ("protan", "deutan")))
            print(f"{d:6.3f} | {min(norm):8.1f} {min(cvd):9.1f}")
        return 0

    cat_names = json.loads((ROOT / "data" / "ingredients.json").read_text("utf-8"))["_meta"]["categories"]
    fam_hues = {k: v[1] for k, v in OUTCOME_FAMILIES.items()}

    blocks = {}
    report = []
    result_notes: list[str] = []
    for theme in ("light", "dark"):
        a, ra = build(theme, CATEGORY_HUES, MUTED, CATEGORY_DELTA)
        c, notes = build_result(theme)
        blocks[theme] = {**a, **c}
        report += ra
        result_notes += notes

    if args.report:
        print(f"{'theme':6} {'key':11} {'hue':>5} {'ink':8} {'ink/tint':>9} {'ink/bg':>7} {'vivid/bg':>9}")
        for r in report:
            print(f"{r['theme']:6} {r['key']:11} {r['hue']:5.0f} {r['ink']:8} "
                  f"{r['ink_on_tint']:9.2f} {r['ink_on_bg']:7.2f} {r['vivid_on_bg']:9.2f}")
        worst = min(r["ink_on_tint"] for r in report)
        print(f"\n글자색 최저 대비 {worst:.2f}:1 (기준 4.5:1)")

    if args.audit:
        print("\n결과 방향 3색 (뜻을 나르는 색)")
        for line in result_notes:
            print(line)
        for theme in ("light", "dark"):
            surface = THEMES[theme]["bg"]
            print(f"\n[{theme}]")
            for name, hues, muted, d in (("성분 분류 12종", CATEGORY_HUES, MUTED, CATEGORY_DELTA),):
                css, _ = build(theme, hues, muted, d)
                for line in audit(name, [v for k, v in css.items() if k.endswith("-vivid")], surface):
                    print(line)

    fam_map = {oid: fam for fam, (_, _, ids) in OUTCOME_FAMILIES.items() for oid in ids}
    known = {o["id"] for o in json.loads((ROOT / "data" / "outcomes.json").read_text("utf-8"))["outcomes"]}
    missing = known - set(fam_map)
    if missing:
        raise SystemExit(f"계열이 없는 측정 항목: {sorted(missing)}")

    worst_lines = []
    for theme in ("light", "dark"):
        for name, hues, muted, d in (("분류 12종", CATEGORY_HUES, MUTED, CATEGORY_DELTA),):
            css_, _ = build(theme, hues, muted, d)
            cols = [v for k, v in css_.items() if k.endswith("-vivid")]
            n = worst_pair(cols)[0]
            c = min(worst_pair(cols, v)[0] for v in ("protan", "deutan"))
            worst_lines.append(f"     {theme:5} {name}  보통 시각 {n:.1f} · 색각 이상 {c:.1f}")

    head = (
        "/* 이 파일은 scripts/gen_colors.py 가 만든다. 직접 고치지 말 것.\n"
        "   다시 만들기:  python scripts/gen_colors.py\n\n"
        "   성분 분류 12종의 이름표 색.\n"
        "   OKLCH(사람 눈이 느끼는 밝기 기준 색 공간)에서 뽑았고, 밝기와 진하기를\n"
        "   거의 고정한 채 색상만 돌렸다. 그래서 어느 색을 골라도 화면에서 느껴지는\n"
        "   무게가 같고, 어떤 분류가 더 중요해 보이는 일이 없다.\n\n"
        "   ■ 이 색들은 '데이터'가 아니라 '이름표'다.\n"
        "     분류가 12가지나 되므로 색만으로 서로 구분되게 만들 수는 없다.\n"
        "     실제로 재보면 두 색이 가장 비슷할 때의 차이(OKLab ΔE×100)는\n"
        + "".join(l + "\n" for l in worst_lines) +
        "     이고, 색각 이상에서는 사실상 겹친다. 그래서 색에 뜻을 싣지 않았다.\n"
        "     분류 이름표에는 언제나 한글 이름이 함께 붙고, 색을 못 보아도\n"
        "     읽는 데 아무 지장이 없다.\n\n"
        "   ■ 뜻을 나르는 색은 따로 있다: 결과 방향 3색(--sig/--null/--unclear).\n"
        "     그 3색만 색각 이상 검사를 통과하도록 골랐고, 그마저도 막대마다\n"
        "     숫자와 글자 라벨을 함께 둔다.\n\n"
        "   ■ 이 둘 말고는 화면에 색을 쓰지 않는다. 측정 항목의 계통 묶음도\n"
        "     이름만 글자로 보여 주고 색은 주지 않는다. */\n\n"
    )
    css = head
    css += ":root {\n" + emit(blocks["light"]) + "\n}\n"
    css += '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {\n'
    css += emit(blocks["dark"], "    ") + "\n  }\n}\n"
    css += ':root[data-theme="dark"] {\n' + emit(blocks["dark"]) + "\n}\n"

    # 화면 코드가 분류 이름만 붙이면 그 자리의 색이 통째로 바뀌도록 이름을 이어 준다.
    # style.css 는 --tone-* 만 쓰고 분류 목록을 알 필요가 없다.
    css += ("\n/* data-cat 이 붙은 곳에서 --tone-* 가 그 분류의 색이 된다.\n"
            "   style.css 는 분류 이름을 하나도 몰라도 된다. */\n")
    for attr, keys in (("data-cat", CATEGORY_HUES),):
        for key in keys:
            css += (f'[{attr}="{key}"] {{ '
                    f"--tone:var(--c-{key}-ink); "
                    f"--tone-bg:var(--c-{key}-tint); "
                    f"--tone-edge:var(--c-{key}-edge); "
                    f"--tone-v:var(--c-{key}-vivid); "
                    f"--tone-v2:var(--c-{key}-vivid2); }}\n")

    Path(args.out).write_text(css, "utf-8")

    meta = {
        "categories": {k: {"ko": cat_names[k], "hue": CATEGORY_HUES[k]} for k in CATEGORY_HUES},
        "outcome_families": {k: {"ko": v[0], "hue": v[1], "outcomes": v[2]}
                             for k, v in OUTCOME_FAMILIES.items()},
        "outcome_family_of": fam_map,
    }
    (ROOT / "data" / "palette.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print(f"{args.out} — 성분 분류 {len(CATEGORY_HUES)}종의 색")
    print(f"{ROOT / 'data' / 'palette.json'} — 측정 항목 계통 묶음 {len(fam_map)}개 (색 없음, 이름만)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
