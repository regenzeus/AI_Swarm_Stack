// The code map's graph as the viewer wants it: Understand Anything's own autoFixGraph, saved, so the viewer has
// nothing left to correct and shows no "loaded with N auto-corrections" banner (an edge without a weight, a node
// without a type). Runs in the code-map image after an analysis (ops/understand.sh) with the repo's .ua at /ua:
//   docker run --rm --network none -v <repo>/.ua:/ua -v ops/ua_fix.mjs:/ua_fix.mjs:ro --entrypoint node <image> /ua_fix.mjs
import fs from "node:fs";

const { autoFixGraph } = await import("/opt/ua/packages/core/dist/schema.js");
const file = "/ua/knowledge-graph.json";
const { data, issues } = autoFixGraph(JSON.parse(fs.readFileSync(file, "utf8")));
const fixed = issues.filter((i) => i.level === "auto-corrected");
if (fixed.length) fs.writeFileSync(file, JSON.stringify(data, null, 2));
const left = issues.length - fixed.length;
console.log(`code map graph: ${fixed.length} auto-correction${fixed.length === 1 ? "" : "s"} saved` + (left ? `, ${left} other issue${left === 1 ? "" : "s"} left` : ""));
