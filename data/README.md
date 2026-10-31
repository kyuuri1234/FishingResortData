# データの説明

すべて UTF-8 の CSV である。

| ファイル | 内容 |
|---|---|
| `fish.csv` | 魚ごとの基本の値 |
| `spots.csv` | スポットの位置と大きさ、時間帯ごとの上限 |
| `spawn_rates.csv` | スポットごとの魚と確率 |
| `quest_unlocks.csv` | クエストで解放される魚 |
| `size_ranks.csv` | 魚ごとの体長の範囲とランクの下限 |
| `size_band_odds.csv`, `titles.csv` | サイズ帯の確率と称号 |
| `rods.csv`, `reels.csv` | 竿とリール |
| `fish_lure_types.csv` | 魚に使えるルアーの系統と体長の範囲 |
| `s_only_lures.csv` | Sランクだけが反応する魚とルアーの組 |
| `weather_next.csv` | 前の日の天気ごとの次の日の確率 |
| `activities.csv` | ツアーや大会の料金と週ごとの予定 |
| `board_targets.csv` | 掲示板の目標の場所と魚 |
| `spot_depth.csv` | スポットの水深の中央値 (`median_depth_m`) と、水でない場所の割合 (`not_water_pct`) |
| `lures.csv` | ルアーの色・機構・体長の範囲 |
| `color_shift.csv` | 天気ごとの好きな色のずれの確率 |
| `lure_color_scores.csv` | 基準色・天気・ルアーごとの色の倍率の期待値 |
| `baits.csv`, `bait_affinity.csv`, `bait_by_weather.csv` | エサの性能と相性 |
| `trolling_lure_color.csv` | トローリングルアーと魚の色の当たり確率 |
| `trolling_route_summary.csv`, `trolling_route_fish.csv` | 航路とルアーごとの当たりの確率と魚の内訳 |
| `trolling_routes.csv` | 航路の座標 |

## 主な列

**spots.csv**: `area` はエリアの識別子、`Offshore` は外海である。
`x`, `z` は中心の座標、`width_m`, `depth_m` は回転前の長方形の幅と奥行、`rot_deg` は回転である。
長方形の点は、中心からの変位 (dx, dz) を `x = 中心x + dx cosθ + dz sinθ`、`z = 中心z − dx sinθ + dz cosθ` で回したものである。
`refill_sec` はつつきが始まってから60秒の間の補充の間隔、`bait_adjust` は[エサの補正](../docs/bait.md#場所による補正)である。

**spawn_rates.csv**: `weight` は抽選の重みである。
`pct_early` はクエストの魚も放流魚もない状態、`pct_standard` はクエストの魚を解放した状態、`pct_all_unlocked` は放流魚も解放した状態の確率 (%) である。
`unlock` は解放の条件である。

**fish.csv**: `s_min_result_cm` は釣り上げた直後の画面、`s_min_dex_cm` は図鑑のSランクの下限である。
`mechanism` は好むルアーの機構で、0が汎用、1がラトル、2が振動である (`lures.csv` も同じ)。
`lure_accept_rate` はルアーの[反応率](../docs/lure-color.md#ルアーの系統と体長)である。
`hold` は結果画面の持ち方、`pull_class` は[引きの強さの区分](../docs/fight.md#魚ごとの引き)、`pull_speed_a`, `pull_speed_b` はその速さA・B、`stamina` は粘りの値、`speed_coef` は基準サイズに対する個体の大きさに掛かる速さの係数、`rush_threshold` は突進のしにくさ、`rush_div` は突進の溜めの増えやすさに関わる値、`speed_cap` は小さい魚の速さを抑える係数である。

**size_ranks.csv**: `result_*_cm` は結果画面、`dex_*_cm` は図鑑の判定の下限である。

**fish_lure_types.csv**: `coverage` は、その範囲に全個体が入るなら `all`、一部の個体だけなら `part` である。

**lure_color_scores.csv**: `expected_multiplier` は色の倍率の期待値、`zero_rate` は倍率が0になる魚の割合である。

**trolling_route_fish.csv**: `stock_state` は放流魚を解放していない状態 (`locked`) か解放した状態 (`unlocked`) かである。
`pick_rate` は魚が選ばれる確率、`hit_rate` は当たりの確率、`per_check` は1回の抽選でその魚がかかる確率、`share_of_hits` は当たりの中の割合である。
