import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

interface GraphNode {
  exports?: string[];
  id: string;
  path?: string;
  summary: string;
  title?: string;
  type: string;
}

interface GraphEdge {
  from: string;
  to: string;
  type: string;
}

interface GraphFile {
  edges: GraphEdge[];
  nodes: GraphNode[];
}

interface ViolationRecord {
  file: string;
  kind: string;
  line: number;
  message: string;
  value: string;
}

interface ViolationsFile {
  violations: ViolationRecord[];
}

interface DecisionRecord {
  id: string;
  needs_review?: boolean;
  rule: string;
  title: string;
}

const CATEGORY_ORDER = [
  "hardcoded-color",
  "hardcoded-font-size",
  "unknown-token",
];

const CATEGORY_LABELS: Record<string, string> = {
  "hardcoded-color": "Hardcoded colors",
  "hardcoded-font-size": "Arbitrary font sizes",
  "unknown-token": "Invented tokens",
};

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export interface CategoryTotal {
  count: number;
  kind: string;
  label: string;
}

export interface ViolationSegment {
  count: number;
  kind: string;
}

export interface ViolationRow {
  file: string;
  highlighted: boolean;
  label: string;
  segments: ViolationSegment[];
  total: number;
}

export interface ViolationsModel {
  categories: CategoryTotal[];
  countCh: number;
  labelCh: number;
  rows: ViolationRow[];
  scanDate: string;
  topTwoCount: number;
  total: number;
}

export interface CanvasNode {
  id: string;
  name: string;
  typeLabel: string;
}

export interface GraphModel {
  focus: CanvasNode;
  imports: CanvasNode[];
  parents: CanvasNode[];
  rules: Array<{ id: string; title: string }>;
  scanDate: string;
  tokens: string[];
}

function readText(rel: string): string {
  return fs.readFileSync(path.join(process.cwd(), rel), "utf8");
}

function scanDate(): string {
  const graphTime = fs.statSync(
    path.join(process.cwd(), "context/graph.json")
  ).mtime;
  const violationTime = fs.statSync(
    path.join(process.cwd(), "context/violations.json")
  ).mtime;
  const latest = graphTime > violationTime ? graphTime : violationTime;
  const month = MONTHS[latest.getMonth()] ?? "";
  return `${latest.getDate()} ${month} ${latest.getFullYear()}`;
}

function fileLabel(file: string, files: string[]): string {
  const base = file.split("/").pop() ?? file;
  const stem = base.replace(/\.[^.]+$/, "");
  let stemCollisions = 0;
  for (const other of files) {
    const otherBase = other.split("/").pop() ?? other;
    if (otherBase.replace(/\.[^.]+$/, "") === stem) stemCollisions += 1;
  }
  if (stemCollisions > 1) {
    const parts = file.split("/");
    return parts.slice(-2).join("/");
  }
  if (base.length > 32) return stem;
  return base;
}

function categoryLabel(kind: string): string {
  return (
    CATEGORY_LABELS[kind] ??
    kind
      .split("-")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ")
  );
}

function orderedKinds(present: string[]): string[] {
  const extras = present
    .filter((kind) => !CATEGORY_ORDER.includes(kind))
    .sort((a, b) => a.localeCompare(b));
  return [
    ...CATEGORY_ORDER.filter((kind) => present.includes(kind)),
    ...extras,
  ];
}

export function loadViolations(): ViolationsModel {
  const data = JSON.parse(
    readText("context/violations.json")
  ) as ViolationsFile;
  const records = data.violations;
  const byFile: Record<string, Record<string, number>> = {};
  const kindTotals: Record<string, number> = {};

  for (const record of records) {
    const fileCounts = byFile[record.file] ?? {};
    fileCounts[record.kind] = (fileCounts[record.kind] ?? 0) + 1;
    byFile[record.file] = fileCounts;
    kindTotals[record.kind] = (kindTotals[record.kind] ?? 0) + 1;
  }

  const files = Object.keys(byFile).sort((a, b) => a.localeCompare(b));
  const rows = files.map((file) => {
    const counts = byFile[file] ?? {};
    const total = Object.keys(counts).reduce(
      (sum, kind) => sum + (counts[kind] ?? 0),
      0
    );
    return { file, counts, total };
  });
  rows.sort((a, b) => b.total - a.total || a.file.localeCompare(b.file));

  const kinds = orderedKinds(Object.keys(kindTotals));
  const top = rows.slice(0, 2);
  const labels = rows.map((row) => fileLabel(row.file, files));
  const longestLabel = labels.reduce(
    (max, label) => Math.max(max, label.length),
    1
  );
  const largestTotal = rows.reduce((max, row) => Math.max(max, row.total), 1);

  return {
    categories: kinds.map((kind) => ({
      count: kindTotals[kind] ?? 0,
      kind,
      label: categoryLabel(kind),
    })),
    countCh: String(largestTotal).length,
    labelCh: longestLabel,
    rows: rows.map((row, index) => ({
      file: row.file,
      highlighted: index < 2,
      label: labels[index] ?? row.file,
      segments: kinds
        .filter((kind) => (row.counts[kind] ?? 0) > 0)
        .map((kind) => ({ count: row.counts[kind] ?? 0, kind })),
      total: row.total,
    })),
    scanDate: scanDate(),
    topTwoCount: top.reduce((sum, row) => sum + row.total, 0),
    total: records.length,
  };
}

