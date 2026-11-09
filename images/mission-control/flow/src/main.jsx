// The template editor (GEN-34, docs/AI-STACK.md §5): Workflow Builder's editor (palette, canvas, a form per block from
// its schema, decisions with branches) on the stack's blocks. The template's YAML stays the truth: toDiagram() draws a
// template's spec, toSpec() turns the drawing back into one, and the app sends that to template_save, which checks it
// with the graph model and writes the canonical YAML. Positions are kept apart, in the template's layout.
//
//   mount(el, {name, spec, layout, agents, roles, theme, onSave(spec, layout)})  -> {destroy()}
//   toDiagram(spec, layout, ctx) -> {nodes, edges}      toSpec(data, base) -> {spec, layout}
import { WorkflowBuilder, useWorkflowBuilderActions } from "@workflowbuilder/sdk";
import "@workflowbuilder/sdk/style.css";
import { useEffect } from "react";
import { createRoot } from "react-dom/client";

import { BLOCK_ICONS, BLOCK_TEMPLATE, blocks } from "./blocks.js";

const FIELDS = ["agent", "brief", "kind", "trigger", "role", "each", "for", "key", "remind", "timeout", "then", "pool", "place"];
const FAILED = "failed";                                // an arrow taken only when its block fails (ops/engine/graph.py)
const FAIL_WORDS = new Set(["failed", "on failure", "if it fails", "fails", "failure"]);
const KEEP = ["values", "items"];                       // fields no form shows: carried through the editor unchanged
const X = 340, Y = 170;                                 // a block's place when the template has no layout yet

function layers(spec) {                                 // left to right by depth, for a template drawn the first time
  const nodes = Object.keys(spec.nodes || {});
  const after = Object.fromEntries(nodes.map((n) => [n, []]));
  for (const e of spec.edges || []) if (after[e[1]]) after[e[1]].push(e[0]);
  const depth = {};
  const d = (n, seen = new Set()) => {
    if (depth[n] !== undefined) return depth[n];
    if (seen.has(n)) return 0;
    seen.add(n);
    return (depth[n] = after[n].length ? 1 + Math.max(...after[n].map((a) => d(a, seen))) : 0);
  };
  nodes.forEach((n) => d(n));
  const rows = {};
  return Object.fromEntries(nodes.map((n) => { const c = depth[n]; rows[c] = (rows[c] || 0) + 1; return [n, { x: 40 + c * X, y: 40 + (rows[c] - 1) * Y }]; }));
}

export function toDiagram(spec, layout = {}) {
  const auto = layers(spec);
  const nodes = Object.entries(spec.nodes || {}).map(([id, f]) => {
    const b = f.block;
    const props = { label: f.title || id, description: f.why || "" };
    for (const k of FIELDS) if (f[k] !== undefined) props[k] = Array.isArray(f[k]) ? f[k].join(", ") : String(f[k]);
    if (f.loop) props.loopMax = String(f.loop.max ?? "");
    const keep = Object.fromEntries(KEEP.filter((k) => f[k] !== undefined).map((k) => [k, f[k]]));
    if (Object.keys(keep).length) props.keep = keep;
    if (b === "branch") {
      const outs = (spec.edges || []).filter((e) => e[0] === id);
      props.decisionBranches = outs.map((e, i) => ({ id: `${id}-b${i}`, sourceHandle: `${id}-b${i}`, label: e[2] || `branch ${i + 1}`, conditions: [] }));
    }
    const t = BLOCK_TEMPLATE[b] || "node";
    return { id, type: t, position: layout[id] || auto[id], data: { type: b, icon: BLOCK_ICONS[b] || "Robot", templateType: t, segments: [], properties: props, ...(b === "start" ? { isStartNode: true } : {}) } };
  });
  const edges = [];
  for (const e of spec.edges || []) {
    const src = nodes.find((n) => n.id === e[0]);
    const br = src?.data.properties.decisionBranches?.find((x) => x.label === e[2]);
    edges.push({ id: `e-${e[0]}-${e[1]}`, source: e[0], target: e[1], sourceHandle: br ? br.sourceHandle : "source", targetHandle: "target", type: "labelEdge",
      data: e[2] === FAILED ? { label: "if it fails" } : e[2] ? { label: e[2] } : {} });
  }
  for (const [id, f] of Object.entries(spec.nodes || {})) {    // a loop is an arrow back
    if (f.loop?.to) edges.push({ id: `l-${id}-${f.loop.to}`, source: id, target: f.loop.to, sourceHandle: "source", targetHandle: "target", type: "labelEdge", data: { label: `back, at most ${f.loop.max}` } });
  }
  return { nodes, edges };
}

function slug(text, taken) {
  let base = String(text || "step").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/^[^a-z]+/, "") || "step";
  base = base.slice(0, 40).replace(/-+$/, "");
  let id = base, n = 2;
  while (taken.has(id)) id = `${base}-${n++}`;
  taken.add(id);
  return id;
}

