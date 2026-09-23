/* CNAS console.
   One page, five views. The only stateful thing on the client is the selected
   role, which is sent as a header; every access decision is taken server-side. */

const S = {
  role: "standard_officer",
  cases: [], findings: [], families: {},
  currentCase: null, cy: null,
  filterFamily: null, filterStatus: null,
  lastEgo: null, chainMode: false,
};

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (n) => "₹ " + Number(n).toLocaleString("en-IN");

/* Mechanism parameters are read by people, so they are printed as values
   rather than as the JSON the mechanism happened to store them in. */
function param(v) {
  if (Array.isArray(v)) return v.join(", ");
  if (v && typeof v === "object") {
    return Object.entries(v).map(([k, x]) => `${k.replace(/_/g, " ")} ${x}`).join(", ");
  }
  return String(v);
}

/* ====================================================================== icons */
/* Record-type pictograms, drawn on a 24-unit grid as strokes rather than fills:
   a stroked shape keeps its weight when it is scaled down onto a 34px node and
   still reads across a lecture theatre. One definition serves the graph, the
   legend and the chain cards, so a node type cannot be drawn two ways. */
const ICON_PATHS = {
  person:
    '<circle cx="12" cy="7.6" r="3.9"/>' +
    '<path d="M4.4 20.4c0-4 3.4-6.3 7.6-6.3s7.6 2.3 7.6 6.3"/>',
  phone:
    '<rect x="6.2" y="2.4" width="11.6" height="19.2" rx="2.2"/>' +
    '<path d="M10.4 5.4h3.2"/><path d="M12 18.4v.05"/>',
  bank:
    '<path d="M2.6 9.6 12 4l9.4 5.6"/><path d="M4.6 9.6v8.2M19.4 9.6v8.2"/>' +
    '<path d="M8.6 11.8v6M15.4 11.8v6"/><path d="M2.6 20.8h18.8"/>',
  vehicle:
    '<path d="M5.8 12.2 7.3 8.4A2.1 2.1 0 0 1 9.3 7.1h5.4a2.1 2.1 0 0 1 2 1.3l1.5 3.8"/>' +
    '<rect x="3" y="12.2" width="18" height="4.6" rx="1.4"/>' +
    '<circle cx="7.4" cy="19" r="1.8"/><circle cx="16.6" cy="19" r="1.8"/>',
  pin:
    '<path d="M12 21.4s6.8-6.2 6.8-11a6.8 6.8 0 1 0-13.6 0c0 4.8 6.8 11 6.8 11Z"/>' +
    '<circle cx="12" cy="10.2" r="2.5"/>',
  case:
    '<path d="M3 7.4a1.6 1.6 0 0 1 1.6-1.6h4.2l2.1 2.5h8.5A1.6 1.6 0 0 1 21 9.9v8.5' +
    'a1.6 1.6 0 0 1-1.6 1.6H4.6A1.6 1.6 0 0 1 3 18.4Z"/>',
  document:
    '<path d="M13.8 2.8H7a2 2 0 0 0-2 2v14.4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/>' +
    '<path d="M13.8 2.8V8H19"/><path d="M8.8 13h6.4M8.8 16.8h6.4"/>',
  valuables:
    '<path d="M6.2 3.2h11.6l3.2 5.4L12 20.8 3 8.6Z"/>' +
    '<path d="M3 8.6h18"/><path d="M9.4 8.6 12 3.2l2.6 5.4L12 20.8Z"/>',
  crate:
    '<path d="M3.2 8.2 12 3.8l8.8 4.4v7.6L12 20.2l-8.8-4.4Z"/>' +
    '<path d="m3.2 8.2 8.8 4.4 8.8-4.4"/><path d="M12 12.6v7.6"/>',
  screen:
    '<rect x="2.6" y="4" width="18.8" height="12.6" rx="1.8"/>' +
    '<path d="M8.6 20.6h6.8M12 16.6v4"/>',
  person_alert:
    '<circle cx="9.6" cy="7.4" r="3.7"/>' +
    '<path d="M2.8 20.4c0-3.9 3.1-6.1 6.8-6.1 1.1 0 2.1.2 3 .5"/>' +
    '<path d="M18.6 10.4v5.2"/><path d="M18.6 19.4v.05"/>',
};

function iconBody(name) {
  return ICON_PATHS[name] || ICON_PATHS.document;
}

/* Cytoscape carries one label per node and the record's name is already using
   it, so the pictogram goes into the node body as a background image. Eleven
   icons exist, so each is built once and reused. "white" rather than "#fff":
   an unencoded hash terminates a data URI. */
const iconCache = {};
function iconImage(name) {
  if (!iconCache[name]) {
    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="48" height="48" ` +
      `fill="none" stroke="white" stroke-width="1.9" stroke-linecap="round" ` +
      `stroke-linejoin="round">${iconBody(name)}</svg>`;
    iconCache[name] = "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  }
  return iconCache[name];
}

/* The same pictogram inline, for the legend swatches and the chain cards. */
function iconMarkup(name, size = 15) {
  return `<svg class="ic" viewBox="0 0 24 24" width="${size}" height="${size}" ` +
    `aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" ` +
    `stroke-linecap="round" stroke-linejoin="round">${iconBody(name)}</svg>`;
}

/* How many findings cite a given record. Drives the ring on the node: it is a
   count of evidence, not a score of the person. */
function citationCounts() {
  const counts = {};
  S.findings.forEach(f => {
    const ids = new Set([...(f.subject_ids || []),
                         ...(f.evidence || []).map(e => e.node_id)]);
    ids.forEach(i => { counts[i] = (counts[i] || 0) + 1; });
  });
  return counts;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-CNAS-Role": S.role, ...(opts.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail; } catch (e) { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return res.json();
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show " + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = "toast " + kind; }, 3200);
}

/* Reports come back as a Word document, so they are fetched rather than linked:
   a plain href would not carry the role header the server filters on. */
async function download(path, fallbackName, button) {
  const label = button ? button.textContent : null;
  if (button) { button.disabled = true; button.textContent = "Preparing…"; }
  try {
    const res = await fetch(path, { headers: { "X-CNAS-Role": S.role } });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail; } catch (e) { /* not JSON */ }
      throw new Error(detail);
    }
    const blob = await res.blob();
    const name = res.headers.get("X-CNAS-Filename") || fallbackName;
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    toast(`${name} downloaded.`, "good");
  } catch (e) {
    toast("Export failed: " + e.message, "bad");
  } finally {
    if (button) { button.disabled = false; button.textContent = label; }
  }
}

/* ====================================================================== tabs */
function showView(name) {
  $$(".tab").forEach(b => {
    const on = b.dataset.view === name;
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + name));
  if (name === "audit") loadAudit();
  if (name === "queue") renderQueue();
  if (name === "intake" && !S.intakeSchema) loadIntakeSchema();
  if (name === "emergency") setTimeout(() => $("#emgInput").focus(), 40);
  if (name === "workspace" && S.cy) setTimeout(() => S.cy.resize(), 60);
}

/* =================================================================== session */
async function loadSession() {
  const s = await api("/api/session");
  const sel = $("#roleSelect");
  if (!sel.options.length) {
    sel.innerHTML = s.roles.map(r =>
      `<option value="${r.id}">${esc(r.display)}</option>`).join("");
    sel.value = S.role;
  }
  $("#unitLabel").textContent = s.principal.unit;
  return s;
}

