// ゲームの値はここに書かず、すべて data/ の CSV から読む。

const COLORS = {
  1: ["黒", "#26262a"], 2: ["赤", "#d23b3b"], 3: ["赤橙", "#e4572e"], 4: ["橙", "#f08a24"],
  5: ["桃・紫", "#c85aa6"], 6: ["茶", "#8a5a34"], 7: ["銀・白", "#d9dde2"], 8: ["金", "#d4af37"],
  9: ["黄", "#f2d53c"], 10: ["オリーブ", "#7b8530"], 11: ["緑", "#3a9d5a"], 12: ["青", "#2f6fc4"],
};
const TROLL_LOOK = { "赤橙": "#e4572e", "紫": "#8d4bbb", "黄": "#f2d53c", "銀灰": "#a9aeb5", "水色": "#7cc7e8" };
const MECHANISM = ["汎用", "ラトル", "振動"];
const WEATHERS = ["快晴", "晴れ", "薄曇り", "曇り", "厚い曇り"];
const LURE_TYPES = ["スプーン", "スピナー", "クランクベイト", "バイブレーション", "ミノー"];
const RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
const CAPS = ["cap_morning", "cap_day", "cap_evening", "cap_night"];
const VIEWS = [["fish", "魚"], ["map", "釣り場"], ["lure", "ルアー"], ["sure", "S確定"], ["route", "トローリング"]];

const state = { quest: true, stock: false, weather: "晴れ", rods: 5, lureType: "", lureColors: [], zoom: 1, baitAdjust: 0 };
const MARKS = { "ホテル": "H", "ワープ": "W" };
let mapScroll = {};
const D = {};
const main = document.getElementById("main");

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
    else if (c !== "\r") cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head, ...body] = rows;
  return body.map((r) => Object.fromEntries(head.map((k, i) => [k, r[i] ?? ""])));
}

async function load(name) {
  const res = await fetch(`data/${name}`);
  if (!res.ok) throw new Error(`${name}: ${res.status}`);
  return parseCsv((await res.text()).replace(/^﻿/, ""));
}

const groupBy = (rows, key) => {
  const out = new Map();
  for (const r of rows) {
    const k = key(r);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(r);
  }
  return out;
};
const spotKey = (area, spot) => `${area}/${spot}`;

async function loadAll() {
  const [fish, spots, rates, lures, scores, shift, lureTypes, trollFish, trollSum, trollColor, routes, frames, points, marks, sOnly, ranks, affinity, nibble, nibbleGrades, baitWeather] = await Promise.all([
    "fish.csv", "spots.csv", "spawn_rates.csv", "lures.csv", "lure_color_scores.csv", "color_shift.csv",
    "fish_lure_types.csv", "trolling_route_fish.csv", "trolling_route_summary.csv", "trolling_lure_color.csv",
    "trolling_routes.csv", "map_frames.csv", "fishing_points.csv", "map_marks.csv", "s_only_lures.csv", "size_ranks.csv",
    "bait_affinity.csv", "nibble_bait_seconds.csv", "nibble_grades.csv", "bait_by_weather.csv",
  ].map(load));
  D.serviceBait = new Map(affinity.filter((r) => +r.bait_id === 0 && +r.pattern === 0).map((r) => [+r.bait_group, +r.value]));
  D.nibble = new Map(nibble.map((r) => [`${r.value}/${r.bait_adjust}`, +r.seconds]));
  D.nibbleGrades = new Map(nibbleGrades.map((r) => [+r.grade, r]));
  D.baitWeather = groupBy(baitWeather, (r) => +r.bait_group);
  D.ranks = new Map(ranks.map((r) => [+r.fish_id, r]));
  D.sOnlyByFish = groupBy(sOnly, (r) => +r.fish_id);
  D.marks = groupBy(marks, (m) => m.area);
  D.sOnly = new Set(sOnly.map((r) => `${r.fish_id}/${r.lure_id}`));
  D.points = groupBy(points, (p) => p.area);
  D.fish = new Map(fish.map((f) => [+f.fish_id, f]));
  D.catchable = fish.filter((f) => f.note !== "展示専用" && f.note !== "欠番");
  D.fishByName = new Map(D.catchable.map((f) => [f.name, +f.fish_id]));
  D.spots = new Map(spots.map((s) => [spotKey(s.area, s.spot), s]));
  D.spotsByArea = groupBy(spots, (s) => s.area);
  D.frames = new Map(frames.map((f) => [f.area, f]));
  D.areas = frames.map((f) => f.area);
  D.areaName = new Map(spots.map((s) => [s.area, s.area_name]));
  D.ratesByFish = groupBy(rates, (r) => +r.fish_id);
  D.ratesBySpot = groupBy(rates, (r) => spotKey(r.area, r.spot));
  D.lures = new Map(lures.map((l) => [+l.lure_id, l]));
  D.lureByName = new Map(lures.map((l) => [l.name, +l.lure_id]));
  D.scores = new Map(scores.map((r) => [`${r.base_color}/${r.weather}/${r.lure_id}`, r]));
  D.shift = groupBy(shift, (r) => r.weather);
  D.typesByFish = groupBy(lureTypes, (r) => +r.fish_id);
  D.lureTypes = lureTypes;
  D.trollByFish = groupBy(trollFish, (r) => +r.fish_id);
  D.trollByRoute = groupBy(trollFish, (r) => `${r.route}/${r.stock_state}`);
  D.summary = groupBy(trollSum, (r) => `${r.route}/${r.stock_state}`);
  D.trollColor = new Map(trollColor.map((r) => [+r.lure, r]));
  D.routes = groupBy(routes, (r) => +r.route);
  D.routeSea = new Map(trollSum.map((r) => [+r.route, r.sea]));
}

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props ?? {})) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...kids.flat().filter((x) => x != null && x !== false));
  return el;
}

