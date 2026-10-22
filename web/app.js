/* Dublin Protected Structures — Mapbox GL JS frontend.
 * Reads the pipeline output (data/structures.json), draws every protected
 * structure as a point coloured by when it was built, with a searchable,
 * filterable list and a detail card per building.
 */

const DATA_URL = "data/structures.json";
const DETAIL_SHARDS = 40;  // matches SHARDS in pipeline/build.py

// Build date comes from the NIAH survey; rows it hasn't covered are "unknown".
// Bright colours for the light basemap, checked with the dataviz palette
// validator against its land colour (#f7f7f8): any two eras stay distinct
// with normal colour vision. Gold and orchid are ~2.5-2.7:1 to stay bright,
// relieved by the list and card showing the exact date.
const ERAS = [
  { id: "pre1750", label: "Before 1750", color: "#d19200", max: 1749 },
  { id: "1750", label: "1750–1799", color: "#0073f8", max: 1799 },
  { id: "1800", label: "1800–1849", color: "#009a74", max: 1849 },
  { id: "1850", label: "1850–1899", color: "#cc70f2", max: 1899 },
  { id: "1900", label: "1900 on", color: "#df202e", max: Infinity },
  { id: "unknown", label: "Date unknown", color: "#94a3b8" },
];
const ERA_BY_ID = Object.fromEntries(ERAS.map((e) => [e.id, e]));

// Development Plan conservation zones (pipeline/zones.py). Not the same as
// protection: they shape how the council judges changes to an area.
const ZONES = {
  Z2: { label: "Residential Conservation Area", color: "#d97706" },
  Z8: { label: "Georgian Conservation Area", color: "#7c3aed" },
};
const ZONES_URL = "data/zones.geojson";

function eraOf(year) {
  if (!year) return "unknown";
  return ERAS.find((e) => e.max != null && year <= e.max).id;
}

// ---- State ----
let allRows = [];
const rowByKey = new Map();
let map;

const filters = {
  eras: new Set(ERAS.map((e) => e.id)),
  photoOnly: false,
  nationalOnly: false,
  showZones: true,
  search: "",
};

// ---- Search: street, number or description ----
// Abbreviations are expanded so "Leeson St" finds "Leeson Street". Street
// types are kept: Grosvenor Road and Grosvenor Square are different places.
// "St" before a name ("St Stephen's Green") is Saint and is dropped.
const GENERIC = new Set(["dublin", "the", "co", "saint"]);
const ABBREV = {
  st: "street", rd: "road", ave: "avenue", av: "avenue", sq: "square", tce: "terrace",
  pde: "parade", pl: "place", upr: "upper", lwr: "lower", nth: "north", sth: "south",
  gdns: "gardens", cres: "crescent", grn: "green", pk: "park", ln: "lane",
};