/* ================================================================== overview */
async function loadOverview() {
  const o = await api("/api/overview");
  S.cases = o.cases;

  $("#caseList").innerHTML = o.cases.map(c => `
    <button class="caseitem" data-id="${c.id}">
      <div class="ct">${esc(c.props.title)}</div>
      <div class="cm">${c.id} &middot; ${esc(c.props.district)}</div>
    </button>`).join("");
  $$("#caseList .caseitem").forEach(b =>
    b.onclick = () => selectCase(b.dataset.id));

  // The only count worth standing on its own: records this officer is not
  // being shown. Everything else is already on the nav badge or the graph footer.
  $("#withheldSection").hidden = !o.hidden_from_you;
  $("#withheld").textContent = o.hidden_from_you
    ? `${o.hidden_from_you} record${o.hidden_from_you === 1 ? "" : "s"} withheld at your tier`
    : "";
  $("#pendingPill").textContent = o.pending;
}

async function loadFindings() {
  const r = await api("/api/findings");
  S.findings = r.findings;
  S.families = r.families;
}

/* ================================================================= workspace */
function markCase(caseId) {
  S.currentCase = caseId;
  $$("#caseList .caseitem").forEach(b =>
    b.classList.toggle("sel", b.dataset.id === caseId));
}

async function selectCase(caseId) {
  if (S.flash && S.flash.caseId !== caseId) S.flash = null;
  markCase(caseId);
  const c = S.cases.find(x => x.id === caseId);
  if (c) {
    $("#canvasTitle").textContent = c.props.title;
    $("#canvasSub").textContent =
      `${c.id} · ${c.props.district} · ${c.props.crime} · opened ${c.props.opened}`;
  }
  await drawEgo(caseId);
  renderWorkspaceFindings();
}

async function drawEgo(nodeId) {
  const hops = +$("#hopSelect").value;
  const data = await api(`/api/ego-network/${encodeURIComponent(nodeId)}?hops=${hops}`);
  setChainMode(false);
  S.lastEgo = data;
  $("#queryStat").textContent =
    `${data.nodes.length} records · ${data.edges.length} relationships`
    + (data.truncated ? ` · bounded at ${data.cap}` : "");
  renderGraph(data, nodeId);
  markFlash();
  renderLegend(data);
  renderTimeline(data.timeline);
}

function renderGraph(data, centerId, layoutOverride) {
  // Size carries betweenness and the ring carries how many findings cite the
  // record. Neither is a judgement about the person: one is a position in the
  // network, the other is a count of evidence.
  const maxBtw = data.max_betweenness || 0;
  const cites = citationCounts();
  const els = [
    ...data.nodes.map(n => ({
      data: {
        id: n.id, label: n.display, kind: n.label, color: n.color,
        tier: n.tier, center: n.id === centerId ? 1 : 0,
        icon: iconImage(n.icon),
        // The floor is set by the pictogram, not by taste: it has to stay
        // readable inside the smallest circle on the canvas.
        size: maxBtw > 0 ? 34 + 22 * ((n.betweenness || 0) / maxBtw) : 36,
        cites: cites[n.id] || 0,
      },
    })),
    ...data.edges.map(e => ({
      data: { id: e.id, source: e.source, target: e.target, label: e.type, tier: e.tier },
    })),
  ];

  // The instance is built once and then refilled. Destroying it between draws
  // leaves any layout still animating to tick against a graph that no longer
  // exists, which throws from inside Cytoscape on a fast second click.
  if (S.cy) {
    stopLayout();
    S.cy.elements().remove();
    S.cy.add(els);
    runLayout(layoutOverride);
    return;
  }

  S.cy = cytoscape({
    container: $("#cy"),
    elements: els,
    wheelSensitivity: 0.22,
    style: [
      { selector: "node", style: {
        "background-color": "data(color)",
        "background-image": "data(icon)",
        "background-fit": "none",
        "background-clip": "none",
        // Proportional, so the pictogram grows with a high-betweenness node
        // instead of rattling around inside it.
        "background-width": "62%", "background-height": "62%",
        "label": "data(label)",
        "color": "#1f2328",
        "font-size": 10,
        "font-family": "Segoe UI, system-ui, sans-serif",
        "text-valign": "bottom",
        "text-margin-y": 5,
        "text-wrap": "wrap",
        "text-max-width": 96,
        "width": "data(size)", "height": "data(size)",
        "border-width": 1.5,
        "border-color": "#ffffff",
        "text-outline-width": 3,
        "text-outline-color": "#f6f7f9",
      }},
      // Cited by at least one finding. A ring, not a colour: the node keeps
      // saying what kind of record it is.
      { selector: 'node[cites > 0]', style: {
        "border-width": 3.5, "border-color": "#a32020",
      }},
      // The centre of the ego view is marked by its outline, not by its size -
      // size is spoken for.
      { selector: 'node[center = 1]', style: {
        "border-width": 4, "border-color": "#1b3a5f",
        "font-size": 12, "font-weight": 700,
      }},
      { selector: 'node[tier = "restricted"]', style: {
        "border-color": "#7a1f4b", "border-width": 3, "border-style": "dashed",
      }},
      { selector: "edge", style: {
        "width": 1.1, "line-color": "#b8bfc8",
        "target-arrow-color": "#b8bfc8", "target-arrow-shape": "triangle",
        "arrow-scale": 0.62, "curve-style": "bezier",
        "label": "data(label)", "font-size": 8, "color": "#6b7480",
        "text-rotation": "autorotate", "text-outline-width": 3,
        "text-outline-color": "#f6f7f9",
      }},
      { selector: 'edge[label = "SAME_AS"]', style: {
        "line-color": "#1a4f8a", "target-arrow-color": "#1a4f8a",
        "line-style": "dashed", "width": 2, "color": "#1a4f8a",
      }},
      { selector: 'edge[tier = "restricted"]', style: {
        "line-color": "#7a1f4b", "target-arrow-color": "#7a1f4b", "color": "#7a1f4b",
      }},
      // Just ingested.
      { selector: "node.new", style: {
        "border-width": 5, "border-color": "#15683c", "font-weight": 700,
      }},
      // Already on file, and what the ingested record attached itself to.
      { selector: "node.linked", style: {
        "border-width": 5, "border-color": "#1a4f8a", "border-style": "double",
        "font-weight": 700,
      }},
      { selector: ".dim", style: { "opacity": 0.15 } },
      { selector: ".hot", style: {
        "background-color": "#a32020", "line-color": "#a32020",
        "target-arrow-color": "#a32020", "width": 3, "opacity": 1,
        "border-color": "#a32020", "color": "#a32020", "z-index": 99,
      }},
      // Highlight does not resize: size means betweenness at all times.
      { selector: 'node.hot', style: { "font-size": 12, "font-weight": 700,
        "border-color": "#ffffff" } },
    ],
  });

  runLayout(layoutOverride);
  S.cy.on("tap", "node", evt => showNode(evt.target.id()));
  S.cy.on("tap", e => { if (e.target === S.cy) clearHighlight(); });
}

/* After an ingestion, which records are new and which were already on file.
   The second set is the interesting one - a new case whose whole neighbourhood
   is also new has not attached to anything. */
function markFlash() {
  if (!S.cy || !S.flash) return;
  S.cy.nodes().forEach(n => {
    if (S.flash.created.has(n.id())) n.addClass("new");
    else if (S.flash.attached.has(n.id())) n.addClass("linked");
  });
}

function stopLayout() {
  if (S.layout) { try { S.layout.stop(); } catch (e) { /* already finished */ } }
  S.layout = null;
}

function runLayout(opts) {
  if (!S.cy) return;
  stopLayout();
  S.layout = S.cy.layout(opts || layoutOpts());
  S.layout.run();
}