function s(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs ?? {})) el.setAttribute(k, v);
  return el;
}

// docs/ の表と同じ数字になるよう、端数がちょうど5のときは偶数へ丸める
function fixed(v, digits) {
  const scaled = +v * 10 ** digits;
  const floor = Math.floor(scaled);
  if (Math.abs(scaled - floor - 0.5) > 1e-9) return (+v).toFixed(digits);
  return ((floor % 2 ? floor + 1 : floor) / 10 ** digits).toFixed(digits);
}
const pct = (v, digits = 1) => `${fixed(v, digits)}%`;
const sizeText = (lo, hi) => (hi ? `${lo}〜${hi}cm` : `${lo}cm〜`);
const capsText = (spot) => CAPS.map((c) => spot[c]).join(" / ");
const adjustText = (v) => (+v > 0 ? `+${v}` : v);

const tip = document.getElementById("tip");
function bindTip(el, text) {
  el.addEventListener("pointermove", (e) => {
    tip.textContent = text;
    tip.hidden = false;
    const w = tip.offsetWidth;
    tip.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, e.clientX + 12))}px`;
    tip.style.top = `${e.clientY + 14}px`;
  });
  el.addEventListener("pointerleave", () => { tip.hidden = true; });
}

// チェックの状態に応じて、解放された魚の重みの中の割合を求める
const isOpen = (r) => !r.unlock || (r.unlock === "クエスト" && state.quest) || (r.unlock === "放流" && state.stock);
const spotTotals = new Map();
function rate(r) {
  if (!isOpen(r)) return 0;
  const key = `${r.area}/${r.spot}/${state.quest}/${state.stock}`;
  if (!spotTotals.has(key)) {
    spotTotals.set(key, D.ratesBySpot.get(spotKey(r.area, r.spot)).filter(isOpen).reduce((sum, x) => sum + +x.weight, 0));
  }
  return (r.weight / spotTotals.get(key)) * 100;
}
const stockState = () => (state.stock ? "unlocked" : "locked");

function check(key, text) {
  return h("label", { class: "check" }, h("input", {
    type: "checkbox", checked: state[key], onchange: (e) => { state[key] = e.target.checked; render(); },
  }), text);
}
const unlockChecks = () => h("div", { class: "seg" }, h("span", null, "解放"), check("quest", "クエスト"), check("stock", "放流"));

function seg(label, options, value, set) {
  return h("div", { class: "seg" }, h("span", null, label), options.map(([v, text]) =>
    h("button", { type: "button", "aria-pressed": String(v === value), onclick: () => { set(v); render(); } }, text)));
}

// ひらがなとカタカナ、全角と半角、大文字と小文字、空白の違いをなくして比べる
function searchKey(text) {
  return text.normalize("NFKC").toLowerCase().replace(/\s+/g, "")
    .replace(/[\u30a1-\u30f6]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
}

function picker(label, id, names, value, onpick) {
  const entries = [...names].map(([name, v]) => ({ name, v, key: searchKey(name) }));
  const listId = `${id}-list`;
  const list = h("ul", { id: listId, class: "pick-list", role: "listbox", hidden: true });
  const input = h("input", {
    id, value, autocomplete: "off", role: "combobox", placeholder: "名前の一部で探す",
    "aria-autocomplete": "list", "aria-expanded": "false", "aria-controls": listId,
  });
  let shown = [];
  let active = -1;

  const setActive = (i) => {
    list.children[active]?.setAttribute("aria-selected", "false");
    active = i;
    const el = list.children[i];
    if (!el || !shown.length) { input.removeAttribute("aria-activedescendant"); return; }
    el.setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", el.id);
    el.scrollIntoView({ block: "nearest" });
  };
  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  };
  const choose = (entry) => {
    close();
    input.value = entry.name;
    onpick(entry.v);
  };
  const show = (query) => {
    const key = searchKey(query);
    const hits = entries.filter((e) => e.key.includes(key));
    shown = [...hits.filter((e) => e.key.startsWith(key)), ...hits.filter((e) => !e.key.startsWith(key))];
    active = -1;
    list.replaceChildren(...(shown.length
      ? shown.map((e, i) => h("li", { id: `${id}-opt${i}`, class: "pick-item", role: "option", "aria-selected": "false", onclick: () => choose(e) }, e.name))
      : [h("li", { class: "pick-empty" }, "見つからない")]));
    list.hidden = false;
    list.scrollTop = 0;
    input.setAttribute("aria-expanded", "true");
    if (key) setActive(0);
  };

  input.addEventListener("focus", () => { input.select(); show(""); });
  input.addEventListener("input", () => show(input.value));
  input.addEventListener("blur", () => { close(); input.value = value; });
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;  // 日本語入力の変換の確定では選ばない
    if (e.key === "Escape") {
      close();
      input.value = value;
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (list.hidden) show(input.value);
      if (shown.length) setActive((active + (e.key === "ArrowDown" ? 1 : shown.length - 1 + (active < 0 ? 1 : 0))) % shown.length);
    } else if (e.key === "Enter" && !list.hidden && shown[active]) {
      e.preventDefault();
      choose(shown[active]);
    }
  });
  list.addEventListener("mousedown", (e) => e.preventDefault());  // 選ぶ前に入力欄からフォーカスが外れないようにする
  return h("div", { class: "pick" }, h("label", { for: id }, label), h("div", { class: "pick-box" }, input, list));
}

function bar(value, max, text) {
  return h("div", { class: "bar" }, h("b", null, text),
    h("span", null, h("i", { style: `width:${max ? (value / max) * 100 : 0}%` })));
}

function colorChip(no) {
  const [name, hex] = COLORS[no] ?? ["-", "transparent"];
  return h("span", { class: "color" }, h("span", { class: "swatch", style: `background:${hex}` }), `${no} ${name}`);
}

function lureColors(l) {
  const ids = [...new Set([+l.color1, +l.color2].filter((c) => c > 0))];
  return h("span", { class: "colors" }, ids.map(colorChip));
}

function trollChip(lure) {
  const look = D.trollColor.get(lure).look;
  return h("span", { class: "color" }, h("span", { class: "swatch", style: `background:${TROLL_LOOK[look]}` }), `${lure}番 ${look}`);
}

function heatCell(value, text) {
  if (!(value > 0)) return h("td", { class: "heat" }, text);
  const i = Math.min(RAMP.length - 1, Math.floor(value * RAMP.length));
  return h("td", { class: `heat ${i >= 3 ? "heat-dark" : "heat-light"}`, style: `background:${RAMP[i]}` }, text);
}

function table(head, rows) {
  return h("div", { class: "tw" }, h("table", null,
    h("thead", null, h("tr", null, head.map(([text, cls]) => h("th", { class: cls ?? null, scope: "col" }, text)))),
    h("tbody", null, rows)));
}

function zoomSeg() {
  return seg("拡大", [[1, "1倍"], [2, "2倍"], [3, "3倍"]], state.zoom, (v) => { state.zoom = v; mapScroll = {}; });
}

function mapFrame(area, draw, zoomable = true) {
  const f = D.frames.get(area);
  const [w, hgt] = [+f.width_px, +f.height_px];
  const toPx = (x, z) => [f.px_x * x + f.px_z * z + +f.px_0, f.py_x * x + f.py_z * z + +f.py_0];
  const svg = s("svg", { viewBox: `0 0 ${w} ${hgt}`, role: "img", "aria-label": `${D.areaName.get(area) ?? area} の地図` });
  draw(svg, toPx);
  drawStands(svg, area, toPx);
  drawScale(svg, f);
  svg.append(...svg.querySelectorAll(".spot-label"));  // 番号が足場に隠れないよう最後に描く
  drawMarks(svg, area, toPx);
  const zoom = zoomable ? state.zoom : 1;
  const view = h("div", {
    class: "map-view",
    onscroll: () => { mapScroll[area] = [view.scrollLeft, view.scrollTop]; },
  }, h("div", { class: "map", style: `aspect-ratio:${w}/${hgt};width:calc(min(100%, 74vh * ${w / hgt}) * ${zoom})` },
    h("img", { src: `images/base/${area}.png`, alt: "", width: w, height: hgt }), svg));
  if (zoom > 1) {
    requestAnimationFrame(() => {
      const [left, top] = mapScroll[area] ?? [(view.scrollWidth - view.clientWidth) / 2, (view.scrollHeight - view.clientHeight) / 2];
      view.scrollLeft = left;
      view.scrollTop = top;
    });
  }
  const kinds = [...new Set((D.marks.get(area) ?? []).map((m) => m.kind))];
  return h("div", null, view, h("div", { class: "legend" },
    D.points.has(area) ? [h("i", { class: "legend-stand" }), "足場 (短い線は竿を振る向き)"] : null,
    kinds.map((k) => [h("b", { class: `legend-mark mark-${MARKS[k]}` }, MARKS[k]), k]).flat()));
}

function drawMarks(svg, area, toPx) {
  for (const m of D.marks.get(area) ?? []) {
    const [x, y] = toPx(+m.x, +m.z);
    const letter = MARKS[m.kind];
    const text = s("text", { x: x.toFixed(1), y: y.toFixed(1), class: "mark-text" });
    text.textContent = letter;
    svg.append(s("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: 13, class: `mark mark-${letter}` }), text);
  }
}

function drawStands(svg, area, toPx) {
  for (const p of D.points.get(area) ?? []) {
    const [a, b] = [p.width_m / 2, p.depth_m / 2];
    const pts = [[-1, -1], [1, -1], [1, 1], [-1, 1]]
      .map(([i, j]) => toPx(+p.x + i * a * p.ux + j * b * p.vx, +p.z + i * a * p.uz + j * b * p.vz).map((v) => v.toFixed(1)).join(","))
      .join(" ");
    svg.append(s("polygon", { points: pts, class: "stand" }));
    const [x0, y0] = toPx(+p.x, +p.z);
    const [x1, y1] = toPx(+p.x + +p.front_x, +p.z + +p.front_z);
    const len = Math.hypot(x1 - x0, y1 - y0) || 1;
    svg.append(s("line", { x1: x0.toFixed(1), y1: y0.toFixed(1), x2: (x0 + ((x1 - x0) / len) * 12).toFixed(1), y2: (y0 + ((y1 - y0) / len) * 12).toFixed(1), class: "stand-dir" }));
  }
}

function drawScale(svg, f) {
  const span = f.width_px * f.m_per_px;
  const unit = 10 ** Math.floor(Math.log10(span / 5));
  const size = Math.max(...[1, 2, 5].map((n) => n * unit).filter((v) => v <= span / 5));
  const [x, y, w] = [24, f.height_px - 24, size / f.m_per_px];
  svg.append(s("line", { x1: x, y1: y, x2: x + w, y2: y, class: "scale-halo" }), s("line", { x1: x, y1: y, x2: x + w, y2: y, class: "scale-line" }));
  const text = s("text", { x: x + w / 2, y: y - 14, class: "spot-label" });
  text.textContent = `${size}m`;
  svg.append(text);
}

function spotCorners(spot, toPx) {
  const th = (+spot.rot_deg * Math.PI) / 180;
  const [c, sn] = [Math.cos(th), Math.sin(th)];
  const [sx, sz] = [spot.width_m / 2, spot.depth_m / 2];
  return [[-sx, -sz], [sx, -sz], [sx, sz], [-sx, sz]]
    .map(([lx, lz]) => toPx(+spot.x + c * lx + sn * lz, +spot.z - sn * lx + c * lz).map((v) => v.toFixed(1)).join(","))
    .join(" ");
}

// 大きいスポットを先に描き、小さいスポットを上に重ねてクリックできるようにする
function drawSpots(svg, area, toPx, style) {
  const spots = [...(D.spotsByArea.get(area) ?? [])].sort((a, b) => b.area_m2 - a.area_m2);
  for (const spot of spots) {
    const pts = spotCorners(spot, toPx);
    const st = style(spot);
    const shape = s("polygon", { points: pts, class: st.class });
    if (st.fill) shape.setAttribute("fill", st.fill);
    const hit = s("polygon", { points: pts, class: "spot-hit", "data-spot": spot.spot });
    hit.addEventListener("click", () => { location.hash = `#map/${area}/${spot.spot}`; });
    bindTip(hit, st.tip);
    svg.append(shape, hit);
    if (st.label) {
      const [px, py] = toPx(+spot.x, +spot.z);
      const text = s("text", { x: px.toFixed(1), y: py.toFixed(1), class: "spot-label" });
      text.textContent = spot.spot;
      svg.append(text);
    }
  }
}