function addressWords(text) {
  const raw = text.toLowerCase()
    .replace(/dublin\s*\d+w?/g, " ")
    .replace(/['’.]/g, "")
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  return raw
    .map((w, i) => {
      // Saint when another word follows and nothing alphabetic came before it.
      const saint = w === "st" && i + 1 < raw.length && !raw.slice(0, i).some((p) => /[a-z]/.test(p));
      return saint ? "saint" : ABBREV[w] || w;
    })
    .filter((w) => !GENERIC.has(w));
}

// "7-8" -> [7, 8]; "9a" -> [9]; "1, 3 & 5" -> [1, 3, 5];
// "1-13 (odd)" and "6/12 (even nos. only)" keep one side of the street.
// Numbers written out always count ("53/55 (even)" is a slip in the source).
function houseNumbers(text) {
  const out = new Set((text.match(/\d+/g) || []).map(Number));
  const parity = /\bodd\b/i.test(text) ? 1 : /\beven\b/i.test(text) ? 0 : null;
  const sep = parity == null ? /(\d+)\s*-\s*(\d+)/g : /(\d+)\s*[-/]\s*(\d+)/g;
  for (const [, a, b] of text.matchAll(sep)) {
    if (b - a > 0 && b - a < 60) {
      for (let n = +a; n <= +b; n++) if (parity == null || n % 2 === parity) out.add(n);
    }
  }
  return out;
}

function parseQuery(q) {
  const words = addressWords(q);
  const nums = words.filter((w) => /^\d+[a-z]?$/.test(w)).map((w) => parseInt(w, 10));
  const street = words.filter((w) => !/\d/.test(w));
  // Still typing the last word? Let it match as a prefix.
  return { nums, street, prefix: !/\s$/.test(q) };
}

function streetMatches(row, query) {
  return query.street.every((w, i) =>
    row._words.has(w) ||
    (query.prefix && i === query.street.length - 1 && row._wordList.some((rw) => rw.startsWith(w))));
}

// ---- Filtering (single source of truth feeds both map + list) ----
function matchesFilters(r) {
  if (!filters.eras.has(r._era)) return false;
  if (filters.photoOnly && !r.p) return false;
  if (filters.nationalOnly && !(r.r === "National" || r.r === "International")) return false;
  return true;
}

function matchesSearch(r, query, raw) {
  if (!raw) return true;
  if (query.street.length && streetMatches(r, query) &&
      (!query.nums.length || query.nums.some((n) => r._nums.has(n)))) return true;
  return raw.length >= 3 && r.d.toLowerCase().includes(raw);
}

function activeFilterCount() {
  return (filters.eras.size < ERAS.length) + filters.photoOnly + filters.nationalOnly;
}

let fitTimer;
function applyFilters() {
  const count = activeFilterCount();
  const badge = document.getElementById("filter-count");
  badge.hidden = count === 0;
  badge.textContent = count;

  const raw = filters.search;
  const query = parseQuery(raw);
  const shown = allRows.filter((r) => matchesFilters(r) && matchesSearch(r, query, raw));
  updateMapData(shown);
  renderList(shown);
  document.getElementById("stats").textContent =
    `${shown.length.toLocaleString()} shown · ${allRows.length.toLocaleString()} protected structures`;

  // Once typing pauses: a single match opens its card, otherwise zoom to fit
  // the results.
  clearTimeout(fitTimer);
  if (map && raw && shown.length && shown.length <= 400) {
    fitTimer = setTimeout(() => {
      if (shown.length === 1) {
        if (shown[0].k !== selectedKey) openDetail(shown[0], { fly: true });
      } else {
        fitTo(shown);
      }
    }, 350);
  }
}

function fitTo(rows) {
  const b = new mapboxgl.LngLatBounds();
  rows.forEach((r) => b.extend(r.ll));
  map.fitBounds(b, { padding: 80, maxZoom: 17, duration: 600 });
}

// ---- Sidebar list ----
// Rows are paged in rather than all at once: 9,000 rows on every keystroke is
// slow, so we render PAGE_SIZE at a time behind a "Show more".
const PAGE_SIZE = 300;
let listRows = [];
let listRendered = 0;

function streetOf(r) {
  return r.n && r.a.startsWith(r.n) ? r.a.slice(r.n.length).trim() : r.a;
}

function resultRow(r) {
  const li = document.createElement("li");
  li.className = r.k === selectedKey ? "result selected" : "result";
  li.dataset.key = r.k;
  const era = ERA_BY_ID[r._era];
  const built = r.y ? ` · c.${r.y}` : "";
  li.innerHTML = `
    <span class="era-dot" style="background:${era.color}"></span>
    <div class="meta">
      <p class="name">${escapeHtml(r.a.replace(/, Dublin.*$/, ""))}</p>
      <p class="sub">${escapeHtml(r.d)}${built}</p>
    </div>`;
  li.addEventListener("click", () => {
    if (r.k === selectedKey) return closeDetail();  // click again to deselect
    openDetail(r, { fly: true });
  });
  return li;
}

function appendPage(count = PAGE_SIZE) {
  const list = document.getElementById("results");
  list.querySelector(".list-more")?.remove();

  const end = Math.min(listRendered + count, listRows.length);
  const batch = document.createDocumentFragment();
  for (let i = listRendered; i < end; i++) batch.appendChild(resultRow(listRows[i]));
  list.appendChild(batch);
  listRendered = end;

  const remaining = listRows.length - listRendered;
  if (remaining > 0) {
    const li = document.createElement("li");
    li.className = "list-more";
    li.innerHTML = `
      <button type="button">Show ${Math.min(PAGE_SIZE, remaining).toLocaleString()} more</button>
      <span class="sub">${remaining.toLocaleString()} not shown</span>`;
    li.querySelector("button").addEventListener("click", () => appendPage());
    list.appendChild(li);
  }
}

function renderList(rows) {
  listRows = [...rows].sort(byAddress);
  listRendered = 0;
  document.getElementById("results").innerHTML = "";
  document.getElementById("results").scrollTop = 0;
  appendPage();
}

function byAddress(a, b) {
  return a._street.localeCompare(b._street) || a._first - b._first || a.a.localeCompare(b.a);
}

// ---- Selection (the open building is highlighted in the list and on the map) ----
let selectedKey = null;

function setSelected(key) {
  selectedKey = key;
  const list = document.getElementById("results");
  list.querySelector(".result.selected")?.classList.remove("selected");
  document.body.classList.toggle("detail-open", key != null);
  map?.getLayer("selected") && map.setFilter("selected", ["==", ["get", "k"], key ?? ""]);
  if (key == null) return;
  const row = list.querySelector(`.result[data-key="${CSS.escape(key)}"]`);
  row?.classList.add("selected");
  row?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  setSheetExpanded(false);
}

// ---- Detail data (long NIAH text lives in shards, fetched on demand) ----
const shardCache = new Map();

function loadDetail(row) {
  const n = parseInt(row.id, 10) % DETAIL_SHARDS;
  if (!shardCache.has(n)) {
    shardCache.set(n, fetch(`data/details/${n}.json`).then((res) => res.json()).catch(() => ({})));
  }
  return shardCache.get(n).then((shard) => shard[row.k] || null);
}

// ---- Detail card (desktop: floats above the point; mobile: bottom sheet) ----
let detailLngLat = null;
const FLY_ZOOM = 17;

// Mirrors the circle-radius stops of the "points" layer, plus a gap.
function pointLift(zoom) {
  const stops = [[11, 2], [14, 4], [17, 8]];
  let r = stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [z0, r0] = stops[i - 1], [z1, r1] = stops[i];
    if (zoom >= z1) r = r1;
    else if (zoom > z0) r = r0 + ((zoom - z0) / (z1 - z0)) * (r1 - r0);
  }
  return r + 10;
}

function positionDetail() {
  const card = document.getElementById("detail");
  if (card.hidden || !detailLngLat || mobileQuery.matches) return;
  const pt = map.project(detailLngLat);
  card.style.left = `${pt.x - card.offsetWidth / 2}px`;
  card.style.top = `${pt.y - pointLift(map.getZoom()) - card.offsetHeight}px`;
}

// Pans the map just enough to bring the card fully into view, clear of the
// sidebar on the left and the map controls on the right.
function revealDetail() {
  const card = document.getElementById("detail");
  if (card.hidden || mobileQuery.matches) return;
  // Layout box, not getBoundingClientRect(): the entrance animation scales it.
  const left = card.offsetLeft, right = left + card.offsetWidth, top = card.offsetTop;
  const minX = 12 + 18 * 16 + 12, maxX = map.getContainer().clientWidth - 60, minY = 12;
  const dx = left < minX ? left - minX : right > maxX ? right - maxX : 0;
  const dy = top < minY ? top - minY : 0;
  if (dx || dy) map.panBy([dx, dy], { duration: 300 });
}

// Buildings without a NIAH photo get a satellite view of the site.
function satelliteUrl(lon, lat) {
  return `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/${lon},${lat},18.5,0,0/640x448@2x` +
    `?access_token=${window.APP_CONFIG.MAPBOX_TOKEN}`;
}

// Restarts the entrance animation, e.g. when switching between buildings.
function playEnter(card) {
  card.classList.remove("enter");
  void card.offsetWidth;
  card.classList.add("enter");
}

// r.y is already the middle of NIAH's date range (pipeline/build.py).
function builtLabel(r) {
  return r.y ? `c.${r.y}` : null;
}

function detailHtml(r, d) {
  const [lon, lat] = r.ll;
  const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
  const type = d?.original_type ? capitalise(d.original_type) : "Protected structure";
  const title = d?.name || r.a.replace(/, Dublin.*$/, "");
  const built = builtLabel(r);
  const parts = allRows.filter((x) => x.id === r.id).length;
  const primary = d?.url
    ? `<a class="btn-primary" href="${d.url}" target="_blank" rel="noopener">View on Buildings of Ireland</a>`
    : `<a class="btn-primary" href="${mapsUrl}" target="_blank" rel="noopener">Open in Google Maps</a>`;

  return `
    <div class="detail-scroll">
      <div class="detail-hero">
        <img class="hero-img" src="${d?.image || satelliteUrl(lon, lat)}" alt="${escapeHtml(title)}">
        <div class="hero-shade"></div>
        <button class="detail-close" type="button" aria-label="Close"><img src="icons/close.svg" alt=""></button>
        <div class="hero-text">
          <div class="hero-title">
            <span class="hero-badge">${escapeHtml(type)}</span>
            <h2>${escapeHtml(title)}</h2>
          </div>
          ${built ? `<div class="hero-stat"><span>${built}</span><small>built</small></div>` : ""}
        </div>
      </div>
      <div class="detail-section">
        ${d?.name ? `<p class="detail-address">${escapeHtml(r.a)}</p>` : ""}
        <p class="detail-desc">On the Record as: ${escapeHtml(r.d)}</p>
        ${parts > 1 ? `<p class="detail-note">One of ${parts} parts of this protected structure.</p>` : ""}
        ${r.z ? `<p class="detail-note"><span class="zone-swatch" style="background:${ZONES[r.z].color}"></span>In a ${ZONES[r.z].label} (${r.z})</p>` : ""}
      </div>
      ${d?.appraisal ? `
        <div class="detail-section">
          <p class="detail-desc clamp">${escapeHtml(d.appraisal)}</p>
          <button class="read-more" type="button" hidden>Read more</button>
        </div>` : ""}
      <div class="detail-actions">
        ${primary}
        ${d?.url ? `<div class="detail-links"><a href="${mapsUrl}" target="_blank" rel="noopener">Google Maps</a></div>` : ""}
      </div>
    </div>`;
}

let openToken = 0;

async function openDetail(r, { fly = false } = {}) {
  const token = ++openToken;
  const d = await loadDetail(r);
  if (token !== openToken) return;  // a newer click won

  const [lon, lat] = r.ll;
  const card = document.getElementById("detail");
  const body = document.getElementById("detail-body");
  body.innerHTML = detailHtml(r, d);

  const hero = body.querySelector(".hero-img");
  hero.addEventListener("load", () => hero.classList.add("ready"));
  hero.addEventListener("error", () => {
    const fallback = satelliteUrl(lon, lat);
    if (hero.src !== fallback) hero.src = fallback;
  });
  body.querySelector(".detail-close").addEventListener("click", closeDetail);

  card.hidden = false;
  // Long appraisals are clamped to a few lines; offer the rest if it's cut.
  const clamped = body.querySelector(".clamp");
  const more = body.querySelector(".read-more");
  if (clamped && clamped.scrollHeight > clamped.clientHeight + 1) {
    more.hidden = false;
    more.addEventListener("click", () => {
      clamped.classList.remove("clamp");
      more.remove();
    });
  }
  body.scrollTop = 0;
  playEnter(card);
  setSelected(r.k);

  detailLngLat = r.ll;
  if (fly && !mobileQuery.matches) {
    // Land with the building low enough that the card fits above it.
    const dy = (card.offsetHeight + pointLift(FLY_ZOOM)) / 2;
    card.classList.add("flying");
    map.flyTo({ center: detailLngLat, zoom: FLY_ZOOM, offset: [0, dy] });
    map.once("moveend", () => {
      card.classList.remove("flying");
      playEnter(card);
    });
  } else if (fly) {
    map.flyTo({ center: detailLngLat, zoom: FLY_ZOOM });
  }
  positionDetail();
  if (!fly) revealDetail();
}

function closeDetail() {
  openToken++;
  document.getElementById("detail").hidden = true;
  detailLngLat = null;
  setSelected(null);
}

// ---- Map ----
function toGeoJSON(rows) {
  return {
    type: "FeatureCollection",
    features: rows.map((r) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: r.ll },
      properties: { k: r.k, era: r._era },
    })),
  };
}