function layoutOpts() {
  const name = $("#layoutSelect").value;
  // Labels hang below each node, so the layout has to treat them as part of
  // the node. Without this the algorithms space 20px circles and the names
  // print straight over one another.
  const base = {
    name, animate: true, animationDuration: 420, padding: 44,
    nodeDimensionsIncludeLabels: true, avoidOverlap: true,
  };
  if (name === "cose") return {
    ...base,
    // Tight enough that the graph fills the canvas rather than being fitted
    // down to a smear; label collisions are handled by the layout counting
    // each label as part of its node, not by pushing everything apart.
    nodeRepulsion: 17000, idealEdgeLength: 106, nodeOverlap: 28,
    componentSpacing: 90, gravity: 0.45, numIter: 1500, randomize: false,
  };
  if (name === "concentric") return {
    ...base, concentric: n => n.degree(), levelWidth: () => 2, minNodeSpacing: 54,
  };
  if (name === "breadthfirst") return { ...base, spacingFactor: 1.4, directed: false };
  return base;
}

/* ================================================================= timeline */
/* Only edges that record an event are plotted. An account's opening date and
   an address association are dated facts rather than things that happened, and
   the server decides which is which: see config.EVENT_EDGE_TYPES. */
const DAY = 86400000;
const shortDate = (iso) => new Date(iso).toLocaleDateString("en-IN",
  { day: "numeric", month: "short", year: "numeric" });

function renderTimeline(events) {
  const el = $("#timeline");
  if (!events || !events.length) {
    el.innerHTML = `<p class="empty small">No dated events in this network.</p>`;
    return;
  }

  // Case events are dated to the day and several routinely share one - three
  // records entering the same FIR, for instance. Plotted individually they sit
  // on top of each other and the reader cannot count them, so a day is one
  // marker carrying its own count.
  const byDay = {};
  events.forEach(e => {
    const d = e.event_time.slice(0, 10);
    (byDay[d] = byDay[d] || []).push(e);
  });
  const days = Object.keys(byDay).sort();
  const lo = new Date(days[0]).getTime();
  const hi = new Date(days[days.length - 1]).getTime();
  const span = hi - lo;
  const pct = ms => (span ? 4 + 92 * ((ms - lo) / span) : 50);

  // Interior month ticks only where there is room for them; the two endpoints
  // are always dated, so the axis is readable even over a single week.
  const ticks = [`<span class="tltick end" style="left:0">${esc(shortDate(days[0]))}</span>`];
  if (span >= 75 * DAY) {
    // A span crossing a year boundary needs the year on every tick, or two
    // Aprils read as one. Wide spans also get a tick every quarter rather than
    // every month, so the labels do not run into each other.
    const months = Math.round(span / (30 * DAY));
    const step = months > 30 ? 6 : months > 14 ? 3 : 1;
    const fmt = span > 300 * DAY
      ? { month: "short", year: "2-digit" } : { month: "short" };
    const d = new Date(lo);
    d.setDate(1);
    d.setMonth(d.getMonth() + step);
    while (d.getTime() <= hi - 30 * DAY) {
      if (d.getTime() >= lo + 30 * DAY) {
        ticks.push(`<span class="tltick" style="left:${pct(d.getTime())}%">` +
          `${d.toLocaleDateString("en-IN", fmt)}</span>`);
      }
      d.setMonth(d.getMonth() + step);
    }
  }
  if (days.length > 1) {
    ticks.push(`<span class="tltick end right" style="right:0">` +
      `${esc(shortDate(days[days.length - 1]))}</span>`);
  }

  el.innerHTML =
    `<div class="tlaxis">${ticks.join("")}</div>` +
    `<div class="tltrack">` +
    days.map(d => {
      const group = byDay[d];
      const color = (S.lastEgo.nodes.find(n => n.id === group[0].src) || {}).color || "#6b7480";
      // Both times, because the gap between them is the claim: when it
      // happened, and when this system learnt of it.
      const title = `${shortDate(d)}\n` + group.map(e =>
        `${e.type}: ${e.src_display} -> ${e.dst_display}\n  ingested ` +
        `${(e.ingested_time || "").replace("T", " ")}`).join("\n");
      return `<button class="tlev" data-day="${d}"
        style="left:${pct(new Date(d).getTime())}%;background:${color}"
        title="${esc(title)}">${group.length > 1 ? group.length : ""}
        <span class="sr">${esc(shortDate(d))}, ${group.length} event${group.length === 1 ? "" : "s"}</span>
      </button>`;
    }).join("") +
    `</div>`;

  $$("#timeline .tlev").forEach(b => b.onclick = () => {
    if (!S.cy) return;
    const group = byDay[b.dataset.day];
    const ids = new Set(group.flatMap(e => [e.src, e.dst]));
    const edgeIds = new Set(group.map(e => e.edge_id));
    S.cy.elements().addClass("dim").removeClass("hot");
    S.cy.nodes().filter(n => ids.has(n.id())).removeClass("dim").addClass("hot");
    S.cy.edges().filter(e => edgeIds.has(e.id())).removeClass("dim").addClass("hot");
    $$("#timeline .tlev").forEach(o => o.classList.toggle("on", o === b));
  });
}

/* The size and ring keys describe the canvas, so they are omitted in chain
   mode where there is no canvas to describe. */
function renderLegend(data, withEncoding = true) {
  const kinds = {};
  data.nodes.forEach(n => { kinds[n.label] = { color: n.color, icon: n.icon }; });
  $("#legend").innerHTML = Object.entries(kinds)
    .map(([k, s]) =>
      `<span class="lg"><i style="background:${s.color}">${iconMarkup(s.icon, 12)}</i>${esc(k)}</span>`)
    .join("") + (withEncoding
      ? `<span class="lg enc">Size: betweenness, whole network</span>` +
        `<span class="lg"><i class="ring"></i>Cited by a finding</span>` +
        (S.flash ? `<span class="lg"><i class="ring new"></i>Just ingested</span>` +
          `<span class="lg"><i class="ring linked"></i>Matched, already on file</span>` : "")
      : "");
}

function clearHighlight() {
  if (S.cy) S.cy.elements().removeClass("dim hot");
}

