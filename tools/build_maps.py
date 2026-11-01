"""サイトの地図の土台と、トローリングの地図を描く.

    python3 tools/build_maps.py --game <展開先>

地形はステージの当たり判定 (FieldCollision) の三角形をそのまま塗ったもので、ゲームの画像は
使っていない。枠の回転はゲームの行列 (Y軸回転) どおりに頂点を計算して描く。
地図の向きは TURN でエリアごとに決める。
"""

from __future__ import annotations

import argparse
import csv
import struct
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D
from PIL import Image, ImageDraw

from gamedata import AREA_NAME, AREA_ORDER, FREE_AREAS, Game, Spot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "images"
plt.rcParams["font.family"] = ["Noto Sans CJK JP", "DejaVu Sans"]

LAND = "#e6dcc3"
WATER = "#cfe4f2"
ISLAND = "#c9b58a"
SEA_X0, SEA_X1, SEA_PX = -3010.0, 2310.0, 1100
BASE_LONG_PX, BASE_DPI = 1100, 100
# 時計回りの角度。書いていないエリアは右が -x、上が +z の向きである
TURN = {
    "Beach": 180, "RiverA": 180, "LakeA": 180, "RiverB": 180, "Bluecave": 180, "LakeB": 180, "BeachB": 180,
    "IslandA": 180, "Submap01": 180, "Submap03": 180, "Submap04": 180, "JungleB": 90,
}
# 角度ごとの (右, 上) の、世界の (x, z) に掛ける係数。外海だけはゲームの世界地図の向きである
VIEW = {0: ((-1, 0), (0, 1)), 180: ((1, 0), (0, -1)), 90: ((0, 1), (1, 0))}
SEA_TURN = 180
ROUTE_COLOR = ["#e6194b", "#f58231", "#808000", "#3cb44b", "#008080", "#4363d8", "#911eb4", "#f032e6", "#7f4f24", "#000075"]


def load_tris(path: Path) -> np.ndarray:
    """三角形の頂点 (n, 9)。形式の裏付けはブロック長の一致で確かめる."""
    d = path.read_bytes()
    table = struct.unpack(">I", d[0x34:0x38])[0]
    end = struct.unpack(">I", d[0x38:0x3C])[0]
    offs, p, prev = [], table, 0
    while p + 4 <= end:
        v = struct.unpack(">I", d[p:p + 4])[0]
        if v <= prev or v >= len(d):
            break
        offs.append(v)
        prev = v
        p += 4
    out = []
    for i, off in enumerate(offs):
        stop = offs[i + 1] if i + 1 < len(offs) else end
        n = struct.unpack(">I", d[off:off + 4])[0] >> 16
        if stop - off != 60 + 72 * n:
            continue
        for t in range(n):
            out.append(struct.unpack_from(">9f", d, off + 60 + t * 72))
    return np.array(out, dtype=float).reshape(-1, 9)


def stage_tris(game: Game, stage: int) -> np.ndarray:
    base = game.stage / f"em{stage:02d}/FieldCollision"
    parts = [load_tris(p) for p in sorted(base.glob("*.fcd"))]
    parts = [p for p in parts if len(p)]
    return np.concatenate(parts) if parts else np.zeros((0, 9))


def faces(tris: np.ndarray, min_area: float = 0.01) -> np.ndarray:
    xz = tris[:, [0, 2, 3, 5, 6, 8]].reshape(-1, 3, 2)
    a = np.abs((xz[:, 1, 0] - xz[:, 0, 0]) * (xz[:, 2, 1] - xz[:, 0, 1])
               - (xz[:, 2, 0] - xz[:, 0, 0]) * (xz[:, 1, 1] - xz[:, 0, 1])) / 2
    return xz[a > min_area]


def spot_corners(sp: Spot) -> np.ndarray:
    th = np.radians(sp.rot)
    c, s = np.cos(th), np.sin(th)
    local = np.array([[-sp.sx, -sp.sz], [sp.sx, -sp.sz], [sp.sx, sp.sz], [-sp.sx, sp.sz]])
    # MTXRotRad('y') の行列: x' = c x + s z, z' = -s x + c z
    world = np.column_stack((c * local[:, 0] + s * local[:, 1], -s * local[:, 0] + c * local[:, 1]))
    return world + [sp.x, sp.z]