// The rows on the map; the source is created from these once the style loads.
let mapRows = [];
function updateMapData(rows) {
  mapRows = rows;
  map?.getSource("structures")?.setData(toGeoJSON(rows));
}

function setZonesVisible(show) {
  document.querySelector("#map-legend .legend-zones").hidden = !show;
  if (!map?.getLayer("zones-fill")) return;
  for (const id of ["zones-fill", "zones-line"]) map.setLayoutProperty(id, "visibility", show ? "visible" : "none");
}

function initMapLayers() {
  map.on("style.load", addDataLayers);

  map.on("mouseenter", "points", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "points", () => (map.getCanvas().style.cursor = ""));
  map.on("click", (e) => {
    if (!map.getLayer("points")) return;
    // A little slop so the small dots are easy to hit.
    const box = [[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]];
    const hit = map.queryRenderedFeatures(box, { layers: ["points"] })[0];
    if (!hit) return closeDetail();
    const r = rowByKey.get(hit.properties.k);
    if (r.k === selectedKey) return closeDetail();
    openDetail(r);
  });
}

// Map key: zone swatches, then the era dot colours.
function renderLegend() {
  document.querySelector("#map-legend .legend-rows").innerHTML = Object.entries(ZONES).map(([z, v]) =>
    `<span class="legend-row"><span class="zone-swatch" style="background:${v.color}"></span>${v.label} (${z})</span>`).join("");
  document.querySelector("#map-legend .legend-eras").innerHTML = ERAS.map((e) =>
    `<span class="legend-row"><span class="legend-dot" style="background:${e.color}"></span>${e.label}</span>`).join("");
}