function favoriteOdds(base) {
  const out = new Map();
  for (const w of WEATHERS) {
    const row = Array(13).fill(0);
    for (const r of D.shift.get(w)) row[((base - 1 + +r.shift) % 12) + 1] += +r.probability;
    out.set(w, row);
  }
  return out;
}

function fishPlaces(id) {
  const rows = (D.ratesByFish.get(id) ?? []).filter((r) => rate(r) > 0);
  return [...groupBy(rows, (r) => r.area)]
    .map(([area, list]) => ({ area, list: list.sort((a, b) => rate(b) - rate(a)) }))
    .sort((a, b) => rate(b.list[0]) - rate(a.list[0]));
}

function viewPlaces(id, wanted) {
  const places = fishPlaces(id);
  if (!places.length) return [h("h2", null, "釣れる場所"), h("div", { class: "filters" }, unlockChecks()),
    h("p", { class: "note" }, "この解放状況では、スポットの出現表に出ない。")];
  const now = places.find((p) => p.area === wanted) ?? places[0];
  const max = Math.max(...now.list.map(rate));
  const value = new Map(now.list.map((r) => [r.spot, rate(r)]));
  const name = D.fish.get(id).name;
  const map = mapFrame(now.area, (svg, toPx) => drawSpots(svg, now.area, toPx, (spot) => {
    const v = value.get(spot.spot);
    if (v == null) return { class: "spot-none", tip: `スポット ${spot.spot}: ${name} はいない` };
    const i = Math.min(RAMP.length - 1, Math.floor((v / max) * RAMP.length));
    return { class: "spot-on", fill: RAMP[i], tip: `スポット ${spot.spot}: ${pct(v)}`, label: true };
  }));
  const rows = now.list.map((r) => {
    const spot = D.spots.get(spotKey(r.area, r.spot));
    return h("tr", null,
      h("td", { class: "num" }, h("a", { href: `#map/${r.area}/${r.spot}` }, r.spot)),
      h("td", null, bar(rate(r), max, pct(rate(r)))),
      h("td", { class: "num" }, capsText(spot)));
  });
  return [
    h("h2", null, "釣れる場所"),
    h("div", { class: "filters" }, unlockChecks(), zoomSeg()),
    h("div", { class: "chips" }, places.map((p) => h("a", {
      class: "chip", href: `#fish/${id}/${p.area}`, "aria-current": String(p === now),
    }, D.areaName.get(p.area), h("small", null, `最大 ${pct(rate(p.list[0]))}・${p.list.length}か所`)))),
    h("div", { class: "cols" },
      h("div", null, map, h("div", { class: "legend" }, "0%", RAMP.map((c) => h("i", { style: `background:${c}` })), pct(max))),
      table([["スポット", "num"], ["確率"], ["上限 朝/昼/夕/夜", "num"]], rows)),
  ];
}