export function toSpec(data, base = {}) {
  const taken = new Set(), ids = {};
  for (const n of data.nodes) ids[n.id] = /^[a-z][a-z0-9-]*$/.test(n.id) && !taken.has(n.id) ? (taken.add(n.id), n.id) : null;
  for (const n of data.nodes) if (!ids[n.id]) ids[n.id] = slug(n.data?.properties?.label, taken);
  const fwd = data.edges.filter((e) => ids[e.source] && ids[e.target]).map((e) => ({ ...e }));
  const state = {};                                       // an arrow back: a depth-first walk in the blocks' order meets its target still open
  const walk = (n) => {
    state[n] = 1;
    for (const e of fwd.filter((x) => x.source === n)) {
      if (state[e.target] === 1) e._back = true;
      else if (!state[e.target]) walk(e.target);
    }
    state[n] = 2;
  };
  const into = new Set(fwd.map((e) => e.target));
  for (const n of data.nodes) if (!into.has(n.id) && !state[n.id]) walk(n.id);     // from the starts first, then the rest
  for (const n of data.nodes) if (!state[n.id]) walk(n.id);
  const nodes = {}, layout = {};
  for (const n of data.nodes) {
    const p = n.data?.properties || {}, id = ids[n.id];
    const f = { block: n.data?.type, title: p.label || id };
    for (const k of FIELDS) if (p[k] !== undefined && String(p[k]).trim() !== "") f[k] = String(p[k]).trim();
    if (f.remind) f.remind = f.remind.split(/[\s,]+/).filter(Boolean);
    const back = fwd.find((e) => e.source === n.id && e._back);
    if (back) f.loop = { to: ids[back.target], max: Math.min(Math.max(parseInt(p.loopMax, 10) || 2, 1), 4) };
    if (p.description) f.why = p.description;
    Object.assign(f, p.keep || {});
    nodes[id] = f;
    layout[id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) };
  }
  const edges = fwd.filter((e) => !e._back).map((e) => {
    const src = data.nodes.find((n) => n.id === e.source);
    const br = src?.data?.properties?.decisionBranches?.find((b) => b.sourceHandle === e.sourceHandle);
    const label = (br?.label || e.data?.label || "").trim();
    if (!br && FAIL_WORDS.has(label.toLowerCase())) return [ids[e.source], ids[e.target], FAILED];   // a failure path, from any block
    return src?.data?.type === "branch" && label ? [ids[e.source], ids[e.target], label] : [ids[e.source], ids[e.target]];
  });
  const spec = { template: base.template || data.name, ...(base.about ? { about: base.about } : {}), ...(base.budget ? { budget: base.budget } : {}), nodes, edges };
  return { spec, layout };
}

function Theme({ theme }) {
  const { setTheme } = useWorkflowBuilderActions();
  useEffect(() => { if (theme) setTheme(theme); }, [theme, setTheme]);
  return null;
}

const FIT = { fitView: true, fitViewOptions: { padding: 0.12 }, minZoom: 0.15 };   // a template opens whole, at any size
const CONNECT = ({ sourceNode, targetNode }) => sourceNode?.data?.type !== "end" && targetNode?.data?.type !== "start";   // nothing after an End, nothing into the Start

const NAMES = { label: "Title", agent: "Agent", kind: "Job", trigger: "When or what", brief: "What they hear", role: "Who decides", for: "Waits for", key: "Answer to", timeout: "Gives up after", then: "Then tells" };

export function missing(data, nodeTypes) {             // what a block still needs, in the words of its form, before the save
  const req = Object.fromEntries(nodeTypes.map((t) => [t.type, { label: t.label, need: t.schema.required || [] }]));
  const out = [];
  const starts = data.nodes.filter((n) => n.data?.type === "start");
  if (starts.length !== 1) out.push(starts.length ? "A template has one Start: remove the others" : "Add a Start from the palette: it says what starts a run, and draw an arrow from it to the first block");
  if (!data.nodes.some((n) => n.data?.type === "end")) out.push("Add an End from the palette: it says what a run delivers, and draw an arrow into it from the last block");
  for (const n of data.nodes) {
    const t = req[n.data?.type], p = n.data?.properties || {};
    if (n.data?.type !== "end" && !data.edges.some((e) => e.source === n.id)) out.push(`“${p.label || t?.label}” leads nowhere: draw an arrow from it to the next block or to an End`);
    const need = (t?.need || []).concat(n.data?.type === "start" && ["schedule", "event"].includes(p.kind) ? ["trigger"] : []);
    const gaps = need.filter((k) => String(p[k] ?? "").trim() === "").map((k) => (k === "kind" && t?.label === "Command" ? "Job" : NAMES[k] || k));
    if (gaps.length) out.push(`“${p.label || t.label}” (${t.label}) needs ${gaps.join(" and ")}: select it and fill ${gaps.length > 1 ? "them" : "it"} in`);
    if (n.data?.type === "branch") {
      const outs = data.edges.filter((e) => e.source === n.id && !FAIL_WORDS.has(String(e.data?.label || "").toLowerCase())).length;
      if (outs < 2) out.push(`“${p.label || "Decision"}” (Decision) needs two or more arrows out, one per branch: add its branches and draw an arrow from each`);
    }
  }
  return out;
}

export function mount(el, opts) {
  const nodeTypes = blocks({ agents: opts.agents || [], roles: opts.roles || [] });
  const { nodes, edges } = toDiagram(opts.spec || { nodes: {} }, opts.layout || {});
  const onDataSave = async (data) => {
    const gaps = missing(data, nodeTypes);
    if (gaps.length) { opts.onProblem?.(`Not saved yet. ${gaps.join(". ")}.`); return "error"; }
    try { return (await opts.onSave(toSpec(data, opts.spec || {}))) === false ? "error" : "success"; } catch (e) { console.error(e); return "error"; }
  };
  const root = createRoot(el);
  root.render(
    <WorkflowBuilder.Root name={opts.name} nodeTypes={nodeTypes} initialNodes={nodes} initialEdges={edges} layoutDirection="RIGHT"
      integration={{ strategy: "props", onDataSave }} logo={opts.logo} reactFlowProps={FIT} isValidConnection={CONNECT}>
      <WorkflowBuilder.DefaultLayout />
      <Theme theme={opts.theme} />
    </WorkflowBuilder.Root>,
  );
  return { destroy: () => root.unmount() };
}
