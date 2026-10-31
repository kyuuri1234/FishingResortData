"""ゲームの抽出ファイルと DOL から、公開に使う表を読み出す.

入力は --game で指す ゲームのファイルの展開先だけで、生のバイナリから直接読む。
ゲームのファイルは公開リポジトリには含めない。手順は tools/README.md にある。

コードの番地はメモリ上の番地で、main.dol をセクションの番地どおりに並べて読む。
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

DOL_BASE = 0x80004000
# S22JAF リビジョン1 の main.dol。番地を直接読むので、別の版では誤った値になる
DOL_SHA256 = "80187e0beec0d5922beb8699c9ad9bf221fb60fb549552d9e1f53d0e492fd649"

# エリア表の順。Wholeisland (外海) と TestStage は通常の出現表を使わない。
AREA_ORDER = [
    "Beach", "Jungle", "RiverA", "LakeA", "RiverB", "Bluecave", "LakeB", "JungleB",
    "BeachB", "Wholeisland", "IslandA", "IslandB", "Submap01", "Submap02", "Submap03",
    "Submap04", "TestStage",
]
AREA_NAME = {
    "Beach": "トゥマン・パラダイスビーチ",
    "Jungle": "パナス・ジャングル",
    "RiverA": "ティドゥール・リバー",
    "LakeA": "カナン・レイク",
    "RiverB": "ケリキル・リバー",
    "Bluecave": "サフィーア・ケイブ",
    "LakeB": "ドゥアリブ・レイク",
    "JungleB": "マラム・ジャングル",
    "BeachB": "パチャール・ビーチ",
    "IslandA": "スンビラン・アイランド",
    "IslandB": "スプール・アイランド",
    "Submap01": "グナン・エス・リバー",
    "Submap02": "レマック・エス・レイク",
    "Submap03": "パータパ・リバー",
    "Submap04": "ラハージャ・レイク",
}
FREE_AREAS = [a for a in AREA_ORDER if a in AREA_NAME and a != "Submap02"]

# 魚テーブルの群番号と海域。群の代表魚と航路の位置から決めている。
SEA_NAME = {
    0: "トロピカル", 1: "トロピカル", 2: "トロピカル", 3: "トロピカル", 4: "トロピカル",
    5: "テンパレート", 6: "テンパレート", 7: "テンパレート", 8: "フリジッド", 9: "フリジッド",
    10: "トロピカル", 11: "テンパレート", 12: "トロピカル", 13: "トロピカル", 14: "トロピカル",
    15: "テンパレート", 16: "テンパレート", 17: "テンパレート", 18: "フリジッド",
}

EXHIBIT = {116, 120, 121, 122, 123, 221}  # 展示専用
MISSING = {26}                             # 欠番
JUNK = {33, 69, 174, 175, 180, 181, 222, 223, 224, 225}

LURE_TYPES = ["スプーン", "スピナー", "クランクベイト", "バイブレーション", "ミノー"]
LURE_TYPE_RANGES = [(0, 29), (30, 59), (60, 91), (92, 123), (124, 155)]  # 表 0x804B2E78 で確認
LURE_SIZE_BITS = {1: (0, 30), 2: (20, 70), 4: (50, 200), 8: (150, None)}
GATE_RATE = {0: 1.0, 1: 0.8, 2: 0.1, 3: 0.0}


@dataclass
class Fish:
    id: int
    name: str
    grade: int
    base_cm: float
    points: int
    exp: int
    ladder: list[float]  # f5..f13 (生の値)
    gate_class: int      # u19
    lure_mask: int       # u20
    base_color: int      # u21
    mechanism: int       # u22
    bait_group: int      # u23
    speed_coef: float    # f15
    stamina: float       # f16
    rush_div: float      # f17
    pull_class: int      # u18
    rush_index: int      # u24
    speed_cap_index: int # u25


@dataclass
class Entry:
    fish: int
    p: tuple[int, int, int, int]
    w: tuple[float, float, float, float]
    ghost: bool


@dataclass
class Spot:
    area: str
    spot: int
    x: float
    y: float
    z: float
    sx: float
    sz: float
    rot: float
    caps: tuple[int, int, int, int]
    density_a: float
    density_b: float
    bait_adjust: int
    table_group: int  # 外海だけ意味を持つ
    has_rect: bool = field(init=False)

    def __post_init__(self) -> None:
        self.has_rect = not (self.x == 0 and self.z == 0 and self.sx == 0 and self.sz == 0)


@dataclass
class Lure:
    id: int
    name: str
    price: int
    appeal: float
    color1: int
    color2: int
    mechanism: int
    size_mask: int

    @property
    def type_index(self) -> int:
        return next(i for i, (a, b) in enumerate(LURE_TYPE_RANGES) if a <= self.id <= b)

    @property
    def size_range(self) -> tuple[int, int | None]:
        bands = [LURE_SIZE_BITS[b] for b in LURE_SIZE_BITS if self.size_mask & b]
        lo = min(b[0] for b in bands)
        hi = None if any(b[1] is None for b in bands) else max(b[1] for b in bands)
        return lo, hi


@dataclass
class Activity:
    name_id: int
    desc_id: int
    area: int
    contest: bool
    price: int
    days: int


@dataclass
class Rod:
    id: int
    name: str
    size_mask: int
    cast_step: int
    price: int
    tension_max: int


@dataclass
class Reel:
    id: int
    name: str
    size_mask: int
    price: int
    step: int


@dataclass
class Bait:
    id: int
    name: str
    size_mask: int
    price: int
    appeal_cap: float
    appeal_rate: float


def f32(x: float) -> float:
    """倍精度の値を単精度に丸める (ゲームの単精度演算の結果)."""
    return struct.unpack(">f", struct.pack(">f", x))[0]


C100, C001 = f32(100.0), f32(0.01)


def trunc_ladder(f: float) -> float:
    """FindFishRecord のラダーの切り捨て: fctiwz(100×f) × 0.01."""
    return f32(C001 * f32(math.trunc(f32(C100 * f))))


def round_100(f: float) -> int:
    """DecideFishLength の帯境界: 100×f を四捨五入して整数にする."""
    x = f32(C100 * f)
    t = float(math.trunc(x))
    return int(t + 1.0 if f32(x - t) >= 0.5 else t)


def size_from_100(k: int) -> float:
    s = f32(C001 * f32(k))
    return f32(C001 * f32(round_100(s)))


def size_borders(fish: "Fish") -> dict[str, float]:
    """体長の範囲と S の下限 (cm)。結果画面と図鑑で比較の仕方が違う."""
    lad = [trunc_ladder(v) for v in fish.ladder]
    s_edge = lad[0]
    kmin, kmax = round_100(lad[5]), round_100(lad[8])
    k_ind = math.trunc(f32(C100 * s_edge))
    result = next(k for k in range(kmin, kmax + 1)
                  if math.trunc(f32(C100 * size_from_100(k))) >= k_ind)
    dex = next(k for k in range(kmin, kmax + 1) if size_from_100(k) >= s_edge)
    return {"min": kmin / 100, "max": kmax / 100, "s_result": result / 100, "s_dex": dex / 100}


def rank_ladder(fish: "Fish") -> list[float]:
    """S〜D の下限になるラダー (切り捨て後)."""
    return [trunc_ladder(v) for v in fish.ladder[:5]]


def rank_result(size: float, lad: list[float]) -> int:
    """結果画面のランク: 100倍して切り捨てた整数どうしの比較."""
    k = math.trunc(f32(C100 * size))
    for i, f in enumerate(lad):
        if k >= math.trunc(f32(C100 * f)):
            return i
    return 5


def rank_dex(size: float, lad: list[float]) -> int:
    """図鑑のランク: 単精度のまま比較."""
    for i, f in enumerate(lad):
        if size >= f:
            return i
    return 5


def band_ranges(fish: "Fish") -> list[tuple[int, int]]:
    """サイズ帯0〜5 の [下限, 上限] (0.01cm 単位)."""
    lad = [trunc_ladder(v) for v in fish.ladder]
    pairs = ((0, 8), (1, 0), (2, 1), (3, 2), (4, 3), (5, 4))  # f5〜f13 の添字
    return [(round_100(lad[lo]), round_100(lad[hi])) for lo, hi in pairs]


def rank_borders(fish: "Fish") -> dict[str, list[float]]:
    """S〜D の下限 (cm)。結果画面と図鑑で比較の仕方が違う."""
    lad = rank_ladder(fish)
    ranges = band_ranges(fish)
    kmin, kmax = min(a for a, _ in ranges), max(b for _, b in ranges)

    def border(fn) -> list[float]:
        return [next(k for k in range(kmin, kmax + 1) if fn(size_from_100(k), lad) <= r) / 100
                for r in range(5)]

    return {"result": border(rank_result), "dex": border(rank_dex)}


def band_probs(weights: list[int]) -> list[float]:
    """サイズ帯の確率。trunc(合計×乱数) を、帯5 から累積して ≤ で比べる."""
    total = f32(float(sum(weights)))
    cnt = [0] * 6
    for r in range(32768):
        t = math.trunc(f32(total * f32(f32(r) / 32768.0)))
        acc = 0
        for cls in (5, 4, 3, 2, 1, 0):
            acc += weights[cls]
            if t <= acc:
                cnt[cls] += 1
                break
    return [c / 32768 for c in cnt]


_offsets: dict[int, list[int]] = {}


def band_offsets(width: int) -> list[int]:
    """帯の中の位置 trunc((幅+1)×乱数) の出現回数."""
    if width not in _offsets:
        span = f32(1.0 + f32(float(width)))
        cnt = [0] * (width + 1)
        for r in range(32768):
            cnt[math.trunc(f32(span * f32(f32(r) / 32768.0)))] += 1
        _offsets[width] = cnt
    return _offsets[width]


def rank_probs(fish: "Fish", classes: list[float]) -> list[float]:
    """魚ごとのランク S〜E の確率 (結果画面の判定)."""
    lad = rank_ladder(fish)
    out = [0.0] * 6
    for cls, (lo, hi) in enumerate(band_ranges(fish)):
        for off, c in enumerate(band_offsets(hi - lo)):
            out[rank_result(size_from_100(lo + off), lad)] += classes[cls] * c / 32768
    return out


def size_gate(size_cm: float, mask: int, bands: list[tuple[int, float, float]]) -> bool:
    m = f32(size_cm * C001)
    return any(lo <= m <= hi for bit, lo, hi in bands if mask & bit)


@dataclass
class QuestUnlock:
    fish: int
    quest: str
    step: str


def flatten_dol(dol: bytes) -> bytes:
    """DOL のセクションをメモリの番地どおりに並べる。隙間は0で埋める."""
    hdr = struct.unpack(">64I", dol[:256])
    off, addr, size = hdr[0:18], hdr[18:36], hdr[36:54]
    sections = [(o, a, s) for o, a, s in zip(off, addr, size) if s]
    img = bytearray(max(a + s for _, a, s in sections) - DOL_BASE)
    for o, a, s in sections:
        img[a - DOL_BASE:a - DOL_BASE + s] = dol[o:o + s]
    return bytes(img)


class Game:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.files = self.root / "files"
        self.stage = self.files / "Stage"
        dol_path = self.root / "sys/main.dol"
        if not dol_path.is_file():
            raise SystemExit(f"{dol_path} がない。--game にゲームのファイルの展開先を指定する")
        dol = dol_path.read_bytes()
        if hashlib.sha256(dol).hexdigest() != DOL_SHA256:
            raise SystemExit(f"{dol_path} が対象の版と違う。対象はディスクID S22JAF、リビジョン1 である")
        self.flat = flatten_dol(dol)

    # --- DOL ---------------------------------------------------------------
    def u32(self, addr: int) -> int:
        return struct.unpack_from(">I", self.flat, addr - DOL_BASE)[0]

    def s32(self, addr: int) -> int:
        return struct.unpack_from(">i", self.flat, addr - DOL_BASE)[0]

    def f32(self, addr: int) -> float:
        return struct.unpack_from(">f", self.flat, addr - DOL_BASE)[0]

    def s32s(self, addr: int, n: int) -> list[int]:
        return [self.s32(addr + 4 * i) for i in range(n)]

    def f32s(self, addr: int, n: int) -> list[float]:
        return [round(self.f32(addr + 4 * i), 4) for i in range(n)]

    def color_shift_weights(self) -> list[list[int]]:
        """天気ごとの好みの色のずらしの重み。時間帯4行が同じことを確かめて返す."""
        out = []
        for w in range(5):
            base = self.u32(0x80520BCC + 4 * w)
            rows = [self.s32s(base + 28 * t, 7) for t in range(4)]
            assert all(r == rows[0] for r in rows), "時間帯で重みが違う"
            out.append(rows[0])
        return out

    def bait_pattern_weights(self) -> list[list[int]]:
        out = []
        for w in range(5):
            base = self.u32(0x80520BE0 + 4 * w)
            rows = [self.s32s(base + 12 * t, 3) for t in range(4)]
            assert all(r == rows[0] for r in rows), "時間帯で重みが違う"
            out.append(rows[0])
        return out

    def color_distance_table(self) -> list[float]:
        return self.f32s(0x804C1EBC, 7)

    def mechanism_bonus(self) -> float:
        return self.f32s(0x804C1F2C, 4)[1]

    def bait_multiplier_table(self) -> list[float]:
        return self.f32s(0x804C27C0, 6)

    def bait_adjust_table(self) -> list[int]:
        return self.s32s(0x804C27F0, 13)

    def size_band_weights(self) -> list[list[int]]:
        return [self.s32s(0x804AF5E0 + 24 * r, 6) for r in range(5)]

    def title_exp(self) -> list[int]:
        """称号のレベル0〜32 に必要な累計経験値 (表の値は前のレベルからの差)."""
        steps = self.s32s(0x804B9AF8, 33)
        out, total = [], 0
        for v in steps:
            total += v
            out.append(total)
        return out

    def wait_seconds(self) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        """格付け0〜5 の待ち時間 [下限, 上限] (寄る前、ウキの下)."""
        a = self.f32s(0x804BFD20, 12)
        b = self.f32s(0x804BFD50, 12)
        return ([(int(a[i * 2]), int(a[i * 2 + 1])) for i in range(6)],
                [(int(b[i * 2]), int(b[i * 2 + 1])) for i in range(6)])

    def nibble_grade_coef(self) -> list[float]:
        return self.f32s(0x804BFCF0, 6)

    def nibble_rank_coef(self) -> list[float]:
        return self.f32s(0x804BFD08, 6)

    def nibble_bait_seconds(self) -> list[float]:
        return self.f32s(0x804C2790 + 72, 6)

    def run_distance(self) -> list[float]:
        return self.f32s(0x804AF4F8, 6)

    def pull_speeds(self) -> list[tuple[float, float]]:
        return [(self.f32(0x804C8018 + 8 * i), self.f32(0x804C8018 + 8 * i + 4)) for i in range(10)]

    def reel_fit_table(self) -> list[float]:
        return self.f32s(0x804BFDA0, 7)

    def size_gate_bands(self) -> list[tuple[int, float, float]]:
        """[マスクのビット, 下限m, 上限m]。ルアー・竿・リール・エサで共通."""
        return [(1 << i, self.f32(0x804BFD80 + 8 * i), self.f32(0x804BFD80 + 8 * i + 4)) for i in range(4)]

    def over_size_table(self) -> list[int]:
        return [int(v) for v in self.f32s(0x804C8008, 3)]

    def reel_coef(self) -> tuple[list[float], list[float]]:
        return self.f32s(0x804B2EB8, 3), self.f32s(0x804B2EC4, 3)

    def line_limits(self) -> tuple[list[float], list[float]]:
        """糸切れとたるみの [しきい値, 毎秒の減り] × 2."""
        return self.f32s(0x804C8068, 4), self.f32s(0x804C8078, 4)

    def weather_weights(self) -> list[int]:
        return self.s32s(0x804C21D0, 5)

    def flare_table(self) -> list[float]:
        return self.f32s(0x804C21E4, 5)

    def radar_seconds(self) -> list[tuple[int, int]]:
        v = self.s32s(0x804F0458, 12)
        return [(v[i * 2], v[i * 2 + 1]) for i in range(6)]

    def activities(self) -> list[Activity]:
        """ツアー・大会などの表。+0x30 は28日分の予定のビット列 (ビット0が第1週の月曜)."""
        out = []
        for i in range(1, 62):  # 0 はダミー、62 は名前が別の行の複製
            a = 0x804BB070 + i * 0x70
            v = self.s32s(a, 28)
            out.append(Activity(v[0], v[1], v[4], bool(v[7]), v[8], self.u32(a + 0x30)))
        return out

    def board_targets(self) -> list[tuple[int, int, int]]:
        """掲示板の目標 [エリア, 場所の文言, 魚]."""
        return [(self.s32(0x805266E0 + i * 0x30 + 4), self.s32(0x805266E0 + i * 0x30 + 12),
                 self.s32(0x805266E0 + i * 0x30 + 16)) for i in range(197)]

    def reception_fish(self) -> tuple[list[int], list[int]]:
        """受付嬢の話題のキレイな魚 (21種) とカワイイ魚 (20種)."""
        return self.s32s(0x804F73A8, 21), self.s32s(0x804F7400, 20)

    def reception_topic(self, addr: int, count: int) -> list[tuple[int, int]]:
        """話題の表の各行を、文言の表で [文言ID, 種別] に直す."""
        return [(self.s32(0x804F7038 + 8 * i), self.s32(0x804F7038 + 8 * i + 4)) for i in self.s32s(addr, count)]

    def troll_hit_table(self) -> list[list[float]]:
        return [self.f32s(0x804F76C8 + 52 * r, 13) for r in range(5)]

    def stock_table(self) -> list[int]:
        return [self.s32(0x804F3420 + 16 * i + 4) for i in range(12)]

    def quest_locked(self) -> list[int]:
        return [x for x in self.s32s(0x804EE758, 20) if x >= 0]

    def text_ids(self) -> dict[int, str]:
        """TextData.dat の文言。[個数, ?, ?, 先頭からの位置×個数] のあとに UTF-16BE の本文が続く."""
        d = (self.files / "Text/TextData.dat").read_bytes()
        count = struct.unpack_from(">I", d, 0)[0]
        offs = struct.unpack_from(f">{count}I", d, 12)
        out = {}
        for i, off in enumerate(offs):
            end = offs[i + 1] if i + 1 < count else len(d)
            s = d[off:end].decode("utf-16-be", errors="replace")
            out[i] = s.replace("\x00", "").replace("\r", "\\r").replace("\n", "\\n")
        return out

    def quest_unlocks(self, text: dict[int, str]) -> list[QuestUnlock]:
        """クエストの段階ごとの解放魚.

        行は [通番, 文言, 種別, ?, 対象魚, 匹数, 最小サイズ, 解放魚×3]。段階に入ると解放魚の
        ビットが立ち、種別1 (魚を釣る) なら対象魚のビットも立つ (0x801FE2BC・0x801FFDE8)。
        """
        locked = set(self.quest_locked())
        result: dict[int, QuestUnlock] = {}
        for q in range(33):
            e = 0x804EE3F8 + q * 16
            ptr, count, title = self.u32(e + 4), self.s32(e + 8), self.s32(e + 12)
            for r in range(count):
                a = ptr + r * 0x28
                v = self.s32s(a, 10)
                fishes = [x for x in v[7:10] if x >= 0]
                if v[2] == 1 and v[4] >= 0:
                    fishes.append(v[4])
                for fish in fishes:
                    if fish in locked and fish not in result:
                        # 進行度の初期値は0で、セーブの読み込み時に0行目も再適用される
                        step = _plain(text.get(v[1], "")) if r > 0 else ""
                        result[fish] = QuestUnlock(fish, _plain(text.get(title, "")), step)
        missing = locked - set(result)
        assert not missing, f"解放先が見つからない: {missing}"
        return list(result.values())

    # --- 魚 ----------------------------------------------------------------
    def fish_names(self) -> dict[int, str]:
        d = (self.files / "Fish/fishName.bin").read_bytes()
        _, n = struct.unpack(">II", d[:8])
        out = {}
        for i in range(n):
            raw = d[8 + i * 48:8 + (i + 1) * 48].decode("utf-16-be")
            out[i] = raw.split("\x00")[0].strip()
        return out

    def fish(self) -> list[Fish]:
        names = self.fish_names()
        d = (self.files / "Fish/fishData.bin").read_bytes()
        _, n = struct.unpack(">II", d[:8])
        out = []
        for i in range(n):
            o = 8 + i * 104
            u = struct.unpack_from(">26I", d, o)
            f = struct.unpack_from(">26f", d, o)
            assert u[0] == i
            out.append(Fish(u[0], names[i], u[1], round(f[2], 2), u[3], u[4], list(f[5:14]),
                            u[19], u[20], u[21], u[22], u[23], round(f[15], 3), round(f[16], 3),
                            round(f[17], 3), u[18], u[24], u[25]))
        return out

    def fish_categories(self) -> dict[int, int]:
        """結果画面での持ち方 (fishResult.bin の +0)。0 手のひら、1 糸、2 両手、3 水中."""
        d = (self.files / "Fish/fishResult.bin").read_bytes()
        _, n = struct.unpack(">II", d[:8])
        return {i: struct.unpack_from(">i", d, 8 + i * 36)[0] for i in range(n)}

    def battle_params(self) -> list[float]:
        d = (self.files / "Fish/fishBattleParam.bin").read_bytes()
        return [round(v, 3) for v in struct.unpack_from(">14f", d, 8)]

    def rods(self, text: dict[int, str]) -> list[Rod]:
        d = (self.files / "ItemData/RodData.bin").read_bytes()
        out = []
        for i in range(11):
            mask, _rig, cast, price, _model, tmax, _flag = struct.unpack_from(">7i", d, 16 + i * 28)
            out.append(Rod(i, text[2602 + i], mask, cast, price, tmax))
        return out

    def reels(self, text: dict[int, str]) -> list[Reel]:
        d = (self.files / "ItemData/ReelData.bin").read_bytes()
        out = []
        for i in range(9):
            mask, price, _model, _flag, r1, r2 = struct.unpack_from(">6i", d, 16 + i * 24)
            assert r1 == r2
            out.append(Reel(i, text[2658 + i], mask, price, r1))
        return out

    def free_table(self, area: str) -> dict[int, list[Entry]]:
        """fishFree の出現表。枠番号 -> 行 (先頭はヘッダを読み違えて現れる行)."""
        d = (self.files / f"Fish/fishFree_{area}.bin").read_bytes()
        pos = 8
        out: dict[int, list[Entry]] = {}
        while pos < len(d):
            head = struct.unpack_from(">8I4f", d, pos)
            pos += 48
            assert head[1] == 0xFFFFFFFF
            rows = [Entry(head[3], head[4:8], head[8:12], True)]
            for _ in range(head[2] - 1):
                e = struct.unpack_from(">5I4f", d, pos)
                pos += 36
                rows.append(Entry(e[0], e[1:5], e[5:9], False))
            assert head[0] not in out
            out[head[0]] = rows
        assert pos == len(d)
        return out

    def troll_table(self) -> dict[int, list[Entry]]:
        """fishTrolling の出現表。群番号 -> 行."""
        d = (self.files / "Fish/fishTrolling.bin").read_bytes()
        _, n = struct.unpack(">II", d[:8])
        pos = 8
        out: dict[int, list[Entry]] = {}
        for g in range(n):
            head = struct.unpack_from(">6I4fI", d, pos)
            pos += 44
            rows = [Entry(head[1], head[2:6], head[6:10], True)]
            for _ in range(head[0] - 1):
                e = struct.unpack_from(">5I4fI", d, pos)
                pos += 40
                rows.append(Entry(e[0], e[1:5], e[5:9], False))
            out[g] = rows
        assert pos == len(d)
        return out

    def spots(self) -> dict[str, dict[int, Spot]]:
        d = (self.files / "Fish/setSightArea.bin").read_bytes()
        assert len(d) == 4 + 17 * 96 * 108
        out: dict[str, dict[int, Spot]] = {}
        for ai, area in enumerate(AREA_ORDER):
            out[area] = {}
            for s in range(96):
                o = 4 + (ai * 96 + s) * 108
                x, y, z, sx, _h, sz, rot = struct.unpack_from(">7f", d, o)
                caps = tuple(d[o + 28:o + 32])
                da, db = struct.unpack_from(">2f", d, o + 32)
                group = struct.unpack_from(">i", d, o + 40)[0]
                adjust = struct.unpack_from(">i", d, o + 104)[0]
                out[area][s] = Spot(area, s, x, y, z, sx, sz, rot, caps, da, db, adjust, group)
        return out

    def lures(self) -> list[Lure]:
        rec = (self.files / "ItemData/LureData.bin").read_bytes()
        names = (self.files / "ItemData/LureName.bin").read_bytes()
        assert struct.unpack_from(">II", rec) == (1, 156)
        assert struct.unpack_from(">II", names) == (1, 156)
        stride = (len(names) - 8) // 156
        out = []
        for i in range(156):
            o = 8 + i * 36
            price = struct.unpack_from(">i", rec, o)[0]
            appeal = struct.unpack_from(">f", rec, o + 4)[0]
            c1, c2, mech, mask = struct.unpack_from(">4i", rec, o + 20)
            raw = names[8 + i * stride:8 + (i + 1) * stride].decode("utf-16-be")
            chunks = [c for c in re.split(r"\x00+", raw) if c.strip()]
            out.append(Lure(i, " ".join(chunks[0].split()), price, appeal, c1, c2, mech, mask))
        return out

    def baits(self, text: dict[int, str]) -> list[Bait]:
        d = (self.files / "ItemData/BaitData.bin").read_bytes()
        out = []
        for i in range(14):
            o = 16 + i * 32
            mask, _model, _gain, price = struct.unpack_from(">4i", d, o)
            cap, rate = struct.unpack_from(">2f", d, o + 24)
            out.append(Bait(i, text[2630 + i], mask, price, round(cap, 2), round(rate, 2)))
        return out

    def bait_affinity(self) -> list[list[list[int]]]:
        """[群][パターン][エサ] の相性値."""
        d = (self.files / "Fish/fishBattleItem.bin").read_bytes()
        _, n = struct.unpack(">II", d[:8])
        assert n == 54
        rows = [list(struct.unpack_from(">14i", d, 8 + i * 56)) for i in range(n)]
        return [rows[g * 3:g * 3 + 3] for g in range(18)]

    def troll_paths(self) -> list[list[tuple[float, float]]]:
        d = (self.files / "Test/TrollingPath.bin").read_bytes()
        assert d[:4] == b"PATH"
        n = struct.unpack_from(">I", d, 4)[0]
        pos = 8
        out = []
        for _ in range(n):
            k = struct.unpack_from(">I", d, pos)[0]
            pos += 4
            pts = []
            for _ in range(k):
                x, _y, z, *_rest = struct.unpack_from(">6f", d, pos)
                pos += 24
                pts.append((x, z))
            out.append(pts)
        assert pos == len(d)
        return out


def _plain(s: str) -> str:
    """文言の色指定 (制御文字 + "！ǿ") を落とす."""
    s = re.sub(r".！ǿ", "", s).replace("\\n", "")
    return re.sub(r"[\x00-\x1f]", "", s).strip()


def lottery(entries: list[Entry], band: int, disabled: set[int]) -> dict[int, float]:
    """出現抽選の当選確率を、引き直しまで含めて厳密に求める.

    候補は p > 0 かつ w > 1e-5 の行。無効な種に当たると計17回まで引き、全部無効なら
    表の先頭から最初の有効な行を拾う (FishManager::SpawnByLottery)。
    """
    cand = [(e.fish, e.p[band]) for e in entries if e.p[band] > 0 and e.w[band] > 1e-5]
    total = sum(p for _, p in cand)
    if total == 0:
        return {}
    q = sum(p for f, p in cand if f in disabled) / total
    if q >= 1.0:
        return {}
    keep = sum(q ** k for k in range(17))
    out: dict[int, float] = {}
    for f, p in cand:
        if f not in disabled:
            out[f] = out.get(f, 0.0) + p / total * keep
    first = next(f for f, _ in cand if f not in disabled)
    out[first] += q ** 17
    return out


def shift_probs(weights: list[int]) -> list[float]:
    """int((1+合計)×乱数) を累積と比べる抽選の確率 (先頭の候補が1目ぶん多い)."""
    total = sum(weights)
    tickets = list(weights)
    first = next(i for i, w in enumerate(weights) if w > 0)
    tickets[first] += 1
    return [t / (total + 1) for t in tickets]


def color_distance(c: int, favorite: int) -> int:
    d = 6 if c == 0 else abs(c - favorite)
    return 12 - d if d > 6 else d


def color_step(c1: int, c2: int, favorite: int) -> int:
    base = 1 if c1 != 0 and c2 != 0 else 0
    return min(6, base + min(color_distance(c1, favorite), color_distance(c2, favorite)))
