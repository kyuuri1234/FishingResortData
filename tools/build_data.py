"""公開用の CSV と、説明ページの表を生成する.

    python3 tools/build_data.py --game <展開先>

ゲームの抽出ファイルと DOL から直接読む (tools/gamedata.py)。手書きの説明ページの
`<!-- table:名前 -->` 〜 `<!-- /table -->` の間も、ここで作った表で置き換える。
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import unicodedata
from collections import defaultdict
from pathlib import Path

from gamedata import (AREA_NAME, AREA_ORDER, EXHIBIT, FREE_AREAS, GATE_RATE, JUNK, LURE_TYPES, MISSING, SEA_NAME,
                      Game, band_probs, band_ranges, color_step, lottery, rank_borders, rank_ladder,
                      rank_probs, rank_result, shift_probs, size_borders, size_from_100, size_gate)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"

WEATHER = ["快晴", "晴れ", "薄曇り", "曇り", "厚い曇り"]
BANDS = ["朝", "昼", "夕", "夜"]
COLOR_NAME = {1: "黒", 2: "赤", 3: "赤橙", 4: "橙", 5: "桃・紫", 6: "茶", 7: "銀・白", 8: "金",
              9: "黄", 10: "オリーブ", 11: "緑", 12: "青"}
TROLL_LURE = ["1番 赤橙", "2番 紫", "3番 黄", "4番 銀灰", "5番 水色"]
ROD_CHECK_SEC = 7.5
LURE_SHORT = {"スプーン": "スプーン", "スピナー": "スピナー", "クランクベイト": "クランク",
              "バイブレーション": "バイブ", "ミノー": "ミノー"}
MECHANISM = ["汎用", "ラトル", "振動"]
CATEGORY = ["手のひら", "糸をつかむ", "両手", "水中"]
RANKS = "SABCDE"
WEEKDAY = "月火水木金土日"
ODDS_ROW = 6  # レベル6つごとに重みの行が進む
CAST_RATE = {0: 1.0, 1: 1.5, 2: 2.0}
ROD_CLASS = ["LF", "MF", "HF", "X"]
SIZE_LABEL = {3: "0〜70", 2: "20〜70", 6: "20〜200", 4: "50〜200", 12: "50〜", 8: "150〜"}

def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    with (DATA / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)

def md_table(header: list[str], rows: list[list], align: list[str] | None = None) -> str:
    align = align or ["---"] * len(header)
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)

def compress(nums: list[int]) -> str:
    out = []
    nums = sorted(nums)
    s = p = nums[0]
    for v in nums[1:]:
        if v == p + 1:
            p = v
            continue
        out.append(str(s) if s == p else f"{s}〜{p}")
        s = p = v
    out.append(str(s) if s == p else f"{s}〜{p}")
    return "、".join(out)

def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}"


def size_text(lo: float, hi: float | None) -> str:
    return f"{lo:g}〜{hi:g}" if hi is not None else f"{lo:g}〜"

class Builder:
    def __init__(self, game_root: Path) -> None:
        self.g = Game(game_root)
        self.text = self.g.text_ids()
        self.fish = self.g.fish()
        self.by_id = {f.id: f for f in self.fish}
        self.lures = self.g.lures()
        self.baits = self.g.baits(self.text)
        self.spots = self.g.spots()
        self.troll = self.g.troll_table()
        self.free = {a: self.g.free_table(a) for a in FREE_AREAS}
        self.stock = set(self.g.stock_table())
        self.unlocks = {u.fish: u for u in self.g.quest_unlocks(self.text)}
        self.quest = {f for f, u in self.unlocks.items() if u.step}
        self.never = EXHIBIT | MISSING
        self.tables: dict[str, str] = {}
        self.where: dict[int, list[str]] = defaultdict(list)
        self.shift = [shift_probs(w) for w in self.g.color_shift_weights()]
        self.pattern = [shift_probs(w) for w in self.g.bait_pattern_weights()]
        self.step_mult = self.g.color_distance_table()
        self.category = self.g.fish_categories()
        self.params = self.g.battle_params()
        self.pulls = self.g.pull_speeds()
        self.rods = self.g.rods(self.text)
        self.reels = self.g.reels(self.text)

    def name(self, fid: int) -> str:
        return self.by_id[fid].name

    def condition(self, fid: int) -> str:
        if fid in self.stock:
            return "放流"
        if fid in self.quest:
            return "クエスト"
        return ""

    def rates(self, entries) -> dict[int, tuple[float, float, float, int]]:
        """(序盤, 標準, 全解禁, 重み)。重みは時間帯で変わらないことを確かめてある."""
        for e in entries:
            assert len(set(e.p)) == 1, "時間帯で重みが違う行"
        start = lottery(entries, 0, self.never | self.stock | self.quest)
        main = lottery(entries, 0, self.never | self.stock)
        full = lottery(entries, 0, self.never)
        weights: dict[int, int] = defaultdict(int)
        for e in entries:
            if e.p[0] > 0:
                weights[e.fish] += e.p[0]
        return {f: (start.get(f, 0.0), main.get(f, 0.0), full[f], weights[f]) for f in full}

    # --- 魚 ----------------------------------------------------------------
    def build_fish(self, areas_of: dict[int, set[str]]) -> None:
        rows = []
        for f in self.fish:
            b = size_borders(f) if f.base_cm > 0 else None
            types = [LURE_TYPES[i] for i in range(5) if f.lure_mask >> i & 1]
            if f.gate_class == 3:
                types = []
            note = ("展示専用" if f.id in EXHIBIT else "欠番" if f.id in MISSING else
                    "ゴミ" if f.id in JUNK else "")
            cond = self.condition(f.id)
            rows.append([f.id, f.name, f.grade, f.points, f.exp, f.base_cm, b["min"], b["max"],
                         b["s_result"], b["s_dex"], f.base_color, f.mechanism, f.bait_group,
                         ";".join(types), GATE_RATE[f.gate_class] if types else 0,
                         cond, note, ";".join(sorted(areas_of.get(f.id, []))),
                         CATEGORY[self.category[f.id]], f.pull_class, *self.pulls[f.pull_class],
                         f.stamina, f.speed_coef, self.params[f.rush_index], f.rush_div,
                         self.params[f.speed_cap_index]])
        write_csv("fish.csv", ["fish_id", "name", "grade", "points", "exp", "base_cm", "min_cm",
                               "max_cm", "s_min_result_cm", "s_min_dex_cm", "base_color",
                               "mechanism", "bait_group", "lure_types", "lure_accept_rate",
                               "unlock", "note", "areas", "hold", "pull_class", "pull_speed_a", "pull_speed_b",
                               "stamina", "speed_coef", "rush_threshold", "rush_div", "speed_cap"], rows)
        self.tables["junk-list"] = "、".join(self.name(i) for i in sorted(JUNK))

    # --- 通常の釣り場 ------------------------------------------------------
    def build_spawn(self) -> dict[int, set[str]]:
        spot_rows, rate_rows, area_rows = [], [], []
        areas_of: dict[int, set[str]] = defaultdict(set)
        for area in FREE_AREAS:
            active = []
            for s, entries in sorted(self.free[area].items()):
                sp = self.spots[area][s]
                ok = sp.has_rect and max(sp.caps) > 0
                r = self.rates(entries) if ok else {}
                if ok and r:
                    active.append((sp, r))
                    spot_rows.append([area, AREA_NAME[area], s, round(sp.x, 1), round(sp.z, 1),
                                      round(sp.sx * 2, 1), round(sp.sz * 2, 1), round(sp.rot, 1),
                                      round(4 * sp.sx * sp.sz), *sp.caps,
                                      round(60 * sp.density_a, 1), sp.bait_adjust])
                    for f, (a, b, c, w) in sorted(r.items(), key=lambda kv: -kv[1][2]):
                        rate_rows.append([area, AREA_NAME[area], s, f, self.name(f), w,
                                          f"{a * 100:.2f}", f"{b * 100:.2f}", f"{c * 100:.2f}",
                                          self.condition(f)])
                        areas_of[f].add(area)
            area_rows.append([f"[{AREA_NAME[area]}](../index.html#map/{area})", len(active),
                              len({f for _, r in active for f in r})])
        self.spot_rows, self.rate_rows = spot_rows, rate_rows
        self.tables["area-index"] = md_table(["エリア", "スポット数", "魚の種類"], area_rows,
                                             ["---", "--:", "--:"])
        return areas_of

    # --- 外海 --------------------------------------------------------------
    def build_offshore(self, areas_of: dict[int, set[str]]) -> None:
        zones = {s: sp for s, sp in self.spots["Wholeisland"].items() if sp.has_rect}
        for s, sp in sorted(zones.items()):
            r = self.rates(self.troll[sp.table_group])
            assert 10 <= sp.table_group <= 18
            self.spot_rows.append(["Offshore", "外海", s, round(sp.x, 1), round(sp.z, 1), round(sp.sx * 2),
                                   round(sp.sz * 2), 0, round(4 * sp.sx * sp.sz), *sp.caps,
                                   round(60 * sp.density_a, 1), sp.bait_adjust])
            for f, (a, b, c, w) in sorted(r.items(), key=lambda kv: -kv[1][2]):
                self.rate_rows.append(["Offshore", "外海", s, f, self.name(f), w, f"{a * 100:.2f}",
                                       f"{b * 100:.2f}", f"{c * 100:.2f}", self.condition(f)])
                areas_of[f].add("Offshore")

    # --- ルアーの色 ----------------------------------------------------------
    def build_lure(self) -> None:
        rows = []
        for l in self.lures:
            lo, hi = l.size_range
            rows.append([l.id, l.name, LURE_TYPES[l.type_index], l.color1, l.color2, l.mechanism,
                         lo, hi if hi is not None else "", f"{l.appeal:g}", l.price if l.price > 0 else ""])
        write_csv("lures.csv", ["lure_id", "name", "type", "color1", "color2", "mechanism", "size_min_cm",
                                "size_max_cm", "appeal_base_m", "price"], rows)

        rows = []
        score: dict[tuple[int, int], dict[tuple[int, int], tuple[float, float]]] = {}
        pairs: dict[tuple[int, int], list] = defaultdict(list)
        for l in self.lures:
            pairs[tuple(sorted((l.color1, l.color2)))].append(l)
        for base in range(1, 13):
            for w in range(5):
                res = {}
                for pair in pairs:
                    e = z = 0.0
                    for s, p in enumerate(self.shift[w]):
                        fav = base + s
                        if fav >= 13:
                            fav -= 12
                        m = self.step_mult[color_step(pair[0], pair[1], fav)]
                        e += p * m
                        z += p if m == 0 else 0
                    res[pair] = (e, z)
                score[(base, w)] = res
                for l in self.lures:
                    e, z = res[tuple(sorted((l.color1, l.color2)))]
                    rows.append([base, WEATHER[w], l.id, l.name, LURE_TYPES[l.type_index],
                                 f"{e:.3f}", f"{z:.3f}"])
        write_csv("lure_color_scores.csv", ["base_color", "weather", "lure_id", "lure", "type",
                                            "expected_multiplier", "zero_rate"], rows)

        def pname(p):
            a, b = p
            return f"{a}+{b}" if a else f"{b}のみ"

        cells = []
        for base in range(1, 13):
            row = [f"{base} {COLOR_NAME[base]}"]
            for w in range(5):
                res = score[(base, w)]
                best = max(v[0] for v in res.values())
                tops = sorted(p for p, v in res.items() if abs(v[0] - best) < 1e-9)
                row.append(f"{' / '.join(pname(p) for p in tops[:3])} ({best:.2f})")
            cells.append(row)
        self.tables["best-lure-color"] = md_table(["基準色"] + WEATHER, cells)

        rows = []
        for w in range(5):
            row = [WEATHER[w]] + [(f"{p * 100:.1f}" if p else "-") for p in self.shift[w]]
            rows.append(row)
        self.tables["color-shift"] = md_table(["天気"] + [f"+{i}" for i in range(7)], rows,
                                              ["---"] + ["--:"] * 7)
        out = [[WEATHER[w], s, f"{p:.4f}"] for w in range(5) for s, p in enumerate(self.shift[w]) if p]
        write_csv("color_shift.csv", ["weather", "shift", "probability"], out)

        examples = []
        for c in range(1, 13):
            first = [l for l in self.lures if l.color1 == c]
            names = []
            for l in first:
                if l.name not in names:
                    names.append(l.name)
            examples.append([c, COLOR_NAME[c], len(first), "、".join(names[:5])])
        self.tables["color-names"] = md_table(["番号", "目安の色", "1色目の本数", "ルアーの例"], examples,
                                              ["--:", "---", "--:", "---"])

        rows = []
        for m in range(3):
            ls = [l for l in self.lures if l.mechanism == m]
            fams = []
            for l in ls:
                fam = l.name.split(" ")[0]
                if fam not in fams:
                    fams.append(fam)
            n = sum(1 for f in self.fish if f.mechanism == m and f.id not in self.never)
            rows.append([MECHANISM[m], len(ls), n, "、".join(fams)])
        self.tables["mechanism"] = md_table(["アピールの種類", "ルアーの数", "好む魚の数", "ルアー"], rows,
                                            ["---", "--:", "--:", "---"])

    # --- エサ ---------------------------------------------------------------
    def build_bait(self) -> None:
        aff = self.g.bait_affinity()
        mult = self.g.bait_multiplier_table()
        adj_table = self.g.bait_adjust_table()
        write_csv("baits.csv", ["bait_id", "name", "size", "appeal_cap_m", "appeal_rate_per_sec", "price"],
                  [[b.id, b.name, "レギュラー" if b.size_mask == 3 else "ラージ", b.appeal_cap, b.appeal_rate,
                    b.price if b.price > 0 else ""] for b in self.baits])

        def value(v: int, adjust: int) -> float:
            if v < 0 or v >= 6:
                return 0.0
            return mult[max(0, min(5, v + adj_table[6 + adjust]))]

        rows = [[g, p, b.id, b.name, aff[g][p][b.id], value(aff[g][p][b.id], 0)]
                for g in range(18) for p in range(3) for b in self.baits if aff[g][p][b.id] >= 0]
        write_csv("bait_affinity.csv", ["bait_group", "pattern", "bait_id", "bait", "value", "multiplier"], rows)

        rows = []
        for g in range(18):
            for w in range(5):
                for b in self.baits:
                    if all(aff[g][p][b.id] < 0 for p in range(3)):
                        continue
                    e = [sum(self.pattern[w][p] * value(aff[g][p][b.id], a) for p in range(3))
                         for a in (1, 0, -1)]
                    rows.append([g, WEATHER[w], b.id, b.name, *[f"{x:.3f}" for x in e]])
        write_csv("bait_by_weather.csv", ["bait_group", "weather", "bait_id", "bait", "multiplier_adjust_plus1",
                                          "multiplier_adjust_0", "multiplier_adjust_minus"], rows)

        rows = [[WEATHER[w]] + [f"{p * 100:.1f}" for p in self.pattern[w]] for w in range(5)]
        self.tables["bait-pattern"] = md_table(["天気", "パターン0", "パターン1", "パターン2"], rows,
                                               ["---", "--:", "--:", "--:"])

        rows = []
        for b in self.baits:
            sec = b.appeal_cap / b.appeal_rate
            rows.append([b.name, "S・M" if b.size_mask == 3 else "L・LL", f"{b.appeal_cap:g}",
                         f"{b.appeal_rate:g}", f"{sec:.1f}", f"{b.price:,}" if b.price > 0 else "非売品"])
        adj_rows = []
        for area in FREE_AREAS:
            cnt: dict[int, list[int]] = defaultdict(list)
            for s, sp in self.spots[area].items():
                if s in self.free[area] and sp.has_rect and max(sp.caps) > 0:
                    cnt[sp.bait_adjust].append(s)
            if len(cnt) == 1:
                text = f"{next(iter(cnt)):+d}".replace("+0", "0")
            else:
                text = "、".join(f"{a:+d}: {compress(v)}".replace("+0:", "0:") for a, v in sorted(cnt.items()))
            adj_rows.append([AREA_NAME[area], text])
        self.tables["bait-adjust"] = md_table(["エリア", "補正 (スポットで分かれるエリアはスポット番号つき)"], adj_rows)
        self.tables["bait-list"] = md_table(["エサ", "対象", "最大射程(m)", "増え方(m/s)", "上限までにかかる秒数", "価格pt"], rows,
                                            ["---", "---", "--:", "--:", "--:", "--:"])

        aji = next(f for f in self.fish if self.name(f.id) == "アジ")
        rows = [[b.name] + [f"{value(aff[aji.bait_group][p][b.id], 0):g}" for p in range(3)]
                for b in self.baits if aff[aji.bait_group][0][b.id] >= 0]
        self.tables["bait-example"] = md_table(["エサ", "パターン0", "パターン1", "パターン2"], rows,
                                               ["---", "--:", "--:", "--:"])

    # --- トローリング ---------------------------------------------------------
    def build_trolling(self) -> None:
        hit = self.g.troll_hit_table()
        rows = [[i + 1, TROLL_LURE[i].split(" ")[1]] + [f"{hit[i][c]:g}" for c in range(1, 13)] for i in range(5)]
        write_csv("trolling_lure_color.csv", ["lure", "look"] + [f"color{c}" for c in range(1, 13)], rows)
        self.tables["troll-lure-color"] = md_table(
            ["ルアー"] + [f"色{c}" for c in range(1, 13)],
            [[TROLL_LURE[i]] + [(f"**{hit[i][c] * 100:.0f}**" if hit[i][c] >= 0.3 else f"{hit[i][c] * 100:.0f}")
                                for c in range(1, 13)] for i in range(5)],
            ["---"] + ["--:"] * 12)

        fish_rows, sum_rows = [], []
        for g in range(10):
            entries = self.troll[g]
            for e in entries:
                assert len(set(e.p)) == 1
            for state, disabled in (("locked", self.never | self.stock), ("unlocked", self.never)):
                cand: dict[int, int] = defaultdict(int)
                for e in entries:
                    if e.p[0] > 0 and e.fish not in disabled:
                        cand[e.fish] += e.p[0]
                total = sum(cand.values())
                for k in range(5):
                    per = {f: w / total * hit[k][self.by_id[f].base_color] for f, w in cand.items()}
                    p = sum(per.values())
                    sum_rows.append([g, SEA_NAME[g], state, k + 1, f"{p:.4f}", f"{ROD_CHECK_SEC / p:.1f}",
                                     f"{ROD_CHECK_SEC / p / 5:.1f}"])
                    for f, w in sorted(cand.items(), key=lambda kv: -per[kv[0]]):
                        fish_rows.append([g, state, k + 1, f, self.name(f), w, f"{w / total:.4f}",
                                          f"{hit[k][self.by_id[f].base_color]:g}", f"{per[f]:.4f}",
                                          f"{per[f] / p:.4f}"])
        write_csv("trolling_route_summary.csv", ["route", "sea", "stock_state", "lure", "hit_per_check",
                                                 "sec_per_bite_1rod", "sec_per_bite_5rods"], sum_rows)
        write_csv("trolling_route_fish.csv", ["route", "stock_state", "lure", "fish_id", "fish", "weight",
                                              "pick_rate", "hit_rate", "per_check", "share_of_hits"], fish_rows)
        paths = self.g.troll_paths()
        write_csv("trolling_routes.csv", ["route", "index", "x", "z"],
                  [[r, i, round(x, 1), round(z, 1)] for r, pts in enumerate(paths) for i, (x, z) in enumerate(pts)])

    # --- 体長とランク -----------------------------------------------------------
    def build_size(self) -> None:
        weights = self.g.size_band_weights()
        classes = [band_probs(w) for w in weights]
        exp = self.g.title_exp()
        titles = [self.text[450 + i].replace("\u3000", "") for i in range(33)]
        groups = []
        for r in range(5):
            lv = [i for i in range(33) if min(i // ODDS_ROW, 4) == r]
            groups.append(f"{titles[lv[0]]}〜{titles[lv[-1]]}" if r < 4 else f"{titles[lv[0]]}以上")
        labels = ["1.25〜1.30倍 (S)", "1.20〜1.25倍 (A)", "1.10〜1.20倍 (B)", "1.00〜1.10倍 (C)",
                  "0.90〜1.00倍 (D)", "0.85〜0.90倍 (E)"]
        self.tables["size-band-odds"] = md_table(
            ["サイズ帯 (基準サイズ比)"] + groups,
            [[labels[b]] + [pct(classes[r][b]) for r in range(5)] for b in range(6)],
            ["---"] + ["--:"] * 5)
        rows = [[i, titles[i], f"{exp[i]:,}", min(i // ODDS_ROW, 4) + 1] for i in range(33)]
        self.tables["title-table"] = md_table(["レベル", "クラス", "累計経験値", "サイズ帯の表の列"], rows,
                                              ["--:", "---", "--:", "--:"])
        write_csv("titles.csv", ["level", "title", "exp_required", "odds_column"],
                  [[i, titles[i], exp[i], min(i // ODDS_ROW, 4) + 1] for i in range(33)])
        write_csv("size_band_odds.csv", ["odds_column", "first_title"] + [f"band_{r}_pct" for r in RANKS],
                  [[r + 1, groups[r].split("〜")[0].replace("以上", "")] + [pct(classes[r][b], 2) for b in range(6)]
                   for r in range(5)])
        rows, same = [], 0
        for f in self.fish:
            if f.base_cm <= 0:
                continue
            b = rank_borders(f)
            lo = band_ranges(f)[5][0] / 100
            hi = band_ranges(f)[0][1] / 100
            pr0 = rank_probs(f, classes[0])
            pr4 = rank_probs(f, classes[4])
            same += b["result"][0] == b["dex"][0]
            rows.append([f.id, f.name, f.base_cm, lo, hi, *b["result"], *b["dex"],
                         f"{pr0[0] * 100:.2f}", f"{pr4[0] * 100:.2f}"])
        write_csv("size_ranks.csv", ["fish_id", "name", "base_cm", "min_cm", "max_cm",
                                     *[f"result_{r}_cm" for r in "SABCD"], *[f"dex_{r}_cm" for r in "SABCD"],
                                     "s_pct_first_column", "s_pct_last_column"], rows)
        self.tables["size-diff"] = f"{len(rows)}件のうち{len(rows) - same}件で、Sの境目が0.01cm違う。"

    # --- グレード --------------------------------------------------------------
    def build_grade(self) -> None:
        wait1, wait2 = self.g.wait_seconds()
        coef = self.g.nibble_grade_coef()
        run = self.g.run_distance()
        radar = self.g.radar_seconds()
        rows = []
        for gr in range(6):
            fs = [f for f in self.fish if f.grade == gr and f.id not in self.never]
            exps = sorted({f.exp for f in fs})
            rows.append([gr, len(fs), "・".join(str(e) for e in exps),
                         f"{wait1[gr][0]}〜{wait1[gr][1]}", f"{wait2[gr][0]}〜{wait2[gr][1]}",
                         f"{coef[gr]:g}", f"{5 * coef[gr]:g}〜{15 * coef[gr]:g}", f"{run[gr]:g}"])
        self.tables["grade-table"] = md_table(
            ["グレード", "魚の数", "経験値", "ウキへ向かうまでの時間(秒)", "ウキの下にいる時間(秒)", "つつく時間の係数", "つつく時間(秒)", "逃げる距離m"],
            rows, ["--:", "--:", "--:", ":-:", ":-:", "--:", ":-:", "--:"])
        self.tables["wait-table"] = md_table(
            ["グレード", "ウキへ向かうまでの時間", "ウキの下にいる時間", "つつく時間"],
            [[r[0], r[3], r[4], r[6]] for r in rows], ["--:", ":-:", ":-:", ":-:"])
        self.tables["radar-table"] = md_table(
            ["グレード"] + [str(g) for g in range(2, 6)],
            [["表示時間(秒)"] + [f"{radar[g][0]}〜{radar[g][1]}" for g in range(2, 6)]], ["---"] + [":-:"] * 4)
        rc = self.g.nibble_rank_coef()
        self.tables["nibble-rank"] = md_table(["ランク"] + list(RANKS), [["係数"] + [f"{v:g}" for v in rc]],
                                              ["---"] + ["--:"] * 6)
        sec = self.g.nibble_bait_seconds()
        self.tables["nibble-bait"] = md_table(["補正後の相性の値"] + [str(i) for i in range(6)],
                                              [["足される秒数"] + [f"{v:g}" for v in sec]], ["---"] + ["--:"] * 6)

    # --- 竿とリール -----------------------------------------------------------
    def build_tackle(self) -> None:
        bands = self.g.size_gate_bands()
        ranges = [(0, 30), (20, 70), (50, 200), (150, None)]

        def mask_text(mask: int) -> str:
            on = [ranges[i] for i in range(4) if mask >> i & 1]
            lo = min(a for a, _ in on)
            hi = None if any(b is None for _, b in on) else max(b for _, b in on)
            return size_text(lo, hi)

        r1, r2 = self.g.reel_coef()
        rows, csv_rows = [], []
        for r in self.rods:
            stars = 3 if r.tension_max >= 1000 else 2 if r.tension_max >= 500 else 1
            cast = CAST_RATE.get(r.cast_step)
            csv_rows.append([r.id, r.name, stars, mask_text(r.size_mask), r.tension_max, cast or "", r.price])
            if r.id <= 8:
                rows.append([r.name, stars, mask_text(r.size_mask), r.tension_max, f"{cast:g}",
                             f"{r.price:,}" if r.price else "非売品" if r.id == 8 else "初期装備"])
        write_csv("rods.csv", ["rod_id", "name", "stars", "size_cm", "tension_max", "cast_rate", "price"], csv_rows)
        self.tables["rod-table"] = md_table(["竿", "星", "対象cm", "ゲージの最大値", "投げる倍率", "価格pt"], rows,
                                            ["---", "--:", ":-:", "--:", "--:", "--:"])
        rows, csv_rows = [], []
        for r in self.reels:
            csv_rows.append([r.id, r.name, r.step + 1, mask_text(r.size_mask), r1[r.step], r2[r.step], r.price])
            if r.id <= 6:
                rows.append([r.name, r.step + 1, mask_text(r.size_mask), f"{r1[r.step]:g}", f"{r2[r.step]:g}",
                             f"{r.price:,}" if r.price else "非売品" if r.id == 6 else "初期装備"])
        write_csv("reels.csv", ["reel_id", "name", "stars", "size_cm", "to_center", "from_center", "price"], csv_rows)
        self.tables["reel-table"] = md_table(["リール", "星", "対象cm", "50%へ戻る倍率", "50%から離れる倍率", "価格pt"], rows,
                                             ["---", "--:", ":-:", "--:", "--:", "--:"])

        over = self.g.over_size_table()

        def over_size(mask: int, length: float) -> int:
            on = [i for i in range(4) if mask >> i & 1]
            low, high = on[0], on[-1]
            if length < ranges[high][0] or length <= ranges[low][1]:
                return 1
            n = 0
            for i in range(low + 1, 4):
                n += 1
                if ranges[i][1] is None or length <= ranges[i][1]:
                    break
            return over[n - 1]

        samples = [25, 50, 100, 250]
        names = {0: "LF", 3: "MF", 5: "HF", 7: "X"}
        self.tables["rod-over"] = md_table(
            ["竿", "30cm以下", "30〜70cm", "70〜200cm", "200cm超"],
            [[n] + [f"{over_size(self.rods[i].size_mask, x)}倍" for x in samples] for i, n in names.items()],
            ["---"] + ["--:"] * 4)

        fit = self.g.reel_fit_table()

        def reel_fit(reel, fish_band: int) -> float:
            low = next(i for i in range(4) if reel.size_mask >> i & 1)
            return fit[fish_band - low + 3]

        groups = {"FR (ジャーニー・ステージ・オメガ)": 0, "M (ハンター・ランカーホルダー)": 3, "X (エレファント・インフィニティ)": 5}
        self.tables["reel-fit"] = md_table(
            ["リール", "30cm以下", "30〜70cm", "70〜200cm", "200cm超"],
            [[n] + [f"{reel_fit(self.reels[i], b):g}倍" for b in range(4)] for n, i in groups.items()],
            ["---"] + ["--:"] * 4)

        lure_masks = sorted({l.size_mask for l in self.lures},
                            key=lambda m: (min(i for i in range(4) if m >> i & 1), max(i for i in range(4) if m >> i & 1)))
        rows = []
        for i, n in names.items():
            rod = self.rods[i]
            rs = [r.name.split(" ")[1] for r in self.reels[:7] if r.size_mask & rod.size_mask]
            bait = "レギュラー" if rod.size_mask & 3 else "ラージ"
            ls = [SIZE_LABEL[m] for m in lure_masks if m & rod.size_mask]
            rows.append([n, "・".join(rs), bait, "、".join(ls)])
        self.tables["tackle-combo"] = md_table(["竿", "組めるリール", "エサ", "ルアーの対象cm"], rows)

    # --- ファイト -------------------------------------------------------------
    def build_fight(self) -> None:
        rows = []
        live = [f for f in self.fish if f.id not in self.never and f.id not in JUNK]
        for c, (a, b) in enumerate(self.pulls):
            fs = sorted([f for f in live if f.pull_class == c], key=lambda f: f.points)
            ex = "、".join(f.name for f in fs[-4:]) if fs else "-"
            rows.append([c, f"{a:g}", f"{b:g}", len(fs), ex])
        self.tables["pull-table"] = md_table(["区分", "速さA", "速さB", "魚の数", "例"], rows,
                                             ["--:", "--:", "--:", "--:", "---"])
        top = sorted(live, key=lambda f: -f.stamina)[:12]
        self.tables["stamina-top"] = "、".join(f"{f.name} {f.stamina:g}" for f in top)

    # --- 天気 ----------------------------------------------------------------
    def build_weather(self) -> None:
        w = self.g.weather_weights()
        n = list(w)
        n[0] += 1  # r を 0 から数えて ≤ で区切るので、先頭が1目多い
        total = sum(n)
        self.tables["weather-odds"] = md_table(WEATHER, [[f"{x / total * 100:.1f}%" for x in n]], ["--:"] * 5)
        rows = []
        for j in range(5):
            rows.append([WEATHER[j]] + [("-" if k == j else f"{n[k] / (total - n[j]) * 100:.1f}") for k in range(5)])
        self.tables["weather-next"] = md_table(["前の日 \\ 次の日"] + WEATHER, rows, ["---"] + ["--:"] * 5)
        write_csv("weather_next.csv", ["previous"] + WEATHER,
                  [[WEATHER[j]] + [("" if k == j else f"{n[k] / (total - n[j]):.4f}") for k in range(5)] for j in range(5)])
        early = n[:2] + [71 - sum(n[:2])]
        self.tables["weather-early"] = md_table(WEATHER[:3], [[f"{x / 71 * 100:.1f}%" for x in early]], ["--:"] * 3)
        self.tables["flare-table"] = md_table(WEATHER, [[f"{v * 100:.0f}%" for v in self.g.flare_table()]], ["--:"] * 5)

    # --- 魚とルアーの組 --------------------------------------------------------
    def build_fit(self, areas_of: dict[int, set[str]]) -> None:
        gate = self.g.size_gate_bands()
        classes = sorted({(l.type_index, l.size_range) for l in self.lures},
                         key=lambda c: (c[0], c[1][0], c[1][1] or 9999))
        rows, s_rows = [], []
        for f in self.fish:
            if f.id in self.never or f.gate_class == 3 or f.lure_mask == 0 or f.base_cm <= 0:
                continue
            if f.id not in areas_of:  # トローリング専用と展示専用の魚は、設定があってもルアーで釣れない
                continue
            kmin = band_ranges(f)[5][0]
            kmax = band_ranges(f)[0][1]
            for t, (lo, hi) in classes:
                if not f.lure_mask >> t & 1:
                    continue
                lo_k = lo * 100
                hi_k = hi * 100 if hi else 10 ** 7
                if lo_k > kmax or hi_k < kmin:
                    continue
                full = lo_k <= kmin and kmax <= hi_k
                rows.append([f.id, f.name, LURE_TYPES[t], lo, hi or "", "all" if full else "part"])
            lad = rank_ladder(f)
            for l in self.lures:
                if not f.lure_mask >> l.type_index & 1:
                    continue
                lo, hi = l.size_range
                ks = range(max(kmin, lo * 100 - 2), kmin + (kmax - kmin) + 1)
                first = next((k for k in ks if size_gate(size_from_100(k), l.size_mask, gate)), None)
                if first is None or first == kmin:
                    continue
                if rank_result(size_from_100(first), lad) == 0:
                    s_rows.append([f.id, f.name, l.id, l.name, first / 100, kmax / 100])
        groups: dict[tuple[int, ...], list] = defaultdict(list)
        for f in self.fish:
            if f.id in self.never or f.id in JUNK or f.gate_class == 3 or f.lure_mask == 0 or f.id not in areas_of:
                continue
            groups[tuple(t for t in range(5) if f.lure_mask >> t & 1)].append(f)
        self.tables["lure-type-groups"] = md_table(
            ["反応する種類", "魚の数", "例"],
            [["全種類" if len(k) == 5 else "と".join(LURE_SHORT[LURE_TYPES[t]] for t in k) + ("だけ" if len(k) == 1 else ""),
              len(v), "、".join(x.name for x in sorted(v, key=lambda x: -x.points)[:4])]
             for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))],
            ["---", "--:", "---"])
        write_csv("fish_lure_types.csv", ["fish_id", "fish", "type", "size_min_cm", "size_max_cm", "coverage"], rows)
        write_csv("s_only_lures.csv", ["fish_id", "fish", "lure_id", "lure", "pass_min_cm", "pass_max_cm"], s_rows)

    # --- 受付嬢の話題 ----------------------------------------------------------
    def build_reception(self) -> None:
        topics = [("掲示板の目標の魚がいる", "目標の魚", 0x804F7474, 5, 0),
                  ("グレード4以上の魚がいる (ゴミ以外)", "グレードが最も高い魚。同じなら後に釣った魚", 0x804F7488, 5, 0),
                  ("10匹以上 (ゴミも数える)", "-", 0x804F749C, 5, 0),
                  ("Sランクの魚がいる (ゴミ以外)", "最後に釣ったSの魚", 0x804F74B0, 8, 0),
                  ("Eランクの魚がいる (ゴミ以外)", "最後に釣ったEの魚", 0x804F74D0, 3, 0),
                  ("キレイな魚がいる", "最後に釣ったキレイな魚", 0x804F74DC, 5, 1),
                  ("カワイイ魚がいる", "最後に釣ったカワイイ魚", 0x804F74F0, 5, 0),
                  ("3匹以下", "-", 0x804F7504, 3, 0),
                  ("それ以外", "-", 0x804F7510, 5, 0)]

        def first_line(i: int) -> str:
            s = re.sub(r".！ǿ", "", self.text[i]).replace("%ls", "○○")
            return re.split(r"\\r|\\n", s)[0].strip()

        rows = []
        for n, (cond, who, addr, count, pick) in enumerate(topics, 1):
            ids = self.g.reception_topic(addr, count)
            rows.append([n, cond, who, count, first_line(ids[pick][0])])
        self.tables["reception-topics"] = md_table(["順", "条件", "話題に出る魚", "セリフの数", "セリフの例"], rows,
                                                   ["--:", "---", "---", "--:", "---"])
        pretty, cute = self.g.reception_fish()
        assert not set(pretty) & set(cute)
        self.tables["reception-fish"] = md_table(
            ["話題", "魚"], [["キレイ", "、".join(self.name(i) for i in pretty)],
                             ["カワイイ", "、".join(self.name(i) for i in cute)]])
        self.tables["reception-never"] = "、".join(
            self.name(i) for i in pretty + cute if self.by_id[i].grade >= 4)

    # --- 予定表 ----------------------------------------------------------------
    def build_calendar(self) -> None:
        def clean(i: int) -> str:
            return re.sub(r"[\x00-\x1f]", "", re.sub(r".！ǿ", "", self.text[i])).replace("\u3000", " ").strip()

        def week(mask: int, k: int) -> str:
            b = mask >> (7 * k) & 0x7F
            return "毎日" if b == 0x7F else "".join(WEEKDAY[i] for i in range(7) if b >> i & 1) or "-"

        act = self.g.activities()
        full = (1 << 28) - 1
        rows, contests, csv_rows = [], [], []
        for a in act:
            name = clean(a.name_id).strip()
            area = AREA_NAME.get(AREA_ORDER[a.area], "") if a.area < len(AREA_ORDER) else ""
            weeks = [week(a.days, k) for k in range(4)]
            csv_rows.append([name, area, a.price, int(a.contest), *weeks])
            if a.contest:
                d = unicodedata.normalize("NFKC", clean(a.desc_id))
                style = re.search(r"【スタイル】(.+?)\\n", d).group(1)
                rule = re.search(r"【ルール】(.+?)\\n", d).group(1)
                prize = re.search(r"【優勝特典】(\d+)", d).group(1)
                days = [k for k in range(28) if a.days >> k & 1]
                assert len(days) == 2 and days[1] - days[0] == 14
                when = f"第{days[0] // 7 + 1}・{days[1] // 7 + 1}週の{WEEKDAY[days[0] % 7]}曜"
                contests.append((days[0], [when, name, style, rule, f"{int(prize):,}", a.price]))
            elif a.days != full:
                rows.append([name, area, f"{a.price:,}"] + weeks)
        write_csv("activities.csv", ["name", "area", "price", "contest", "week1", "week2", "week3", "week4"], csv_rows)
        contests.sort(key=lambda c: (c[0] % 14, c[1][1]))
        self.tables["contest-table"] = md_table(["開催日", "大会", "スタイル", "ルール", "優勝特典pt", "参加費pt"],
                                                [c[1] for c in contests], ["---", "---", "---", "---", "--:", "--:"])
        self.tables["activity-table"] = md_table(["アクティビティ", "エリア", "料金pt", "第1週", "第2週", "第3週", "第4週"], rows,
                                                 ["---", "---", "--:", "---", "---", "---", "---"])

    # --- 掲示板の目標 ------------------------------------------------------------
    def build_board(self) -> None:
        rows = []
        for area, pid, fid in self.g.board_targets():
            nm = re.sub(r"[\x00-\x1f]", "", self.text[pid]).strip()
            a = AREA_NAME.get(AREA_ORDER[area], "") if area < len(AREA_ORDER) else ""
            rows.append([a, nm, fid, self.name(fid)])
        write_csv("board_targets.csv", ["area", "place", "fish_id", "fish"], rows)

    # --- スポットの広さと魚の数 --------------------------------------------------
    def build_density(self) -> None:
        spots = [r for r in self.spot_rows if r[0] != "Offshore"]
        edges = [(0, 100), (100, 400), (400, 1600), (1600, 6400), (6400, 10 ** 9)]
        rows = []
        for lo, hi in edges:
            fs = [(r[8], max(r[9:13])) for r in spots if lo <= r[8] < hi]
            label = f"{lo:,}〜{hi:,}" if hi < 10 ** 9 else f"{lo:,}以上"
            med = statistics.median(c for _, c in fs)
            dens = statistics.median(c / a * 1000 for a, c in fs if a > 0)
            rows.append([label, len(fs), f"{med:g}", f"{dens:.1f}"])
        self.tables["spot-density"] = md_table(["面積 m²", "スポット数", "上限の中央値", "1,000m²あたりの上限"], rows,
                                               ["---", "--:", "--:", "--:"])

    def build_conditions(self) -> None:
        rows = [[u.quest, self.name(f), u.step] for f, u in self.unlocks.items() if u.step]
        write_csv("quest_unlocks.csv", ["quest", "fish", "step"], rows)
        self.tables["stock-fish"] = "、".join(self.name(f) for f in self.g.stock_table())

    def fill_docs(self) -> None:
        pat = re.compile(r"(<!-- table:([\w-]+) -->\n).*?(<!-- /table -->)", re.S)
        pages = [*DOCS.glob("*.md"), ROOT / "README.md",
                 DATA / "README.md", ROOT / "tools/README.md"]
        for path in pages:
            if not path.exists():
                continue
            s = path.read_text(encoding="utf-8")

            def repl(m):
                return m.group(1) + self.tables[m.group(2)] + "\n" + m.group(3)

            new = pat.sub(repl, s)
            if new != s:
                path.write_text(new, encoding="utf-8")

    def run(self) -> None:
        DATA.mkdir(exist_ok=True)
        areas_of = self.build_spawn()
        self.build_offshore(areas_of)
        write_csv("spots.csv", ["area", "area_name", "spot", "x", "z", "width_m", "depth_m", "rot_deg", "area_m2",
                                "cap_morning", "cap_day", "cap_evening", "cap_night", "refill_sec", "bait_adjust"],
                  self.spot_rows)
        write_csv("spawn_rates.csv", ["area", "area_name", "spot", "fish_id", "fish", "weight", "pct_early",
                                      "pct_standard", "pct_all_unlocked", "unlock"], self.rate_rows)
        self.build_trolling()
        self.build_fish(areas_of)
        self.build_lure()
        self.build_bait()
        self.build_conditions()
        self.build_size()
        self.build_grade()
        self.build_tackle()
        self.build_fight()
        self.build_weather()
        self.build_fit(areas_of)
        self.build_density()
        self.build_reception()
        self.build_calendar()
        self.build_board()
        self.fill_docs()

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, required=True, help="ゲームのファイルの展開先")
    Builder(ap.parse_args().game).run()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