function viewTrollingOfFish(id) {
  const rows = (D.trollByFish.get(id) ?? []).filter((r) => r.stock_state === stockState());
  if (!rows.length) return [];
  const routes = [...groupBy(rows, (r) => +r.route)]
    .map(([route, list]) => ({ route, list, best: Math.max(...list.map((r) => +r.per_check)) }))
    .sort((a, b) => b.best - a.best);
  const top = routes[0].best;
  return [
    h("h2", null, "トローリング"),
    h("p", { class: "note" }, "1回の抽選でこの魚がかかる確率である。いちばん高いルアーを太字にしている。"),
    table([["航路", "num"], ["海域"], ["選ばれる確率", "num"], ...[1, 2, 3, 4, 5].map((n) => [trollChip(n), "num"])],
      routes.map(({ route, list, best }) => h("tr", null,
        h("td", { class: "num" }, h("a", { href: `#route/${route}` }, String(route))),
        h("td", { class: "nowrap" }, D.routeSea.get(route)),
        h("td", { class: "num" }, pct(list[0].pick_rate * 100)),
        [1, 2, 3, 4, 5].map((n) => {
          const v = +list.find((r) => +r.lure === n).per_check;
          const cell = heatCell(v / top, pct(v * 100, 2));
          if (v === best) cell.style.fontWeight = "700";
          return cell;
        })))),
  ];
}

function fishLures(f) {
  const ranges = D.typesByFish.get(+f.fish_id) ?? [];
  const out = [];
  for (const l of D.lures.values()) {
    const r = ranges.find((x) => x.type === l.type && x.size_min_cm === l.size_min_cm && x.size_max_cm === l.size_max_cm);
    if (!r) continue;
    const sc = D.scores.get(`${f.base_color}/${state.weather}/${l.lure_id}`);
    const match = l.mechanism === f.mechanism;
    out.push({ l, part: r.coverage === "part", sure: D.sOnly.has(`${f.fish_id}/${l.lure_id}`), m: +sc.expected_multiplier, zero: +sc.zero_rate, match, total: +sc.expected_multiplier * (match ? 1.2 : 1) });
  }
  return out.sort((a, b) => b.sure - a.sure || b.total - a.total);
}

