"""公開データと文書の整合を検査する。ゲームのファイルは要らない.

    python3 tools/check_docs.py

問題があれば終了コード1で終わる。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fails: list[str] = []

def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK' if ok else 'NG'}] {name}{' : ' + detail if detail else ''}")
    if not ok:
        fails.append(name)

def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def main() -> int:
    data = ROOT / "data"

    acts = {r["name"].strip(): r for r in rows(data / "activities.csv")}
    south = acts["トローリングツアー 南海岸"]
    check("南海岸のトローリングが毎週土日 (NPCの台詞)", all(south[f"week{k}"] == "土日" for k in range(1, 5)))
    check("大会が8種類", sum(r["contest"] == "1" for r in acts.values()) == 8)
    check("掲示板の目標が197件", len(rows(data / "board_targets.csv")) == 197)
    app = (ROOT / "site/app.js").read_text(encoding="utf-8")
    missing = [n for n in re.findall(r'"([\w]+\.csv)"', app) if not (data / n).exists()]
    check("サイトが読む CSV がある", not missing, str(missing))
    frames = rows(data / "map_frames.csv")
    no_image = [r["area"] for r in frames if not (ROOT / "images/base" / f"{r['area']}.png").exists()]
    check("サイトの地図の土台がある", not no_image and len(frames) == 15, str(no_image))

    pages = [ROOT / "README.md", ROOT / "data/README.md", ROOT / "tools/README.md",
             *(ROOT / "docs").glob("*.md")]
    broken, empty = [], []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+?)(?:#[^)]*)?\)", text):
            if not target.startswith("http") and not (page.parent / target).exists():
                broken.append(f"{page.name}: {target}")
        empty += [f"{page.name}: {m}" for m in re.findall(r"<!-- table:([\w-]+) -->\n<!-- /table -->", text)]
    check("文書のリンク", not broken, str(broken[:5]))
    slug = lambda h: re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
    bad_anchor = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for target, frag in re.findall(r"\]\(([^)#]*)#([^)]+)\)", text):
            if target and not target.endswith(".md"):
                continue
            dest = (page.parent / target) if target else page
            heads = re.findall(r"^#+ (.+)$", dest.read_text(encoding="utf-8"), re.M)
            if frag not in {slug(h) for h in heads}:
                bad_anchor.append(f"{page.name}: {target}#{frag}")
    check("文書の見出しへのリンク", not bad_anchor, str(bad_anchor[:5]))
    check("文書の表が埋まっている", not empty, str(empty[:5]))
    polite = re.compile(r"(です|ます|ません|ました|でした)(。|$|\s*\||\s*\(|\s*\[)")
    style = []
    for page in pages:
        for line in page.read_text(encoding="utf-8").split("\n"):
            if page.name == "reception.md" and line.startswith("|"):
                continue
            if polite.search(line):
                style.append(f"{page.name}: {line[:30]}")
    check("常態で書かれている", not style, str(style[:5]))
    labels = re.compile(r"実機で確認|\(解析\)|\(推定\)|確かさ|確かめていません|とみられ")
    labeled = [f"{p.name}: {m}" for p in pages for m in labels.findall(p.read_text(encoding="utf-8"))]
    check("検証の書き分けが残っていない", not labeled, str(labeled[:5]))

    print()
    print("問題なし" if not fails else f"問題 {len(fails)} 件: {fails}")
    return 1 if fails else 0

if __name__ == "__main__":
    raise SystemExit(main())