function readGraph(): GraphFile {
  return JSON.parse(readText("context/graph.json")) as GraphFile;
}

function readDecisions(): DecisionRecord[] {
  const doc = parse(readText("context/decisions.yaml")) as {
    decisions?: DecisionRecord[];
  };
  if (!doc?.decisions) {
    throw new Error("context/decisions.yaml is missing a decisions list");
  }
  return doc.decisions;
}

function typeLabel(type: string): string {
  const labels: Record<string, string> = {
    component: "Component",
    decision: "Decision",
    hook: "Hook",
    layout: "Layout",
    page: "Page",
    token: "Token",
    util: "Util",
  };
  return labels[type] ?? type;
}

function nodeName(node: GraphNode): string {
  const exported = node.exports?.[0];
  if (node.type === "component" && exported) return exported;
  const colon = node.id.indexOf(":");
  return colon === -1 ? node.id : node.id.slice(colon + 1);
}

function toCanvas(node: GraphNode): CanvasNode {
  return {
    id: node.id,
    name: nodeName(node),
    typeLabel: typeLabel(node.type),
  };
}

function prettyToken(id: string): string {
  const raw = id.startsWith("token:") ? id.slice("token:".length) : id;
  const bits = raw.split(".");
  const head = bits[0] ?? "";
  const rest = bits.slice(1).join("-");
  if (head === "color" || head === "class" || head === "animation") return rest;
  if (head === "font") return `font-${rest}`;
  if (head === "shadow") return `shadow-${rest}`;
  return bits.join("-");
}

function parentPages(
  focusId: string,
  edges: GraphEdge[],
  byId: Record<string, GraphNode>
): GraphNode[] {
  const seen: Record<string, true> = { [focusId]: true };
  let frontier = [focusId];
  while (frontier.length > 0) {
    const next: string[] = [];
    const pages: GraphNode[] = [];
    for (const id of frontier) {
      for (const edge of edges) {
        if (edge.to !== id || edge.type !== "renders") continue;
        if (seen[edge.from]) continue;
        seen[edge.from] = true;
        const node = byId[edge.from];
        if (!node) continue;
        if (node.type === "page") pages.push(node);
        else next.push(node.id);
      }
    }
    if (pages.length > 0) {
      pages.sort((a, b) => a.id.localeCompare(b.id));
      return pages;
    }
    frontier = next;
  }
  return [];
}

export function loadGraph(nodeId: string): GraphModel | null {
  const graph = readGraph();
  const byId: Record<string, GraphNode> = {};
  for (const node of graph.nodes) byId[node.id] = node;
  const focus = byId[nodeId];
  if (!focus) return null;

  const imports: GraphNode[] = [];
  const tokenLabels: string[] = [];
  const decisionIds: Record<string, true> = {};
  for (const edge of graph.edges) {
    if (edge.from !== focus.id) continue;
    if (edge.type === "imports") {
      const target = byId[edge.to];
      if (target) imports.push(target);
    } else if (edge.type === "uses_token") {
      tokenLabels.push(prettyToken(edge.to));
    } else if (
      edge.type === "constrained_by" &&
      edge.to.startsWith("decision:")
    ) {
      decisionIds[edge.to.slice("decision:".length)] = true;
    }
  }
  imports.sort((a, b) => a.id.localeCompare(b.id));
  tokenLabels.sort((a, b) => a.localeCompare(b));

  const rules: Array<{ id: string; title: string }> = [];
  for (const decision of readDecisions()) {
    if (!decisionIds[decision.id]) continue;
    rules.push({ id: decision.id, title: decision.title });
    delete decisionIds[decision.id];
  }
  for (const id of Object.keys(decisionIds).sort((a, b) =>
    a.localeCompare(b)
  )) {
    const node = byId[`decision:${id}`];
    rules.push({ id, title: node?.title ?? id });
  }

  return {
    focus: toCanvas(focus),
    imports: imports.map(toCanvas),
    parents: parentPages(focus.id, graph.edges, byId).map(toCanvas),
    rules,
    scanDate: scanDate(),
    tokens: tokenLabels,
  };
}