function viewSize(f) {
  const r = D.ranks.get(+f.fish_id);
  if (!r) return [];
  const row = (k) => h("tr", null, h("td", null, k),
    h("td", { class: "num" }, `${(+r[`result_${k}_cm`]).toFixed(2)}cm`),
    h("td", { class: "num" }, `${(+r[`dex_${k}_cm`]).toFixed(2)}cm`));
  return [
    h("h2", null, "サイズとランク"),
    h("p", { class: "note" }, `Sランクで湧く確率は、クラスで${pct(r.s_pct_first_column, 2)}から${pct(r.s_pct_last_column, 2)}へ変わる。`),
    h("div", { class: "narrow" }, table([["ランク"], ["結果画面の下限", "num"], ["図鑑の下限", "num"]], [..."SABCD"].map(row))),
  ];
}

function spotRanges(nums) {
  const out = [];
  for (const n of [...nums].sort((a, b) => a - b)) {
    const last = out.at(-1);
    if (last && last[1] === n - 1) last[1] = n;
    else out.push([n, n]);
  }
  return out.map(([lo, hi]) => (lo === hi ? String(lo) : `${lo}〜${hi}`)).join("、");
}

function viewBait(f) {
  const id = +f.fish_id;
  if (!D.ratesByFish.has(id) && D.trollByFish.has(id)) return [];
  const column = { 1: "multiplier_adjust_plus1", 0: "multiplier_adjust_0", [-1]: "multiplier_adjust_minus" }[state.baitAdjust];
  const group = D.baitWeather.get(+f.bait_group);
  const baits = groupBy(group, (r) => r.bait);
  const values = group.map((r) => +r[column]);
  const low = Math.min(...values);
  const span = Math.max(...values) - low;
  return [
    h("h2", null, "エサの相性"),
    h("div", { class: "filters" }, seg("エサの補正", [[1, "+1"], [0, "0"], [-1, "-1、-2"]], state.baitAdjust, (v) => { state.baitAdjust = v; })),
    table([["エサ"], ...WEATHERS.map((w) => [w, "num"])], [...baits].map(([bait, list]) => h("tr", null,
      h("td", null, bait),
      WEATHERS.map((w) => {
        const m = +list.find((r) => r.weather === w)[column];
        return heatCell(span > 0 ? (m - low) / span : 0, fixed(m, 2));
      })))),
  ];
}

function viewNibble(f) {
  const id = +f.fish_id;
  const value = D.serviceBait.get(+f.bait_group);
  const plus = (adjust) => D.nibble.get(`${value}/${adjust}`) ?? 0;
  const groups = new Map();
  for (const { area, list } of fishPlaces(id)) {
    for (const r of list) {
      const seconds = plus(D.spots.get(spotKey(r.area, r.spot)).bait_adjust);
      const key = `${area}/${seconds}`;
      if (!groups.has(key)) groups.set(key, { area, seconds, spots: [] });
      groups.get(key).spots.push(+r.spot);
    }
  }
  if (!groups.size) return [];
  const rows = [...groups.values()].sort((a, b) => b.seconds - a.seconds);
  const floatFish = +f.grade < 3 ? plus(0) : null;
  const base = D.nibbleGrades.get(+f.grade);
  const time = (seconds) => `${+base.min_sec + seconds}〜${+base.max_sec + seconds}秒`;
  const head = h("h2", null, "ウキをつつく時間");
  const all = new Set(rows.map((g) => g.seconds));
  if (floatFish != null) all.add(floatFish);
  if (all.size === 1) return [head, h("dl", { class: "stats" }, h("div", null, h("dt", null, "ランクC以下"), h("dd", null, time(rows[0].seconds))))];
  const split = (area) => rows.filter((g) => g.area === area).length > 1;
  const row = (place, seconds) => h("tr", null, h("td", null, place), h("td", { class: "num" }, time(seconds)));
  return [
    head,
    h("div", { class: "narrow" }, table([["釣り場"], ["ランクC以下", "num"]], [
      ...rows.map((g) => row([h("a", { href: `#fish/${id}/${g.area}` }, D.areaName.get(g.area)), split(g.area) ? ` スポット ${spotRanges(g.spots)}` : ""], g.seconds)),
      floatFish != null ? row("ウキに湧いた魚", floatFish) : null,
    ])),
  ];
}