function addDataLayers() {
  // Conservation zones sit under the points as a faint wash.
  map.addSource("zones", { type: "geojson", data: ZONES_URL });
  const zoneColor = ["match", ["get", "zone"], ...Object.entries(ZONES).flatMap(([z, v]) => [z, v.color]), "#94a3b8"];
  map.addLayer({
    id: "zones-fill",
    type: "fill",
    source: "zones",
    paint: { "fill-color": zoneColor, "fill-opacity": 0.1 },
  });
  map.addLayer({
    id: "zones-line",
    type: "line",
    source: "zones",
    paint: {
      "line-color": zoneColor,
      "line-opacity": 0.45,
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.4, 16, 1.2],
    },
  });
  setZonesVisible(filters.showZones);

  map.addSource("structures", { type: "geojson", data: toGeoJSON(mapRows) });
  const radius = ["interpolate", ["linear"], ["zoom"], 11, 2, 14, 4, 17, 8];
  map.addLayer({
    id: "points",
    type: "circle",
    source: "structures",
    paint: {
      "circle-radius": radius,
      "circle-color": ["match", ["get", "era"], ...ERAS.flatMap((e) => [e.id, e.color]), "#94a3b8"],
      "circle-stroke-color": "#fff",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 12, 0, 15, 1.2],
    },
  });
  map.addLayer({
    id: "selected",
    type: "circle",
    source: "structures",
    filter: ["==", ["get", "k"], selectedKey ?? ""],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 6, 14, 8, 17, 12],
      "circle-color": "transparent",
      "circle-stroke-color": "#0f172a",
      "circle-stroke-width": 2.5,
    },
  });
}