/* ============================================================ chain swimlane */
const humanise = (s) => {
  const t = String(s).replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/* What each hop is, in the terms the record itself uses. Every value here is a
   field already on the node: nothing about the chain is narrated by the UI. */
function chainCaption(n) {
  const p = n.props || {};
  const parts = {
    Case: [p.crime, p.district],
    Person: [p.role_in_case && humanise(p.role_in_case), p.occupation],
    BankAccount: [p.flag && humanise(p.flag), p.bank],
    Phone: [p.subscriber, p.operator],
    Vehicle: [p.make, p.owner],
    SmugglingConsignment: [p.bill_of_entry, p.declared_as],
    StolenProperty: [p.description, p.valuation && inr(p.valuation)],
  }[n.label] || [];
  const out = parts.filter(Boolean);
  return out.length ? out.join(" · ") : n.label;
}

function renderChainStrip(chain) {
  const dated = (t) => (t || "").slice(0, 10);
  $("#chainstrip").innerHTML = chain.nodes.map((n, i) => {
    const e = chain.edges[i];
    return `
      <div class="chainstep">
        <button class="chaincard" data-node="${esc(n.id)}">
          <span class="chainno">${i + 1}</span>
          <span class="chainglyph" style="background:${n.color}"
                title="${esc(n.label)}">${iconMarkup(n.icon, 15)}</span>
          <span class="chainname">${esc(n.display)}</span>
          <span class="chaincap">${esc(chainCaption(n))}</span>
        </button>
      </div>
      ${e ? `<div class="chainlink">
        <span class="chainrel">${esc(e.type)}</span>
        <span class="chaindate">${esc(dated(e.event_time))}</span>
      </div>` : ""}`;
  }).join("");
  $$("#chainstrip .chaincard").forEach(el =>
    el.onclick = () => showNode(el.dataset.node));
}

/* Chain mode replaces the case view rather than sitting inside it. The path is
   five hops long, further than any depth the ego view offers, and a six-node
   line rendered as a force graph is a worse drawing of itself: the strip shows
   every node, every relationship and every date, so the canvas stands down. */
function setChainMode(on) {
  S.chainMode = on;
  $("#chainstrip").hidden = !on;
  $("#cy").hidden = on;
  $("#btnBackToCase").hidden = !on;
  $("#btnChain").hidden = on;
  // Controls describing an ego view that is not on screen.
  $("#hopSelect").disabled = on;
  $("#layoutSelect").disabled = on;
  $("#btnFit").hidden = on;
  // The strip already carries a date between every pair of hops.
  $("#timelineWrap").hidden = on;
}

/* Findings that touch anything in the network currently on screen. */
function findingsOnNetwork() {
  if (!S.lastEgo) return [];
  const ids = new Set(S.lastEgo.nodes.map(n => n.id));
  return S.findings.filter(f =>
    (f.subject_ids || []).some(i => ids.has(i)) ||
    (f.evidence || []).some(e => ids.has(e.node_id)));
}

function renderWorkspaceFindings() {
  const list = findingsOnNetwork();
  $("#wsFindings").innerHTML = list.map(f => `
    <button class="mini ${f.tier === "restricted" ? "restricted" : ""}" data-id="${f.finding_id}">
      <div class="mf">${esc(f.family_label)}</div>
      <div class="mt">${esc(f.finding_type)}</div>
    </button>`).join("") ||
    `<p class="empty">No findings on this network.</p>`;
  $$("#wsFindings .mini").forEach(el =>
    el.onclick = () => showFinding(el.dataset.id));
}

/* ============================================================ detail panels */
function clearPanel() {
  $("#panel").innerHTML = `<p class="empty">Select a case, a record on the graph, or a finding.</p>`;
  clearHighlight();
}

function revealPanel() {
  if (window.matchMedia("(max-width:1100px)").matches) {
    $("#panelWrap").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function showNode(nodeId) {
  let n;
  try { n = await api(`/api/node/${encodeURIComponent(nodeId)}`); }
  catch (e) { toast(e.message, "bad"); return; }

  const props = Object.entries(n.props)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(v)}</dd>`).join("");

  const resolved = (n.resolved_from || []).length > 1 ? `
    <div class="sec">
      <h4>Resolved from ${n.resolved_from.length} records</h4>
      <div class="evlist">${n.resolved_from.map(r =>
        `<div class="ev" data-node="${r}"><div class="evid">${r}</div></div>`).join("")}</div>
    </div>` : "";

  $("#panel").innerHTML = `
    <div class="phead">
      <div class="ptype">${esc(n.label)} ${n.tier !== "standard"
        ? `<span class="badge b-${n.tier}">${n.tier}</span>` : ""}</div>
      <div class="pstatement">${esc(n.display)}</div>
    </div>
    <div class="sec"><h4>Attributes</h4><dl class="kv">${props}
      <dt>source record</dt><dd class="mono">${esc(n.source_record_id)}</dd></dl></div>
    ${resolved}
    ${n.cases && n.cases.length ? `
      <div class="sec"><h4>Appears in</h4><div class="evlist">
        ${n.cases.map(c => `<div class="ev" data-node="${c.id}">
          <div class="evtop"><span class="evid">${c.id}</span>
            <span class="evlabel">${esc(c.props.district || "")}</span></div>
          <div class="evrole">${esc(c.props.title || "")}</div></div>`).join("")}
      </div></div>` : ""}
    <div class="actions">
      <button class="btn" id="btnExpand">Centre the graph here</button>
    </div>`;

  $$("#panel .ev[data-node]").forEach(el =>
    el.onclick = () => showNode(el.dataset.node));
  const be = $("#btnExpand");
  if (be) be.onclick = () => drawEgo(nodeId).then(renderWorkspaceFindings);
  revealPanel();
}

function findingById(id) { return S.findings.find(f => f.finding_id === id); }

function showFinding(id) {
  const f = findingById(id);
  if (!f) return;
  $("#panel").innerHTML = explainHTML(f);
  wireExplain($("#panel"), f);
  highlightFinding(f);
  revealPanel();
}

function highlightFinding(f) {
  if (!S.cy) return;
  const ids = new Set([...(f.subject_ids || []), ...(f.evidence || []).map(e => e.node_id)]);
  const present = S.cy.nodes().filter(n => ids.has(n.id()));
  if (!present.length) return;
  S.cy.elements().addClass("dim").removeClass("hot");
  present.removeClass("dim").addClass("hot");
  present.connectedEdges().filter(e =>
    ids.has(e.source().id()) && ids.has(e.target().id()))
    .removeClass("dim").addClass("hot");
}

/* ===================================== the Explainability Contract, rendered */
function explainHTML(f) {
  return `
    <div class="phead">
      <div class="ptype">
        <span>${esc(f.family_label)}</span>
        ${f.tier !== "standard" ? `<span class="badge b-${f.tier}">${f.tier}</span>` : ""}
        <span class="badge b-${f.status}">${f.status}</span>
      </div>
      <h3>${esc(f.finding_type)}</h3>
      <div class="pstatement">${esc(f.statement)}</div>
    </div>

    <div class="sec">
      <h4>Confidence</h4>
      <div class="confnum">${f.confidence.toFixed(3)}</div>
      <div class="confmeaning">${esc(f.confidence_meaning)}</div>
    </div>

    <div class="sec">
      <h4>Evidence &mdash; ${f.evidence.length} record${f.evidence.length === 1 ? "" : "s"}</h4>
      <div class="evlist">
        ${f.evidence.map(e => `
          <div class="ev" data-node="${e.node_id}">
            <div class="evtop">
              <span class="evid">${esc(e.node_id)}</span>
              <span class="evlabel">${esc(e.label)}</span>
            </div>
            <div class="evrole">${esc(e.role)}</div>
            <div class="evsrc">${esc(e.source_record_id)}</div>
          </div>`).join("")}
      </div>
    </div>

    <div class="sec">
      <details class="fold">
        <summary><h4>Mechanism and parameters</h4></summary>
        <dl class="kv">
          <dt>mechanism</dt><dd class="mono">${esc(f.mechanism)}</dd>
          <dt>version</dt><dd class="mono">${esc(f.model_version)}</dd>
          ${Object.entries(f.mechanism_params).map(([k, v]) =>
            `<dt>${esc(k.replace(/_/g, " "))}</dt><dd class="mono">${esc(param(v))}</dd>`).join("")}
        </dl>
      </details>
    </div>

    ${mechanismExtras(f)}

    ${(f.contributing_merges || []).length ? `
      <div class="sec">
        <details class="fold">
          <summary><h4>Merges behind this finding
            <span class="foldn">${f.contributing_merges.length}</span></h4></summary>
          <div class="evlist">
            ${f.contributing_merges.map(m => `
              <div class="ev"><div class="evid">${esc(m)}</div>
                <div class="evrole">reversible entity resolution decision</div></div>`).join("")}
          </div>
        </details>
      </div>` : ""}

    <div class="sec">
      <h4>Known limitations</h4>
      <div class="limit">${esc(f.limitations)}</div>
    </div>

    ${decisionHTML(f)}`;
}

function decisionHTML(f) {
  const exportBtn =
    `<button class="btn small" data-export="${f.finding_id}">Export finding</button>`;
  if (f.status !== "pending") {
    return `<div class="sec"><h4>Decision</h4>
      <div class="decided">
        <b>${esc(f.status)}</b> by ${esc(f.decided_by || "")} on
        ${esc((f.decided_at || "").replace("T", " "))}<br>
        <span class="muted">${esc(f.decision_reason || "")}</span>
      </div>
      <div class="actions">
        <button class="btn" data-reopen="${f.finding_id}">Reopen</button>
        ${exportBtn}
      </div>
    </div>`;
  }
  return `<div class="sec">
    <h4>Decision</h4>
    <textarea class="reasonbox" data-reason="${f.finding_id}"
      placeholder="Reason — required to reject, recorded either way"></textarea>
    <div class="actions">
      <button class="btn ok" data-confirm="${f.finding_id}">Confirm</button>
      <button class="btn danger" data-reject="${f.finding_id}">Reject</button>
      ${exportBtn}
    </div>
  </div>`;
}

/* mechanism-specific evidence displays */
function mechanismExtras(f) {
  const x = f.extra || {};

  if (f.mechanism === "statistical.benford" && x.suspect) {
    const s = x.suspect, c = x.control || {};
    const rows = s.observed.map((o, i) => {
      const e = s.expected[i], max = Math.max(...s.observed, ...s.expected);
      return `<div class="barrow">
        <span>${i + 1}</span>
        <span class="bartrack"><i class="obs" style="width:${(o / max) * 100}%"></i></span>
        <span class="bartrack"><i class="exp" style="width:${(e / max) * 100}%"></i></span>
      </div>`;
    }).join("");
    return `<div class="sec">
      <h4>First-digit distribution</h4>
      <div class="barrow" style="margin-bottom:4px">
        <span>d</span><span>observed</span><span>expected</span></div>
      <div class="bars">${rows}</div>
      <dl class="kv" style="margin-top:12px">
        <dt>n</dt><dd>${s.n}</dd>
        <dt>orders of mag.</dt><dd>${s.orders_of_magnitude}</dd>
        <dt>MAD</dt><dd>${s.mad} (threshold ${f.mechanism_params.mad_threshold_suspect})</dd>
        <dt>chi-square</dt><dd>${s.chi2} (crit. ${s.critical_value_chi2_p01} at p=.01)</dd>
        <dt>verdict</dt><dd style="color:var(--bad)">${s.verdict}</dd>
        <dt>control group</dt><dd style="color:var(--good)">${c.verdict || "n/a"} (n=${c.n || 0})</dd>
      </dl></div>`;
  }

  if (f.mechanism === "timeseries.cusum" && x.series) {
    const max = Math.max(...x.series.map(p => p.credit));
    const bars = x.series.map((p, i) =>
      `<i class="${i >= x.alarm_index ? "post" : ""}" style="height:${(p.credit / max) * 100}%"
          title="${p.date}: ${inr(p.credit)}"></i>`).join("");
    return `<div class="sec">
      <h4>Daily credit volume</h4>
      <div class="spark">${bars}</div>
      <dl class="kv" style="margin-top:10px">
        <dt>baseline mean</dt><dd>${inr(x.mu0)}</dd>
        <dt>after change</dt><dd>${inr(x.post_change_mean)}</dd>
        <dt>detected on</dt><dd>${esc(x.alarm_date)}</dd>
        <dt>decision limit h</dt><dd>${x.h}</dd>
      </dl></div>`;
  }

  if (f.mechanism === "vector.mo_similarity" && x.narratives) {
    const [a, b] = Object.keys(x.narratives);
    return `<div class="sec">
      <h4>Comparison</h4>
      <dl class="kv" style="margin-bottom:10px">
        <dt>MO features</dt><dd>${x.feature_similarity}</dd>
        <dt>narrative text</dt><dd>${x.text_similarity}</dd>
        <dt>combined</dt><dd>${x.combined} (threshold ${f.mechanism_params.threshold})</dd>
        <dt>shared entities</dt><dd>${x.shared_entities.length
          ? esc(x.shared_entities.join(", ")) : "none"}</dd>
      </dl>
      <div class="narrbox"><b>${a}</b>${esc(x.narratives[a])}</div>
      <div class="narrbox"><b>${b}</b>${esc(x.narratives[b])}</div>
      <div class="tblwrap"><table class="tbl">
        <tr><th>attribute</th><th>value in both cases</th></tr>
        ${Object.entries(x.agreeing_features).map(([k, v]) =>
          `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}
      </table></div>
    </div>`;
  }

  if (f.mechanism === "rule.structuring" && x.deposits) {
    return `<div class="sec">
      <h4>Deposits that satisfied the rule</h4>
      <div class="tblwrap"><table class="tbl">
        <tr><th>from</th><th>amount</th><th>when</th><th>channel</th></tr>
        ${x.deposits.map(d => `<tr class="hi">
          <td>${esc(d.from)}</td><td>${inr(d.amount)}</td>
          <td>${esc(d.when.replace("T", " ").slice(0, 16))}</td>
          <td>${esc(d.channel || "")}</td></tr>`).join("")}
        <tr><td><b>total</b></td><td colspan="3"><b>${inr(x.total)}</b>
          over ${x.window_hours} h</td></tr>
      </table></div></div>`;
  }

  if (f.mechanism === "structural.community_bridge" && x.top_by_betweenness) {
    const ri = x.removal_impact || {};
    return `<div class="sec">
      <h4>Betweenness ranking</h4>
      <div class="tblwrap"><table class="tbl">
        <tr><th>record</th><th>type</th><th>betweenness</th></tr>
        ${x.top_by_betweenness.map(r => `<tr${(f.subject_ids || []).includes(r.id)
          ? ' class="hi"' : ""}><td>${esc(r.display)}</td>
          <td>${esc(r.label)}</td><td>${r.betweenness}</td></tr>`).join("")}
      </table></div>
      <dl class="kv" style="margin-top:12px">
        <dt>communities</dt><dd>${x.n_communities}</dd>
        <dt>spanned by node</dt><dd>${x.communities_spanned}</dd>
        <dt>components before</dt><dd>${ri.components_before}</dd>
        <dt>components after</dt><dd>${ri.components_after}${ri.splits
          ? " — removal splits the network" : ""}</dd>
      </dl></div>`;
  }

  if (f.mechanism === "structural.community_bridge" && x.path) {
    return `<div class="sec">
      <h4>Traced path</h4>
      <div class="tblwrap"><table class="tbl">
        <tr><th>#</th><th>record</th><th>type</th></tr>
        ${x.path.nodes.map((n, i) => `<tr class="hi"><td>${i + 1}</td>
          <td>${esc(n.display)}</td><td>${esc(n.label)}</td></tr>`).join("")}
      </table></div></div>`;
  }

  if (f.mechanism_family === "er" && (x.merge || x.merges)) {
    const merges = (x.merges || [x.merge]).filter(m => m.fields);
    const table = (m) => `
      <div class="tblwrap"><table class="tbl">
        <tr><th>field</th><th>score</th><th>weight</th><th>note</th></tr>
        ${m.fields.map(fl => `<tr${fl.counted === false ? ' style="opacity:.55"' : ""}>
          <td>${esc(fl.field)}</td>
          <td>${fl.score === null ? "&mdash;" : Number(fl.score).toFixed(2)}</td>
          <td>${fl.weight === null ? "det." : fl.weight}</td>
          <td style="white-space:normal">${esc(fl.note)}</td>
        </tr>`).join("")}
      </table></div>
      <dl class="kv" style="margin-top:10px">
        <dt>method</dt><dd>${esc(m.method)}</dd>
        <dt>score</dt><dd>${m.score}</dd>
        <dt>decision</dt><dd>${esc(m.decision)}</dd>
        <dt>thresholds</dt><dd>low ${m.thresholds.tau_low} / high ${m.thresholds.tau_high}</dd>
      </dl>
      <div class="limit" style="margin-top:10px">${esc(m.rationale)}</div>`;
    const pair = (m) => `${esc(m.left_display)} vs ${esc(m.right_display)}`;
    if (!merges.length) return "";

    // One group of records can produce a table per pair, and six of them
    // stacked open is the wall this panel is meant not to be. The first is the
    // one worth reading; the rest are there to be opened, not scrolled past.
    const rest = merges.slice(1);
    return `
      <div class="sec">
        <h4>Field agreement &mdash; ${pair(merges[0])}</h4>
        ${table(merges[0])}
      </div>
      ${rest.length ? `
        <div class="sec">
          <details class="fold">
            <summary><h4>Further field agreement
              <span class="foldn">${rest.length}</span></h4></summary>
            ${rest.map(m => `
              <div class="subsec">
                <h5>${pair(m)}</h5>
                ${table(m)}
              </div>`).join("")}
          </details>
        </div>` : ""}`;
  }
  return "";
}

function wireExplain(root, f) {
  $$(".ev[data-node]", root).forEach(el =>
    el.onclick = () => showNode(el.dataset.node));

  const cbtn = $(`[data-confirm="${f.finding_id}"]`, root);
  const rbtn = $(`[data-reject="${f.finding_id}"]`, root);
  const box  = $(`[data-reason="${f.finding_id}"]`, root);
  const reop = $(`[data-reopen="${f.finding_id}"]`, root);
  const xbtn = $(`[data-export="${f.finding_id}"]`, root);

  if (cbtn) cbtn.onclick = () => decide(f.finding_id, "confirm", box ? box.value : "");
  if (rbtn) rbtn.onclick = () => decide(f.finding_id, "reject", box ? box.value : "");
  if (reop) reop.onclick = () => decide(f.finding_id, "confirm", "Reopened for further review.");
  if (xbtn) xbtn.onclick = () => download(
    `/api/report/finding/${encodeURIComponent(f.finding_id)}`,
    `CNAS-Finding-Report-${f.finding_id}.docx`, xbtn);
}

async function decide(id, action, reason) {
  if (action === "reject" && !reason.trim()) {
    toast("A rejection must carry a reason.", "bad");
    return;
  }
  try {
    await api(`/api/findings/${encodeURIComponent(id)}/${action}`, {
      method: "POST", body: JSON.stringify({ reason }),
    });
    await loadFindings();
    await loadOverview();
    toast(`Finding ${action === "confirm" ? "confirmed" : "rejected"}. Written to the audit log.`, "good");
    if ($("#view-queue").classList.contains("active")) renderQueue(id);
    else { showFinding(id); renderWorkspaceFindings(); }
  } catch (e) { toast(e.message, "bad"); }
}

/* ====================================================================== queue */
function renderQueue(openId) {
  const fams = {};
  S.findings.forEach(f => { fams[f.mechanism_family] = (fams[f.mechanism_family] || 0) + 1; });
  $("#familyFilter").innerHTML =
    `<button class="filt ${!S.filterFamily ? "on" : ""}" data-f="">All
       <span>${S.findings.length}</span></button>` +
    Object.entries(S.families).map(([k, v]) =>
      `<button class="filt ${S.filterFamily === k ? "on" : ""}" data-f="${k}">${esc(v)}
        <span>${fams[k] || 0}</span></button>`).join("");
  $$("#familyFilter .filt").forEach(b => b.onclick = () => {
    S.filterFamily = b.dataset.f || null; renderQueue();
  });

  const counts = { pending: 0, confirmed: 0, rejected: 0 };
  S.findings.forEach(f => counts[f.status]++);
  $("#statusFilter").innerHTML =
    `<button class="filt ${!S.filterStatus ? "on" : ""}" data-s="">All
       <span>${S.findings.length}</span></button>` +
    ["pending", "confirmed", "rejected"].map(s =>
      `<button class="filt ${S.filterStatus === s ? "on" : ""}" data-s="${s}">${s}
        <span>${counts[s]}</span></button>`).join("");
  $$("#statusFilter .filt").forEach(b => b.onclick = () => {
    S.filterStatus = b.dataset.s || null; renderQueue();
  });

  const list = S.findings.filter(f =>
    (!S.filterFamily || f.mechanism_family === S.filterFamily) &&
    (!S.filterStatus || f.status === S.filterStatus));

  $("#queueList").innerHTML = list.map(f => `
    <article class="qcard ${f.tier === "restricted" ? "restricted" : ""}" data-id="${f.finding_id}">
      <div class="qhead">
        <div class="qfam">${esc(f.family_label)}</div>
        <div class="qmain">
          <div class="qtype">${esc(f.finding_type)}</div>
          <div class="qstate">${esc(f.statement)}</div>
        </div>
        <div class="qmeta">
          <span class="qconf">${f.confidence.toFixed(2)}</span>
          <span class="badge b-${f.status}">${f.status}</span>
          ${f.tier !== "standard" ? `<span class="badge b-${f.tier}">${f.tier}</span>` : ""}
        </div>
      </div>
      <div class="qbody" id="body-${f.finding_id}"></div>
    </article>`).join("") ||
    `<p class="empty">Nothing matches this filter.</p>`;

  $$(".qcard").forEach(card => {
    const id = card.dataset.id;
    $(".qhead", card).onclick = () => toggleCard(id);
  });
  if (openId) toggleCard(openId, true);
}

function toggleCard(id, force) {
  const card = $(`.qcard[data-id="${id}"]`);
  if (!card) return;
  const open = force || !card.classList.contains("open");
  if (!open) { card.classList.remove("open"); return; }
  const f = findingById(id);
  const body = $("#body-" + id);
  body.innerHTML = explainHTML(f);
  // The card header already carries the statement, so the expanded body drops
  // its own copy and splits the rest into two columns: the reading half on the
  // left, the machinery half on the right. The grid collapses to one column on
  // narrow screens, so the split never forces a horizontal scroll.
  const secs = $$(".sec", body);
  const head = $(".phead", body);
  if (head) head.remove();
  const left = document.createElement("div");
  const right = document.createElement("div");
  secs.forEach((s, i) => (i < 2 ? left : right).appendChild(s));
  body.innerHTML = "";
  body.append(left, right);
  card.classList.add("open");
  wireExplain(body, f);
}

/* ================================================================== emergency */
async function runEmergency(q) {
  if (!q || q.length < 3) { toast("Enter at least three characters.", "bad"); return; }
  let r;
  try { r = await api(`/api/emergency-lookup?q=${encodeURIComponent(q)}`); }
  catch (e) { toast(e.message, "bad"); return; }

  $("#emgTiming").innerHTML =
    `${r.hits.length} result${r.hits.length === 1 ? "" : "s"} · ` +
    `<span class="${r.within_target ? "ok" : ""}">${r.elapsed_ms} ms</span>`;

  $("#emgResults").innerHTML = r.hits.length ? r.hits.map(h => `
    <div class="hit">
      <div class="hittop">
        <span class="hitval">${esc(h.matched_value)}</span>
        <span class="badge b-standard">${esc(h.node.label)} &middot; ${esc(h.matched_field)}</span>
      </div>
      <div class="hitsrc">${esc(h.node.id)} &middot; ${esc(h.node.source_record_id)}</div>
      ${h.cases.length ? `<div class="hitcases">
        ${h.cases.map(c => `<button class="hitcase" data-case="${c.id}">
          <span><b>${esc(c.props.title || c.id)}</b> &middot; ${esc(c.props.district || "")}</span>
          <span class="muted">${esc(c.props.crime || "")} &middot; ${esc(c.props.opened || "")}</span>
        </button>`).join("")}</div>` :
        `<p class="muted" style="margin:8px 0 0">Not linked to any case.</p>`}
    </div>`).join("") :
    `<p class="empty">No record on file for that identifier.</p>`;

  $$(".hitcase").forEach(el => el.onclick = () => {
    showView("workspace"); selectCase(el.dataset.case);
  });
}

/* ===================================================================== intake */
async function loadIntakeSchema() {
  let s;
  try { s = await api("/api/intake/schema"); }
  catch (e) { toast(e.message, "bad"); return; }
  S.intakeSchema = s;

  $("#intakePack").innerHTML = `<option value="">—</option>` +
    s.packs.map(p => `<option value="${p.id}">${esc(p.label)}</option>`).join("");

  $("#intakeMO").innerHTML = Object.entries(s.mo_features).map(([k, vals]) => `
    <label class="fld">${esc(k.replace(/_/g, " "))}
      <select name="mo_features.${esc(k)}">
        <option value="">—</option>
        ${vals.map(v => `<option value="${esc(v)}">${esc(v.replace(/_/g, " "))}</option>`).join("")}
      </select>
    </label>`).join("");

  const d = $("#intakeForm").elements["opened"];
  if (d && !d.value) d.value = new Date().toISOString().slice(0, 10);
}

/* ------------------------------------------------------ document intake */
/* The parse fills the form and then stops. An officer sees what was read out
   of the document, and what phrase each value came from, before any of it
   reaches the graph. */
async function parseDocument(file) {
  const dz = $("#dropzone");
  dz.classList.add("busy");
  const body = new FormData();
  body.append("file", file, file.name);
  let r;
  try {
    const res = await fetch("/api/intake/parse",
      { method: "POST", body, headers: { "X-CNAS-Role": S.role } });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail; } catch (e) { /* not JSON */ }
      throw new Error(detail);
    }
    r = await res.json();
  } catch (e) {
    toast("Could not read the document: " + e.message, "bad");
    return;
  } finally {
    dz.classList.remove("busy");
  }
  applyParse(r);
}

function clearProvenance() {
  $$("#intakeForm .prov").forEach(el => el.remove());
  $$("#intakeForm .filled").forEach(el => el.classList.remove("filled"));
}

function setParsed(name, entry) {
  if (!entry) return false;
  const el = $("#intakeForm").elements[name];
  if (!el) return false;
  el.value = entry.value;
  const fld = el.closest(".fld") || el.closest(".fset");
  if (fld) {
    fld.classList.add("filled");
    const note = document.createElement("span");
    note.className = "prov" + (entry.unusable ? " bad" : "");
    note.textContent = entry.unusable
      ? `${entry.how} — not a recorded value, left for you to set`
      : entry.how;
    if (entry.evidence) note.title = entry.evidence;
    fld.appendChild(note);
  }
  if (entry.unusable) el.value = "";
  return !entry.unusable;
}

function applyParse(r) {
  const form = $("#intakeForm");
  form.reset();
  clearProvenance();

  let filled = 0;
  ["title", "district", "pack", "opened", "officer", "narrative"]
    .forEach(k => { if (setParsed(k, r.fields[k])) filled++; });
  Object.entries(r.person || {})
    .forEach(([k, v]) => { if (setParsed(`person.${k}`, v)) filled++; });
  Object.entries(r.identifiers || {})
    .forEach(([k, v]) => { if (setParsed(`identifiers.${k}`, v)) filled++; });
  Object.entries(r.mo_features || {})
    .forEach(([k, v]) => { if (setParsed(`mo_features.${k}`, v)) filled++; });

  if (!form.elements["opened"].value) {
    form.elements["opened"].value = new Date().toISOString().slice(0, 10);
  }

  const src = r.source || {};
  const missing = r.missing_required || [];
  $("#parseReport").hidden = false;
  $("#parseReport").innerHTML = `
    <div class="prhead">
      <h2>${esc(src.filename || "document")}</h2>
      <span class="prmeta">${esc(src.how || "")} ·
        ${Number(src.characters || 0).toLocaleString("en-IN")} characters ·
        ${filled} value${filled === 1 ? "" : "s"} extracted</span>
    </div>
    <div class="prcounts">
      <span><b>${r.counts.fields}</b> case fields</span>
      <span><b>${r.counts.person}</b> person details</span>
      <span><b>${r.counts.identifiers}</b> identifiers</span>
      <span><b>${r.counts.mo_features}</b> modus operandi attributes</span>
    </div>
    ${missing.length ? `<p class="prmissing">Not found in the document, fill
      these in: <b>${missing.map(esc).join(", ")}</b></p>` : ""}
    <details class="fold prdoc">
      <summary><h4>Document text, with every extracted value marked</h4></summary>
      <div class="doctext">${highlightedText(r)}</div>
    </details>`;

  $("#intakeResult").hidden = true;
  toast(`${filled} value${filled === 1 ? "" : "s"} read from ${src.filename}. ` +
        `Check them, then file the record.`, "good");
  $("#parseReport").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* The document with every matched span marked, so "where did that IMEI come
   from" is answered by looking rather than by trusting. */
function highlightedText(r) {
  const text = r.text || "";
  const spans = [];
  const collect = (group, prefix) => Object.entries(group || {}).forEach(([k, v]) => {
    if (v && v.span) spans.push({ a: v.span[0], b: v.span[1], label: prefix + k });
  });
  collect(r.fields, "");
  collect(r.person, "");
  collect(r.identifiers, "");
  collect(r.mo_features, "");
  spans.sort((x, y) => x.a - y.a || y.b - x.b);

  let out = "", at = 0;
  for (const s of spans) {
    if (s.a < at) continue;               // overlaps something already marked
    out += esc(text.slice(at, s.a));
    out += `<mark title="${esc(s.label)}">${esc(text.slice(s.a, s.b))}</mark>`;
    at = s.b;
  }
  return out + esc(text.slice(at));
}

/* Field names carry their own nesting, so the form is the schema and the two
   cannot drift apart. */
function intakePayload(form) {
  const body = {};
  new FormData(form).forEach((v, k) => {
    v = String(v).trim();
    if (!v) return;
    const [head, tail] = k.split(".");
    if (tail) (body[head] = body[head] || {})[tail] = v;
    else body[head] = v;
  });
  return body;
}

/* Two findings of the same kind against different cases is one sentence, not
   the same sentence twice. */
function intakeFindingSummary(r) {
  const byType = {};
  r.findings.forEach(f => {
    const against = (f.subject_ids || []).filter(i => i !== r.case_id);
    (byType[f.finding_type] = byType[f.finding_type] || []).push(...against);
  });
  return Object.entries(byType).map(([type, against]) =>
    `${esc(type)} <span class="mono">${against.map(esc).join(", ")}</span>`).join("; ");
}

async function submitIntake(button) {
  const form = $("#intakeForm");
  if (!form.reportValidity()) return;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Ingesting…";
  let r;
  try {
    r = await api("/api/intake/fir",
      { method: "POST", body: JSON.stringify(intakePayload(form)) });
  } catch (e) {
    toast(e.message, "bad");
    return;
  } finally {
    button.disabled = false;
    button.textContent = label;
  }

  // Cleared on success, so a second click cannot file the same FIR twice.
  form.reset();
  clearProvenance();
  $("#parseReport").hidden = true;
  form.elements["opened"].value = new Date().toISOString().slice(0, 10);

  const n = (c, one, many) => `${c} ${c === 1 ? one : many}`;
  $("#intakeResult").hidden = false;
  $("#intakeResult").innerHTML = `
    <h2>Ingested as ${esc(r.case_id)}</h2>
    <ul class="ilist">
      <li>${n(r.created_nodes.length, "record", "records")} created</li>
      <li>${n(r.merges.length, "record", "records")} on file resolved to the same
        thing${r.attached_to.length
          ? `: <span class="mono">${r.attached_to.map(esc).join(", ")}</span>` : ""}</li>
      <li>${n(r.findings.length, "finding", "findings")} raised${r.findings.length
        ? `: ${intakeFindingSummary(r)}` : ""}</li>
    </ul>
    ${r.merges.length ? `<div class="tblwrap"><table class="tbl">
      <tr><th>merge</th><th>basis</th><th>decision</th></tr>
      ${r.merges.map(m => `<tr class="hi"><td class="mono">${esc(m.merge_id)}</td>
        <td>${esc(m.basis)}</td><td>${esc(m.decision)}</td></tr>`).join("")}
    </table></div>` : ""}
    <p class="fnote">Written to the audit ledger as INGEST${r.merges.length
      ? ", with one entry per merge" : ""}${r.findings.length
      ? " and one per finding" : ""}.</p>`;

  // The new records are marked so what the case attached itself to is visible
  // on the graph rather than left to be inferred.
  // Kept until another case is opened rather than timed out: on a projector a
  // six-second window is a thing the room misses.
  S.flash = {
    caseId: r.case_id,
    created: new Set(r.created_nodes),
    attached: new Set(r.attached_to),
  };
  await loadFindings();
  await loadOverview();
  showView("workspace");
  await selectCase(r.case_id);
  toast(`${r.case_id} ingested. ${n(r.attached_to.length, "record", "records")} ` +
        `already on file matched.`, "good");
}

/* ====================================================================== audit */
async function loadAudit() {
  const a = await api("/api/audit-log?limit=300");
  const v = a.verification;
  $("#chainState").innerHTML = v.intact
    ? `<span style="color:var(--good)">Chain intact · ${v.entries} entries</span>`
    : `<span style="color:var(--bad)">Chain broken at #${v.broken_at}</span>`;

  const cls = a => a.startsWith("FINDING_REJ") ? "reject"
    : a.startsWith("FINDING_CONF") ? "decide"
    : a.startsWith("EMERGENCY") ? "emg"
    : a.startsWith("REPORT") ? "report"
    : (a.startsWith("MERGE") || a.startsWith("FINDING_CREATED") || a === "INGEST") ? "write" : "";

  $("#auditTable").innerHTML =
    `<div class="arow head"><span>#</span><span>Timestamp</span><span>Actor</span>
      <span>Action</span><span>Target</span><span>Entry hash</span></div>` +
    a.entries.map(e => `
      <div class="arow">
        <span class="m">${e.seq}</span>
        <span class="m">${esc(e.ts.slice(0, 19).replace("T", " "))}</span>
        <span>${esc(e.actor)}</span>
        <span><span class="act ${cls(e.action)}">${esc(e.action)}</span></span>
        <span class="m">${esc(e.target)}</span>
        <span class="hash" title="prev ${esc(e.prev_hash)}">${esc(e.hash.slice(0, 16))}&hellip;</span>
      </div>`).join("");
}

/* ======================================================================= boot */
async function refreshAll() {
  await loadSession();
  await loadFindings();
  await loadOverview();
  renderQueue();
  if (S.currentCase && S.cases.some(c => c.id === S.currentCase)) await selectCase(S.currentCase);
  else if (S.cases.length) await selectCase(S.cases[0].id);
}

function boot() {
  $$(".tab").forEach(b => b.onclick = () => showView(b.dataset.view));

  $("#roleSelect").onchange = async e => {
    S.role = e.target.value;
    clearPanel();
    await refreshAll();
    toast(`Signed in as ${e.target.selectedOptions[0].textContent}.`);
  };

  $("#panelClose").onclick = clearPanel;
  $("#btnBackToCase").onclick = () =>
    S.currentCase && selectCase(S.currentCase);
  $("#hopSelect").onchange = () =>
    S.currentCase && drawEgo(S.currentCase).then(renderWorkspaceFindings);
  $("#layoutSelect").onchange = runLayout;
  $("#btnFit").onclick = () => S.cy && S.cy.fit(undefined, 44);

  $("#btnExportCase").onclick = e => {
    if (!S.currentCase) { toast("Select a case first.", "bad"); return; }
    download(`/api/report/case/${encodeURIComponent(S.currentCase)}?hops=${$("#hopSelect").value}`,
      `CNAS-Case-Report-${S.currentCase}.docx`, e.currentTarget);
  };

  $("#btnExportQueue").onclick = e => {
    const q = new URLSearchParams();
    if (S.filterStatus) q.set("status", S.filterStatus);
    if (S.filterFamily) q.set("family", S.filterFamily);
    const qs = q.toString();
    download("/api/report/queue" + (qs ? "?" + qs : ""),
      "CNAS-Review-Queue-Report.docx", e.currentTarget);
  };

  // The path from the Jaipur theft to the Kandla consignment is five hops long,
  // further than any ego view on offer, so the path replaces the case view
  // rather than being highlighted inside one that cannot contain it.
  $("#btnChain").onclick = async () => {
    let chain;
    try { chain = await api("/api/chain?src=C-001&dst=C-005"); }
    catch (e) { toast(e.message, "bad"); return; }
    if (!chain.found) { toast("No path visible at your tier.", "bad"); return; }

    markCase("C-001");
    setChainMode(true);
    $("#canvasTitle").textContent = "Cross-domain path · C-001 to C-005";
    $("#canvasSub").textContent =
      `${chain.hops} hops · theft in Jaipur through to smuggling at Kandla`;
    // Any layout still animating would go on ticking against a canvas that is
    // no longer on screen.
    stopLayout();
    S.lastEgo = { nodes: chain.nodes, edges: chain.edges, truncated: false };
    renderLegend({ nodes: chain.nodes }, false);
    renderChainStrip(chain);
    $("#queryStat").textContent =
      `${chain.nodes.length} records · ${chain.edges.length} relationships on the path`;
    renderWorkspaceFindings();

    const f = S.findings.find(x => x.finding_id === "F-STRUCT-CHAIN");
    if (f) { $("#panel").innerHTML = explainHTML(f); wireExplain($("#panel"), f); }
    toast(`Path traced end to end: ${chain.hops} hops.`, "good");
  };

  $("#intakeForm").onsubmit = e => { e.preventDefault(); submitIntake($("#btnIntake")); };
  $("#btnIntake").onclick = e => { e.preventDefault(); submitIntake(e.currentTarget); };

  const dz = $("#dropzone");
  const pick = $("#firFile");
  $("#btnPick").onclick = () => pick.click();
  pick.onchange = () => { if (pick.files[0]) parseDocument(pick.files[0]); };
  dz.ondragover = e => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = e => {
    e.preventDefault();
    dz.classList.remove("over");
    const f = e.dataTransfer.files[0];
    if (f) parseDocument(f);
  };
  // The samples are served from the repository so the demonstration does not
  // depend on a file dialogue on someone else's laptop.
  $$("#dropzone .sample").forEach(b => b.onclick = async () => {
    try {
      const res = await fetch(`/samples/${encodeURIComponent(b.dataset.file)}`);
      if (!res.ok) throw new Error(res.statusText);
      parseDocument(new File([await res.blob()], b.dataset.file));
    } catch (e) { toast("Sample not available: " + e.message, "bad"); }
  });

  $("#emgBtn").onclick = () => runEmergency($("#emgInput").value.trim());
  $("#emgInput").onkeydown = e => { if (e.key === "Enter") runEmergency(e.target.value.trim()); };
  $$(".chip").forEach(c => c.onclick = () => {
    $("#emgInput").value = c.dataset.q; runEmergency(c.dataset.q);
  });

  $("#btnVerify").onclick = async () => {
    const v = await api("/api/audit-log/verify");
    toast(v.intact
      ? `Chain verified: ${v.entries} entries.`
      : `Chain broken at entry ${v.broken_at}: ${v.reason}`, v.intact ? "good" : "bad");
    loadAudit();
  };

  // Cytoscape sizes itself to its container once; a resized window has to say so.
  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => { if (S.cy) { S.cy.resize(); S.cy.fit(undefined, 44); } }, 180);
  });

  refreshAll().catch(e => toast("Startup failed: " + e.message, "bad"));
}

document.addEventListener("DOMContentLoaded", boot);