function viewColors(f) {
  const base = +f.base_color;
  const head = [h("h2", null, "ルアーの色の食いつきやすさ")];
  if (!D.ratesByFish.has(+f.fish_id) && D.trollByFish.has(+f.fish_id)) return [...head, h("p", { class: "note" }, "トローリングでしか釣れない魚である。")];
  if (!D.typesByFish.has(+f.fish_id)) return [...head, h("p", { class: "note" }, "ルアーに反応しない魚である。")];
  const odds = favoriteOdds(base);
  const colorTable = table([["天気"], ...Object.keys(COLORS).map((c) => [String(c), "num"])],
    WEATHERS.map((w) => h("tr", { class: w === state.weather ? "is-pick" : null },
      h("td", { class: "nowrap" }, w),
      Object.keys(COLORS).map((c) => {
        const p = odds.get(w)[c];
        return heatCell(p, p > 0 ? `${Math.round(p * 100)}` : "");
      }))));
  const lures = fishLures(f);
  const max = Math.max(...lures.map((x) => x.total));
  const sure = D.sOnlyByFish.get(+f.fish_id) ?? [];
  const ranges = groupBy(D.typesByFish.get(+f.fish_id) ?? [], (r) => r.type);
  return [
    ...head,
    h("dl", { class: "stats" },
      h("div", null, h("dt", null, "基準色"), h("dd", null, colorChip(base))),
      h("div", null, h("dt", null, "好むアピールの種類"), h("dd", null, MECHANISM[+f.mechanism])),
      h("div", null, h("dt", null, "ルアーに反応する確率"), h("dd", null, pct(f.lure_accept_rate * 100, 0)))),
    h("h3", null, "好きな色の確率 (%)"),
    h("div", { class: "note" }, h("span", { class: "colors" }, Object.keys(COLORS).map(colorChip))),
    colorTable,
    h("h3", null, "反応するルアーの体長"),
    h("div", { class: "narrow" }, table([["種類"], ["体長の範囲"]], LURE_TYPES.filter((t) => ranges.has(t)).map((t) => h("tr", null,
      h("td", { class: "nowrap" }, t),
      h("td", null, ranges.get(t).map((r) => sizeText(r.size_min_cm, r.size_max_cm) + (r.coverage === "part" ? "*" : "")).join("、")))))),
    h("h3", null, "使えるルアー"),
    h("div", { class: "filters" }, seg("天気", WEATHERS.map((w) => [w, w]), state.weather, (v) => { state.weather = v; })),
    lures.some((x) => x.sure) ? h("p", { class: "sure-note" }, h("b", { class: "badge" }, "S確定"), `のルアー ${lures.filter((x) => x.sure).length}本にかかれば、この魚は必ずSランクである (反応する体長 ${(+sure[0].pass_min_cm).toFixed(2)}〜${(+sure[0].pass_max_cm).toFixed(2)}cm)。`) : null,
    h("p", { class: "note" }, "倍率は色の倍率の期待値で、アピールの種類が魚の好みと合うルアーは1.2倍した値である。「*」は一部の個体だけが反応するルアーである。"),
    table([["ルアー"], ["種類"], ["色"], ["体長"], ["アピールの種類"], ["倍率"], ["倍率0の割合", "num"]],
      lures.map((x) => h("tr", { class: x.sure ? "is-sure" : null },
        h("td", { class: "nowrap" }, h("a", { href: `#lure/${x.l.lure_id}` }, x.l.name), x.sure ? h("b", { class: "badge" }, "S確定") : x.part ? " *" : ""),
        h("td", { class: "nowrap" }, x.l.type),
        h("td", null, lureColors(x.l)),
        h("td", { class: "nowrap" }, sizeText(x.l.size_min_cm, x.l.size_max_cm)),
        h("td", { class: "nowrap" }, MECHANISM[+x.l.mechanism], x.match ? " (一致)" : ""),
        h("td", null, bar(x.total, max, x.total.toFixed(2))),
        h("td", { class: "num" }, pct(x.zero * 100, 0))))),
  ];
}

function viewFish(idText, area) {
  const id = D.fishByName.has(D.fish.get(+idText)?.name) ? +idText : +D.catchable[0].fish_id;
  const f = D.fish.get(id);
  return [
    picker("魚", "pick-fish", D.fishByName, f.name, (v) => { location.hash = `#fish/${v}`; }),
    h("h1", null, f.name),
    h("dl", { class: "stats" },
      h("div", null, h("dt", null, "グレード"), h("dd", null, f.grade)),
      h("div", null, h("dt", null, "体長"), h("dd", null, `${f.min_cm}〜${f.max_cm}cm`)),
      h("div", null, h("dt", null, "ポイント"), h("dd", null, f.points)),
      f.unlock ? h("div", null, h("dt", null, "解放"), h("dd", null, f.unlock)) : null,
      f.note ? h("div", null, h("dt", null, "区分"), h("dd", null, f.note)) : null),
    viewPlaces(id, area),
    viewTrollingOfFish(id),
    viewSize(f),
    viewBait(f),
    viewNibble(f),
    viewColors(f),
  ];
}

function viewMap(areaArg, spotArg) {
  const area = D.frames.has(areaArg) ? areaArg : D.areas[0];
  const key = spotKey(area, spotArg);
  const picked = D.spots.has(key) ? D.spots.get(key) : null;
  const spots = [...(D.spotsByArea.get(area) ?? [])].sort((a, b) => a.spot - b.spot);
  const fishIn = (spot) => (D.ratesBySpot.get(spotKey(area, spot.spot)) ?? [])
    .filter((r) => rate(r) > 0)
    .sort((a, b) => rate(b) - rate(a));
  const map = mapFrame(area, (svg, toPx) => drawSpots(svg, area, toPx, (spot) => {
    const top = fishIn(spot)[0];
    return {
      class: spot === picked ? "spot-pick" : "spot-idle",
      tip: `スポット ${spot.spot}${top ? `: ${top.fish} ${pct(rate(top))} ほか` : ""}`,
      label: true,
    };
  }));
  const detail = picked ? (() => {
    const list = fishIn(picked);
    const max = list.length ? rate(list[0]) : 0;
    return [
      h("h2", { style: "margin-top:0" }, `スポット ${picked.spot}`),
      h("dl", { class: "stats" },
        h("div", null, h("dt", null, "上限 朝/昼/夕/夜"), h("dd", null, capsText(picked))),
        h("div", null, h("dt", null, "面積"), h("dd", null, `${(+picked.area_m2).toLocaleString("ja-JP")}m²`)),
        h("div", null, h("dt", null, "幅×奥行"), h("dd", null, `${(+picked.width_m).toFixed(0)}×${(+picked.depth_m).toFixed(0)}m`)),
        h("div", null, h("dt", null, "補充間隔"), h("dd", null, `${picked.refill_sec}秒`)),
        h("div", null, h("dt", null, "エサの補正"), h("dd", null, adjustText(picked.bait_adjust)))),
      h("div", { style: "height:8px" }),
      table([["魚"], ["確率"]], list.map((r) => h("tr", null,
        h("td", { class: "nowrap" }, h("a", { href: `#fish/${r.fish_id}/${area}` }, r.fish)),
        h("td", null, bar(rate(r), max, pct(rate(r))))))),
    ];
  })() : [h("p", { class: "note" }, "地図のスポットか下の一覧を選ぶ。")];
  return [
    h("h1", null, D.areaName.get(area)),
    h("div", { class: "chips" }, D.areas.map((a) => h("a", {
      class: "chip", href: `#map/${a}`, "aria-current": String(a === area),
    }, D.areaName.get(a)))),
    h("div", { class: "filters" }, unlockChecks(), zoomSeg()),
    h("div", { class: "cols" }, h("div", null, map), h("div", null, detail)),
    h("h2", null, `スポットの一覧 (${spots.length}か所)`),
    table([["スポット", "num"], ["最も多い魚"], ["確率", "num"], ["魚の数", "num"], ["上限 朝/昼/夕/夜", "num"]],
      spots.map((spot) => {
        const list = fishIn(spot);
        return h("tr", { class: spot === picked ? "is-pick" : null },
          h("td", { class: "num" }, h("a", { href: `#map/${area}/${spot.spot}` }, spot.spot)),
          h("td", { class: "nowrap" }, list[0]?.fish ?? "-"),
          h("td", { class: "num" }, list[0] ? pct(rate(list[0])) : "-"),
          h("td", { class: "num" }, String(list.length)),
          h("td", { class: "num" }, capsText(spot)));
      })),
  ];
}