def label(ax, x, y, text, size=8, color="#111", weight="bold", **kw) -> None:
    ax.text(x, y, text, fontsize=size, color=color, weight=weight, ha="center", va="center",
            path_effects=[pe.withStroke(linewidth=2.5, foreground="white")], **kw)


def view(area: str, xz) -> np.ndarray:
    """世界の (x, z) を、地図の (右, 上) にする."""
    xz = np.asarray(xz, dtype=float)
    (a, b), (c, d) = VIEW[TURN.get(area, 0)]
    return np.stack((a * xz[..., 0] + b * xz[..., 1], c * xz[..., 0] + d * xz[..., 1]), axis=-1)


def area_bounds(game: Game, area: str, spots: list[Spot]) -> tuple[np.ndarray, np.ndarray]:
    marks = [(x, z) for _, x, z in game.map_marks(area)]
    corners = view(area, np.concatenate([*(spot_corners(s) for s in spots), np.array(marks).reshape(-1, 2)]))
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    pad = max(25.0, 0.06 * (hi - lo).max())
    return lo - pad, hi + pad


def draw_terrain(ax, area: str, tris: np.ndarray, spots: list[Spot]) -> None:
    level = Counter(round(s.y, 2) for s in spots).most_common(1)[0][0]
    ax.set_facecolor(LAND)
    ymax = tris[:, [1, 4, 7]].max(axis=1)
    ymin = tris[:, [1, 4, 7]].min(axis=1)
    water = tris[ymax <= level + 0.25]
    land = tris[ymin > level + 0.25]
    ax.add_collection(PolyCollection(view(area, faces(water)), facecolors=WATER, edgecolors=WATER, linewidths=0.2, zorder=1))
    ax.add_collection(PolyCollection(view(area, faces(land)), facecolors=LAND, edgecolors=LAND, linewidths=0.2, zorder=2))


def save_base(fig, name: str, turn: int, lo: np.ndarray, hi: np.ndarray) -> list:
    """サイトの地図の土台を保存し、世界の (x, z) から画像の (px, py) への変換の行を返す."""
    (OUT / "base").mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "base" / f"{name}.png", dpi=BASE_DPI)
    plt.close(fig)
    w, h = fig.canvas.get_width_height()
    sx, sy = w / (hi[0] - lo[0]), h / (hi[1] - lo[1])
    (a, b), (c, d) = VIEW[turn]
    return [name, w, h, turn, 1 / sx, a * sx, b * sx, -lo[0] * sx, -c * sy, -d * sy, hi[1] * sy]