function initMap() {
  mapboxgl.accessToken = window.APP_CONFIG.MAPBOX_TOKEN;
  map = new mapboxgl.Map({
    container: "map",
    style: window.APP_CONFIG.MAP_STYLE,
    center: [-6.262, 53.343],  // Dublin city centre
    zoom: 12.3,
    logoPosition: "bottom-right",  // bottom-left sits under the sidebar
  });
  // Keep the map's centre (and flyTo targets) clear of the floating panel.
  if (!mobileQuery.matches) map.setPadding({ left: 18 * 16 + 12 });
  map.addControl(new mapboxgl.NavigationControl(), "top-right");
  map.addControl(new mapboxgl.GeolocateControl({ trackUserLocation: true }), "top-right");
  initMapLayers();
  map.on("move", positionDetail);
  map.on("resize", positionDetail);
  applyFilters();
}

// ---- Panel chrome: squircle corners, mobile bottom sheet ----
const mobileQuery = window.matchMedia("(max-width: 767px)");

function setSheetExpanded(expanded) {
  const sidebar = document.getElementById("sidebar");
  const handle = document.getElementById("sheet-handle");
  sidebar.classList.toggle("expanded", expanded);
  handle.setAttribute("aria-expanded", String(expanded));
  handle.querySelector(".hint").textContent = expanded ? "Tap to collapse" : "Tap to expand";
}