function colorFilter() {
  const toggle = (c) => {
    const now = state.lureColors;
    state.lureColors = now.includes(c) ? now.filter((x) => x !== c) : [...now, c].slice(-2);
    render();
  };
  return h("div", { class: "seg" }, h("span", null, "色 (2色まで)"),
    h("button", { type: "button", "aria-pressed": String(!state.lureColors.length), onclick: () => { state.lureColors = []; render(); } }, "すべて"),
    Object.keys(COLORS).map((c) => h("button", {
      type: "button", "aria-pressed": String(state.lureColors.includes(+c)), onclick: () => toggle(+c),
    }, colorChip(+c))));
}

function viewLure(idText) {
  const shown = [...D.lures.values()].filter((l) => (!state.lureType || l.type === state.lureType)
    && state.lureColors.every((c) => +l.color1 === c || +l.color2 === c));
  const id = D.lures.has(+idText) && idText !== undefined && idText !== "" ? +idText : +D.lures.values().next().value.lure_id;
  const l = D.lures.get(id);
  const fish = D.lureTypes
    .filter((r) => r.type === l.type && r.size_min_cm === l.size_min_cm && r.size_max_cm === l.size_max_cm)
    .sort((a, b) => a.fish_id - b.fish_id);
  return [
    picker("ルアー", "pick-lure", D.lureByName, l.name, (v) => { location.hash = `#lure/${v}`; }),
    h("h1", null, l.name),
    h("dl", { class: "stats" },
      h("div", null, h("dt", null, "色"), h("dd", null, lureColors(l))),
      h("div", null, h("dt", null, "反応する体長"), h("dd", null, sizeText(l.size_min_cm, l.size_max_cm))),
      h("div", null, h("dt", null, "種類"), h("dd", null, l.type)),
      h("div", null, h("dt", null, "アピールの種類"), h("dd", null, MECHANISM[+l.mechanism])),
      h("div", null, h("dt", null, "アピール基準"), h("dd", null, `${l.appeal_base_m}m`)),
      h("div", null, h("dt", null, "価格"), h("dd", null, l.price ? `${(+l.price).toLocaleString("ja-JP")}pt` : "-"))),
    h("h2", null, `反応する魚 (${fish.length}種)`),
    h("p", { class: "note" }, "「*」は一部の個体だけが反応する魚である。"),
    h("div", { class: "fishlist" }, fish.map((r) => h("span", null,
      h("a", { href: `#fish/${r.fish_id}` }, r.fish),
      D.sOnly.has(`${r.fish_id}/${l.lure_id}`) ? h("b", { class: "badge" }, "S確定") : r.coverage === "part" ? " *" : ""))),
    h("h2", null, `ルアーの一覧 (${shown.length}本)`),
    h("div", { class: "filters" }, seg("種類", [["", "すべて"], ...LURE_TYPES.map((t) => [t, t])], state.lureType, (v) => { state.lureType = v; })),
    h("div", { class: "filters" }, colorFilter()),
    shown.length ? null : h("p", { class: "note" }, "この条件のルアーはない。"),
    table([["ルアー"], ["種類"], ["色"], ["体長"], ["アピールの種類"], ["アピール", "num"]],
      shown.map((x) => h("tr", { class: x === l ? "is-pick" : null },
        h("td", { class: "nowrap" }, h("a", { href: `#lure/${x.lure_id}` }, x.name)),
        h("td", { class: "nowrap" }, x.type),
        h("td", null, lureColors(x)),
        h("td", { class: "nowrap" }, sizeText(x.size_min_cm, x.size_max_cm)),
        h("td", { class: "nowrap" }, MECHANISM[+x.mechanism]),
        h("td", { class: "num" }, `${x.appeal_base_m}m`)))),
  ];
}