def area_base(game: Game, area: str, spots: list[Spot]) -> list:
    """スポットもラベルもない地形だけの地図。スポットはサイトが座標から描く."""
    tris = stage_tris(game, AREA_ORDER.index(area) + 1)
    lo, hi = area_bounds(game, area, spots)
    w, h = hi[0] - lo[0], hi[1] - lo[1]
    scale = BASE_LONG_PX / BASE_DPI / max(w, h)
    fig = plt.figure(figsize=(w * scale, h * scale), dpi=BASE_DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    draw_terrain(ax, area, tris, spots)
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_visible(False)
    return save_base(fig, area, TURN.get(area, 0), lo, hi)


def sea_plain(game: Game) -> list:
    fig = plt.figure(figsize=(BASE_LONG_PX / BASE_DPI, BASE_LONG_PX / BASE_DPI), dpi=BASE_DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    sea_base(game, ax)
    ax.set_aspect("auto")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for side in ax.spines.values():
        side.set_visible(False)
    return save_base(fig, "Offshore", SEA_TURN, np.array([-3100.0, -2400.0]), np.array([2400.0, 3100.0]))


def write_frames(frames: list) -> None:
    with (ROOT / "data/map_frames.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["area", "width_px", "height_px", "turn_deg", "m_per_px", "px_x", "px_z", "px_0", "py_x", "py_z", "py_0"])
        for name, width, height, turn, *rest in frames:
            w.writerow([name, width, height, turn, *(f"{float(v):.6f}" for v in rest)])


def write_marks(rows: list) -> None:
    with (ROOT / "data/map_marks.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["area", "area_name", "kind", "x", "z"])
        w.writerows(rows)


def write_points(rows: list) -> None:
    with (ROOT / "data/fishing_points.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["area", "area_name", "x", "y", "z", "ux", "uz", "vx", "vz", "width_m", "depth_m", "height_m", "front_x", "front_z"])
        w.writerows(rows)


def components(mask: np.ndarray):
    """連結成分を (外周に触れるか, 点の配列) で順に返す."""
    seen = np.zeros(mask.shape, dtype=bool)
    h, w = mask.shape
    for start in zip(*np.nonzero(mask)):
        if seen[start]:
            continue
        stack, cells, edge = [start], [], False
        seen[start] = True
        while stack:
            i, j = stack.pop()
            cells.append((i, j))
            edge = edge or i in (0, h - 1) or j in (0, w - 1)
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < h and 0 <= b < w and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    stack.append((a, b))
        yield edge, np.array(cells)


def grow(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def sea_land_mask(game: Game) -> np.ndarray:
    """外海の陸。本島の海岸線は垂直の壁で囲まれ、一部は当たり判定の面がない穴になっている.

    面積のある陸の面と大きな穴を陸の種にして、壁に囲まれた内側のうち種に接するものを足す。
    種に接しない壁の輪 (海の上の見えない壁) と、ステージの外周の壁は陸にしない。
    """
    t = stage_tris(game, 10)
    top = t[:, [1, 4, 7]].max(axis=1)
    below, land = t[top <= 0.2], t[top > 0.2]
    scale = SEA_PX / (SEA_X1 - SEA_X0)

    def to_px(x: float, z: float) -> tuple[float, float]:
        return (x - SEA_X0) * scale, (z - SEA_X0) * scale

    def raster(tris: np.ndarray, min_area: float = 0.01) -> np.ndarray:
        img = Image.new("L", (SEA_PX, SEA_PX), 0)
        draw = ImageDraw.Draw(img)
        for tri in faces(tris, min_area):
            draw.polygon([to_px(x, z) for x, z in tri], fill=255, outline=255)
        return np.array(img) > 0

    solid = raster(land, 1.0)
    for stage in (11, 12):
        st = stage_tris(game, stage)
        solid |= raster(st[st[:, [1, 4, 7]].max(axis=1) > 0.2], 1.0)
    img = Image.new("L", (SEA_PX, SEA_PX), 0)
    draw = ImageDraw.Draw(img)
    for tri in land[:, [0, 2, 3, 5, 6, 8]].reshape(-1, 3, 2):
        draw.line([to_px(x, z) for x, z in (*tri, tri[0])], fill=255, width=1)
    wall = np.array(img) > 0
    margin = int(60 * scale)
    wall[:margin] = wall[-margin:] = False
    wall[:, :margin] = wall[:, -margin:] = False

    holes = ~(raster(below) | solid | wall)
    island = solid.copy()
    for edge, cells in components(holes):
        if not edge and len(cells) >= 3000 * scale * scale:
            island[cells[:, 0], cells[:, 1]] = True
    near = grow(island)
    for edge, cells in components(~(island | wall)):
        if not edge and near[cells[:, 0], cells[:, 1]].any():
            island[cells[:, 0], cells[:, 1]] = True
    island |= wall & grow(island)
    rgba = np.zeros((SEA_PX, SEA_PX, 4))
    rgba[island] = (*matplotlib.colors.to_rgb(ISLAND), 1.0)
    return rgba


def sea_base(game: Game, ax) -> None:
    """外海の地形。ゲームの世界地図と同じく z を下向きにする."""
    ax.set_facecolor(WATER)
    ax.imshow(sea_land_mask(game), extent=(SEA_X0, SEA_X1, SEA_X1, SEA_X0), zorder=4, interpolation="nearest")
    ax.set_xlim(-3100, 2400)
    ax.set_ylim(2400, -3100)
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    for name, x, z in (("ペナンカパン島", 150, 280), ("スンビラン", -1700, -1450), ("スプール", 1745, 1020)):
        label(ax, x, z, name, size=10, weight="normal", zorder=8)


def route_lines(ax, paths, zorder=5, width=2.0) -> None:
    for r, pts in enumerate(paths):
        xy = np.array(pts + pts[:1])
        ax.plot(xy[:, 0], xy[:, 1], color=ROUTE_COLOR[r], linewidth=width, zorder=zorder)
        tip = np.array(pts)[np.argmin(np.array(pts)[:, 1] if r >= 5 else -np.array(pts)[:, 1])]
        label(ax, tip[0], tip[1], str(r), size=12, color=ROUTE_COLOR[r], zorder=9)


def route_map(game: Game, paths) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 10.2))
    sea_base(game, ax)
    route_lines(ax, paths)
    ax.set_title("トローリングの航路 (ゲームの世界地図と同じ向き)", fontsize=13)
    ax.legend(handles=[Line2D([], [], color=ROUTE_COLOR[r], lw=2.5, label=f"航路{r}") for r in range(10)],
              ncol=5, loc="lower center", bbox_to_anchor=(0.5, -0.13), frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "trolling" / "routes.png", dpi=120)
    plt.close(fig)


def start_map(game: Game, paths) -> None:
    pts = np.array([p for r in paths for p in r])
    ids = np.array([i for i, r in enumerate(paths) for _ in r])
    xs = np.arange(-3100, 2400, 15.0)
    zs = np.arange(-3100, 2400, 15.0)
    gx, gz = np.meshgrid(xs, zs)
    best = np.zeros(gx.shape, dtype=np.int8)
    for row in range(gx.shape[0]):
        dx = gx[row][:, None] - pts[:, 0]
        dz = gz[row][:, None] - pts[:, 1]
        best[row] = ids[np.argmin(dx * dx + dz * dz, axis=1)]
    fig, ax = plt.subplots(figsize=(10.5, 10.2))
    sea_base(game, ax)
    rgb = np.array([matplotlib.colors.to_rgb(c) for c in ROUTE_COLOR])[best]
    ax.imshow(rgb, extent=(xs[0], xs[-1] + 15, zs[-1] + 15, zs[0]), alpha=0.3, zorder=1, interpolation="nearest")
    route_lines(ax, paths, width=1.4)
    ax.set_xlim(-3100, 2400)
    ax.set_ylim(2400, -3100)
    ax.set_title("トローリングを始めた場所と選ばれる航路", fontsize=13)
    ax.legend(handles=[Line2D([], [], color=ROUTE_COLOR[r], lw=6, alpha=0.5, label=f"航路{r}") for r in range(10)],
              ncol=5, loc="lower center", bbox_to_anchor=(0.5, -0.13), frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "trolling" / "start-zones.png", dpi=120)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, required=True, help="ゲームのファイルの展開先")
    ap.add_argument("--areas", default="")
    args = ap.parse_args()
    game = Game(args.game)
    spots = game.spots()
    tables = {a: game.free_table(a) for a in FREE_AREAS}
    wanted = args.areas.split(",") if args.areas else FREE_AREAS
    (OUT / "trolling").mkdir(parents=True, exist_ok=True)
    frames, points, marks = [], [], []
    for area in wanted:
        if area not in tables:
            continue
        active = [spots[area][s] for s in tables[area]
                  if spots[area][s].has_rect and max(spots[area][s].caps) > 0]
        frames.append(area_base(game, area, active))
        points += [[area, AREA_NAME[area], *(f"{v:.2f}" for v in (p.x, p.y, p.z)),
                    *(f"{v:.4f}" for v in (p.ux, p.uz, p.vx, p.vz)),
                    *(f"{v:.2f}" for v in (p.width, p.depth, p.height)),
                    *(f"{v:.4f}" for v in (p.front_x, p.front_z))]
                   for p in game.fishing_points(AREA_ORDER.index(area) + 1)]
        marks += [[area, AREA_NAME[area], kind, f"{x:.2f}", f"{z:.2f}"] for kind, x, z in game.map_marks(area)]
        print(area, len(active))
    if not args.areas:
        paths = game.troll_paths()
        route_map(game, paths)
        start_map(game, paths)
        frames.append(sea_plain(game))
        write_frames(frames)
        write_points(points)
        write_marks(marks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
