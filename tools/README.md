# 生成スクリプト

`data/` の CSV、`docs/` の表、`images/` は、ディスクのファイルからこのスクリプトで生成している。
`index.html` と `site/` のサイトは、これらの CSV と `images/base/` を読んで表示するだけで、ゲームの値を持たない。
ゲームのファイルがあれば、同じ結果になることを確かめられる。
説明の文章は手で書いたもので、生成の対象ではない。

対象はディスクID S22JAF、リビジョン1 である。
スクリプトは `main.dol` のハッシュを確かめ、版が違えば止まる。

## 必要なもの

- Python 3、numpy、matplotlib、Pillow
- Noto Sans CJK JP フォント (地図の文字に使う)
- ディスクの DATA パーティションのファイルを展開したディレクトリ

ゲームのファイルはこのリポジトリに含まれていない。
展開の方法はここでは扱わない。

## 展開先の構成

スクリプトが読むのは次のファイルで、展開先の直下にこの構成で置く。

| 場所 | 内容 |
|---|---|
| `sys/main.dol` | ゲームのプログラム |
| `files/Fish/*.bin` | 魚と出現表 |
| `files/ItemData/*` | ルアー、エサ、竿、リール |
| `files/Test/TrollingPath.bin` | トローリングの航路 |
| `files/Stage/em*/FieldCollision/*` | 地形 |
| `files/Stage/em*/FishingPoint/*` | 足場 |
| `files/PosData/StagePosData.bin` | ホテルとワープ先の位置 |
| `files/Text/TextData.dat` | ゲーム内の文言 |

## 手順

展開先を `--game` に指定して生成する。

    python3 tools/build_data.py --game <展開先>
    python3 tools/depth_effect.py --game <展開先>
    python3 tools/build_maps.py --game <展開先>

差分がなければ、`data/` と `docs/` はディスクの内容と一致している。

    git status --short -- data docs

`images/` の PNG は、matplotlib やフォントの版で変わることがあるので、差分があってもデータの違いとは限らない。

## スクリプト

| ファイル | 内容 |
|---|---|
| `gamedata.py` | ゲームのファイルと `main.dol` を読む |
| `build_data.py` | CSV とページの表を生成する |
| `depth_effect.py` | 水深と、水深が確率に与える影響を計算する |
| `build_maps.py` | 地図を描き、サイトの地図の土台と `data/map_frames.csv`、`data/fishing_points.csv`、`data/map_marks.csv` を出す |
| `check_docs.py` | 文書のリンク、表、書式を検査する (ゲームのファイルは要らない) |

## 文書を直すとき

説明の文章は `docs/` のページを直接編集する。
`build_data.py` は `<!-- table:名前 -->` の間を書き換えるので、表の見出しや列を変えるときは `build_data.py` を直す。
説明の文章は読みやすさのために、できるだけ句点ごとに改行する。

## ライセンス

このディレクトリのコードは [MIT License](LICENSE) である。
ゲームとそのファイルには適用されない。