function viewSure() {
  const rows = [...D.sOnlyByFish].sort((a, b) => D.fish.get(a[0]).base_cm - D.fish.get(b[0]).base_cm || a[0] - b[0]);
  return [
    h("h1", null, "S確定のルアー"),
    h("p", { class: "note" }, "次の魚は、ルアーの体長の下限がSランクの境目より上にあるので、このルアーにかかれば必ずSランクである。"),
    table([["魚"], ["反応する体長", "num"], ["ルアーに反応する確率", "num"], ["ルアー"]], rows.map(([id, list]) => {
      const f = D.fish.get(id);
      const series = [...new Set(list.map((r) => r.lure.split(" ")[0]))];
      return h("tr", null,
        h("td", { class: "nowrap" }, h("a", { href: `#fish/${id}` }, f.name)),
        h("td", { class: "num" }, `${(+list[0].pass_min_cm).toFixed(2)}〜${(+list[0].pass_max_cm).toFixed(2)}cm`),
        h("td", { class: "num" }, pct(f.lure_accept_rate * 100, 0)),
        h("td", null, series.join("、")));
    })),
  ];
}

function routeLength(points) {
  let len = 0;
  points.forEach((p, i) => {
    const q = points[(i + 1) % points.length];
    len += Math.hypot(q.x - p.x, q.z - p.z);
  });
  return len;
}

function viewRoute(arg) {
  const routes = [...D.routes.keys()].sort((a, b) => a - b);
  const route = D.routes.has(+arg) && arg !== undefined && arg !== "" ? +arg : routes[0];
  const summary = D.summary.get(`${route}/${stockState()}`) ?? [];
  const fishRows = D.trollByRoute.get(`${route}/${stockState()}`) ?? [];
  const secKey = state.rods === 5 ? "sec_per_bite_5rods" : "sec_per_bite_1rod";
  const maxHit = Math.max(...summary.map((r) => +r.hit_per_check));
  const fish = [...groupBy(fishRows, (r) => +r.fish_id)]
    .sort((a, b) => b[1][0].pick_rate - a[1][0].pick_rate || a[0] - b[0]);
  const map = mapFrame("Offshore", (svg, toPx) => {
    const line = (r) => D.routes.get(r).map((p) => toPx(+p.x, +p.z).map((v) => v.toFixed(1)).join(",")).join(" ");
    for (const r of routes.filter((x) => x !== route)) svg.append(s("polygon", { points: line(r), class: "route" }));
    svg.append(s("polygon", { points: line(route), class: "route route-on" }));
    for (const r of routes) {
      const hit = s("polygon", { points: line(r), class: "route-hit", "data-route": r });
      hit.addEventListener("click", () => { location.hash = `#route/${r}`; });
      bindTip(hit, `航路 ${r} (${D.routeSea.get(r)})`);
      svg.append(hit);
    }
  }, false);
  return [
    h("h1", null, `航路 ${route}`),
    h("dl", { class: "stats" },
      h("div", null, h("dt", null, "海域"), h("dd", null, D.routeSea.get(route))),
      h("div", null, h("dt", null, "1周の長さ"), h("dd", null, `${Math.round(routeLength(D.routes.get(route))).toLocaleString("ja-JP")}m`))),
    h("div", { class: "chips" }, routes.map((r) => h("a", {
      class: "chip", href: `#route/${r}`, "aria-current": String(r === route),
    }, `航路 ${r}`, h("small", null, D.routeSea.get(r))))),
    h("div", { class: "filters" },
      h("div", { class: "seg" }, h("span", null, "解放"), check("stock", "放流")),
      seg("竿", [[1, "1本"], [5, "5本"]], state.rods, (v) => { state.rods = v; })),
    h("div", { class: "cols" },
      h("div", null, map),
      h("div", null,
        h("h2", { style: "margin-top:0" }, "各色のかかりやすさ"),
        h("p", { class: "note" }, "竿を出して3分たったあとの値である。"),
        table([["ルアー"], ["1回の抽選でヒットする確率"], ["ヒットまでの平均", "num"]],
          summary.map((r) => h("tr", null,
            h("td", { class: "nowrap" }, trollChip(+r.lure)),
            h("td", null, bar(r.hit_per_check * 100, maxHit * 100, pct(r.hit_per_check * 100))),
            h("td", { class: "num" }, `${r[secKey]}秒`)))))),
    h("h2", null, "各色にかかる魚の割合"),
    table([["魚"], ["選ばれる確率", "num"], ...[1, 2, 3, 4, 5].map((n) => [trollChip(n), "num"])],
      fish.map(([id, rows]) => h("tr", null,
        h("td", { class: "nowrap" }, h("a", { href: `#fish/${id}` }, rows[0].fish)),
        h("td", { class: "num" }, pct(rows[0].pick_rate * 100)),
        [1, 2, 3, 4, 5].map((n) => {
          const v = +(rows.find((r) => +r.lure === n)?.share_of_hits ?? 0);
          return heatCell(v, pct(v * 100, 0));
        })))),
  ];
}

let lastView = "";
function render() {
  const [viewArg, a, b] = location.hash.slice(1).split("/").map(decodeURIComponent);
  const view = VIEWS.some(([v]) => v === viewArg) ? viewArg : "fish";
  const y = scrollY;
  tip.hidden = true;
  document.getElementById("nav").replaceChildren(...VIEWS.map(([v, text]) =>
    h("a", { href: `#${v}`, "aria-current": v === view ? "page" : null }, text)));
  try {
    const build = { fish: viewFish, map: viewMap, lure: viewLure, sure: viewSure, route: viewRoute }[view];
    main.replaceChildren(...build(a, b).flat(Infinity).filter(Boolean));
  } catch (e) {
    main.replaceChildren(h("p", { class: "error" }, `表示に失敗した: ${e.message}`));
    throw e;
  }
  scrollTo(0, view === lastView ? y : 0);
  lastView = view;
}

addEventListener("hashchange", render);
loadAll().then(render).catch((e) => {
  main.replaceChildren(h("p", { class: "error" }, `データを読み込めない: ${e.message}`));
  throw e;
});
