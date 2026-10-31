"""水深が湧き確率に与える影響を計算し、スポットの水深を data/spot_depth.csv に出す.

    python3 tools/depth_effect.py --game <展開先>

ゲームは湧く位置の水深が体長の4分の1より浅いと湧くのをやめる。地形は当たり判定の三角形で、
水面はスポットの高さを使う。各スポットの長方形を格子で調べ、魚ごとに湧ける位置の割合 a を求め、
確率を 重み × a に比例するものとして計算し直す。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from build_maps import stage_tris
from gamedata import AREA_NAME, AREA_ORDER, EXHIBIT, FREE_AREAS, MISSING, Game, band_probs, band_ranges

ROOT = Path(__file__).resolve().parents[1]


def top_heights(tris: np.ndarray, px: np.ndarray, pz: np.ndarray, ymax: float) -> np.ndarray:
    """各点で、高さ ymax 以下で最も高い三角形の高さ。なければ -inf."""
    out = np.full(px.shape, -np.inf)
    xs, zs = tris[:, [0, 3, 6]], tris[:, [2, 5, 8]]
    near = (xs.max(1) >= px.min()) & (xs.min(1) <= px.max()) & (zs.max(1) >= pz.min()) & (zs.min(1) <= pz.max())
    for x0, y0, z0, x1, y1, z1, x2, y2, z2 in tris[near]:
        det = (z1 - z2) * (x0 - x2) + (x2 - x1) * (z0 - z2)
        if abs(det) < 1e-9:
            continue
        m = (px >= min(x0, x1, x2)) & (px <= max(x0, x1, x2)) & (pz >= min(z0, z1, z2)) & (pz <= max(z0, z1, z2))
        if not m.any():
            continue
        a = ((z1 - z2) * (px[m] - x2) + (x2 - x1) * (pz[m] - z2)) / det
        b = ((z2 - z0) * (px[m] - x2) + (x0 - x2) * (pz[m] - z2)) / det
        c = 1 - a - b
        h = a * y0 + b * y1 + c * y2
        h = np.where((a >= -1e-6) & (b >= -1e-6) & (c >= -1e-6) & (h <= ymax), h, -np.inf)
        idx = np.where(m)[0]
        out[idx] = np.maximum(out[idx], h)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, required=True, help="ゲームのファイルの展開先")
    g = Game(ap.parse_args().game)
    fish = {f.id: f for f in g.fish()}
    spots = g.spots()
    skip = EXHIBIT | MISSING | set(g.stock_table())
    classes = band_probs(g.size_band_weights()[2])
    rows, changes = [], []
    for area in FREE_AREAS:
        tris = stage_tris(g, AREA_ORDER.index(area) + 1)
        for s, entries in sorted(g.free_table(area).items()):
            sp = spots[area][s]
            if not (sp.has_rect and max(sp.caps) > 0):
                continue
            n = max(8, min(40, int(max(sp.sx, sp.sz))))
            u = (np.arange(n) + 0.5) / n * 2 - 1
            gx, gz = np.meshgrid(u, u)
            dx, dz = (gx * sp.sx).ravel(), (gz * sp.sz).ravel()
            th = np.radians(sp.rot)
            px = sp.x + np.cos(th) * dx + np.sin(th) * dz
            pz = sp.z - np.sin(th) * dx + np.cos(th) * dz
            depth = sp.y - top_heights(tris, px, pz, sp.y + 10)
            water = depth > 0
            finite = water & np.isfinite(depth)
            rows.append([area, AREA_NAME[area], s, f"{np.median(depth[finite]) if finite.any() else 0:.2f}",
                         f"{(~water).mean() * 100:.1f}"])
            weight: dict[int, int] = {}
            for e in entries:
                if e.p[0] > 0 and e.fish not in skip:
                    weight[e.fish] = weight.get(e.fish, 0) + e.p[0]
            total = sum(weight.values())
            if not total:
                continue
            fit = {}
            for f, w in weight.items():
                sizes = [((lo + hi) / 2e4, classes[c]) for c, (lo, hi) in enumerate(band_ranges(fish[f]))]
                fit[f] = sum(q * (depth >= 0.25 * size).mean() for size, q in sizes)
            scale = sum(w * fit[f] for f, w in weight.items())
            for f, w in weight.items():
                changes.append(abs(w * fit[f] / scale - w / total) * 100 if scale else 0.0)
    with (ROOT / "data/spot_depth.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["area", "area_name", "spot", "median_depth_m", "not_water_pct"])
        w.writerows(rows)
    print(f"{len(changes)}行、1ポイント以上の変化 {sum(c >= 1 for c in changes)}行、最大 {max(changes):.1f}ポイント")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