function initPanel() {
  const sidebar = document.getElementById("sidebar");
  const reclip = squircle(sidebar, () => ({ r: 28, topOnly: mobileQuery.matches }));
  const reclipDetail = squircle(document.getElementById("detail-body"),
    () => ({ r: 28, topOnly: mobileQuery.matches }), document.querySelector(".detail-outline"));
  mobileQuery.addEventListener("change", () => {
    reclip();
    reclipDetail();
    // The bottom sheet is placed by CSS; the floating card by positionDetail().
    const card = document.getElementById("detail");
    card.style.left = card.style.top = "";
    positionDetail();
  });

  const toggle = document.getElementById("filter-toggle");
  toggle.addEventListener("click", () => {
    const open = document.getElementById("filter-panel").classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  document.getElementById("sheet-handle").addEventListener("click", () =>
    setSheetExpanded(!sidebar.classList.contains("expanded")));
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDetail();
  });
}

// ---- Controls wiring ----
function buildControls() {
  const chips = document.getElementById("era-filters");
  for (const e of ERAS) {
    const label = document.createElement("label");
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" value="${e.id}" checked>
      <span class="dot" style="background:${e.color}"></span>${e.label}`;
    label.querySelector("input").addEventListener("change", (ev) => {
      ev.target.checked ? filters.eras.add(e.id) : filters.eras.delete(e.id);
      applyFilters();
    });
    chips.appendChild(label);
  }

  const bind = (id, key) =>
    document.getElementById(id).addEventListener("change", (e) => {
      filters[key] = e.target.checked;
      applyFilters();
    });
  bind("photo-only", "photoOnly");
  bind("national-only", "nationalOnly");
  document.getElementById("show-zones").addEventListener("change", (e) => {
    filters.showZones = e.target.checked;
    setZonesVisible(filters.showZones);
  });

  const legend = document.getElementById("map-legend");
  renderLegend();
  legend.querySelector(".legend-more").addEventListener("click", () => {
    const open = legend.classList.toggle("open");
    legend.querySelector(".legend-more").setAttribute("aria-expanded", String(open));
  });

  let t;
  document.getElementById("search").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      filters.search = e.target.value.toLowerCase().replace(/^\s+/, "");
      applyFilters();
    }, 150);
  });
}

function capitalise(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// A real Mapbox public token starts with "pk." and isn't the .env placeholder.
function hasValidToken() {
  const t = window.APP_CONFIG?.MAPBOX_TOKEN || "";
  return t.startsWith("pk.") && t !== "pk.your_public_token_here";
}

// ---- Boot ----
async function boot() {
  if (!hasValidToken()) {
    document.getElementById("token-warning").hidden = false;
  }

  initPanel();
  buildControls();

  try {
    const res = await fetch(DATA_URL);
    allRows = await res.json();
  } catch (err) {
    document.getElementById("stats").textContent =
      "Could not load data — run python3 serve.py and open the page it prints.";
    console.error(err);
    return;
  }
  for (const r of allRows) {
    r._era = eraOf(r.y);
    r._street = streetOf(r).replace(/, Dublin.*$/, "").toLowerCase();
    r._nums = houseNumbers(r.n || "");
    r._first = Math.min(...r._nums, Infinity);
    r._wordList = addressWords(streetOf(r));
    r._words = new Set(r._wordList);
    rowByKey.set(r.k, r);
  }
  document.getElementById("photo-count").textContent =
    allRows.filter((r) => r.p).length.toLocaleString();
  document.getElementById("national-count").textContent =
    allRows.filter((r) => r.r === "National" || r.r === "International").length.toLocaleString();

  if (hasValidToken()) {
    initMap();
  } else {
    // No token: still show the searchable list so the data is usable.
    applyFilters();
  }
}

boot();
