import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import prettier from "prettier";
import { Project } from "ts-morph";
import { extractCode } from "./code";
import {
  CONTEXT_DIR,
  DECISIONS_PATH,
  FRONTEND_ROOT,
  GRAPH_PATH,
  VIOLATIONS_PATH,
  countFingerprints,
  isRecord,
  loadDecisions,
  matchesAnyGlob,
  oneLine,
  readGraph,
  stableStringify,
  type Decision,
  type Graph,
  type GraphEdge,
  type GraphNode,
  type Violation,
} from "./graph-model";
import {
  compareViolations,
  dedupeViolations,
  loadTokens,
  scanStylesheet,
} from "./styles";

const CODE_TYPES = new Set(["page", "layout", "component", "hook", "util"]);

function previousNodes(): Map<string, GraphNode> {
  const graph = readGraph();
  const map = new Map<string, GraphNode>();
  for (const node of graph?.nodes ?? []) map.set(node.id, node);
  return map;
}

function decisionNodes(decisions: Decision[]): GraphNode[] {
  return decisions.map((decision) => ({
    id: `decision:${decision.id}`,
    needsReview: decision.needs_review,
    path: "context/decisions.yaml",
    rationale: oneLine(decision.rationale),
    summary: oneLine(decision.rule),
    title: decision.title,
    type: "decision" as const,
  }));
}

function constraintEdges(
  decisions: Decision[],
  nodes: GraphNode[]
): GraphEdge[] {
  const edges: GraphEdge[] = [];
  for (const node of nodes) {
    if (!node.path || !CODE_TYPES.has(node.type)) continue;
    for (const decision of decisions) {
      if (!matchesAnyGlob(decision.applies_to, node.path)) continue;
      edges.push({
        from: node.id,
        to: `decision:${decision.id}`,
        type: "constrained_by",
      });
    }
  }
  return edges;
}

function sortEdges(edges: GraphEdge[]): GraphEdge[] {
  return [...edges].sort(
    (a, b) =>
      a.from.localeCompare(b.from) ||
      a.to.localeCompare(b.to) ||
      a.type.localeCompare(b.type)
  );
}

async function writeJson(filePath: string, value: unknown): Promise<void> {
  const formatted = await prettier.format(stableStringify(value), {
    filepath: filePath,
    parser: "json",
  });
  fs.writeFileSync(filePath, formatted);
}

function readCommittedViolations(): Violation[] | null {
  try {
    const raw = execSync("git show HEAD:frontend/context/violations.json", {
      cwd: FRONTEND_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || !Array.isArray(parsed.violations)) return [];
    return parsed.violations.filter(isViolation);
  } catch {
    return null;
  }
}

function isViolation(value: unknown): value is Violation {
  if (!isRecord(value)) return false;
  return (
    typeof value.file === "string" &&
    typeof value.kind === "string" &&
    typeof value.line === "number" &&
    typeof value.message === "string" &&
    typeof value.value === "string"
  );
}

function newViolations(
  current: Violation[],
  baseline: Violation[]
): Violation[] {
  const counts = countFingerprints(baseline);
  const seen = new Map<string, number>();
  const extras: Violation[] = [];
  for (const violation of current) {
    const key = `${violation.file}\0${violation.kind}\0${violation.value}`;
    const next = (seen.get(key) ?? 0) + 1;
    seen.set(key, next);
    if (next > (counts.get(key) ?? 0)) extras.push(violation);
  }
  return extras;
}

async function main(): Promise<void> {
  const check = process.argv.includes("--check");
  fs.mkdirSync(CONTEXT_DIR, { recursive: true });
  const project = new Project({
    skipAddingFilesFromTsConfig: true,
    skipFileDependencyResolution: true,
    tsConfigFilePath: path.join(FRONTEND_ROOT, "tsconfig.json"),
  });
  project.addSourceFilesAtPaths([
    "src/**/*.ts",
    "src/**/*.tsx",
    "tailwind.config.ts",
  ]);
  const tailwind = project.getSourceFileOrThrow("tailwind.config.ts");
  const cssPath = path.join(FRONTEND_ROOT, "src/app/globals.css");
  const css = fs.readFileSync(cssPath, "utf8");
  const tokens = loadTokens(tailwind, css);
  const decisions = loadDecisions(DECISIONS_PATH);
  const code = extractCode(project, tokens, previousNodes());
  const stylesheetViolations = scanStylesheet(
    "src/app/globals.css",
    css,
    tokens
  );
  const violations = dedupeViolations([
    ...code.violations,
    ...stylesheetViolations,
  ]).sort(compareViolations);

  const nodes = [
    ...code.nodes,
    ...tokens.nodes,
    ...decisionNodes(decisions),
  ].sort((a, b) => a.id.localeCompare(b.id));
  const ids = new Set(nodes.map((node) => node.id));
  const edges = sortEdges([
    ...code.edges,
    ...tokens.componentExtends,
    ...constraintEdges(decisions, code.nodes),
  ]);
  for (const edge of edges) {
    if (!ids.has(edge.from) || !ids.has(edge.to)) {
      throw new Error(`Dangling edge ${edge.type} ${edge.from} -> ${edge.to}`);
    }
  }

  const graph: Graph = { edges, nodes, version: 1 };
  await writeJson(GRAPH_PATH, graph);
  await writeJson(VIOLATIONS_PATH, { violations });
  console.log(
    `Wrote context/graph.json (${nodes.length} nodes, ${edges.length} edges) and context/violations.json (${violations.length} violations).`
  );

  if (!check) return;
  const baseline = readCommittedViolations();
  if (baseline === null) {
    console.log(
      "No committed violations.json yet; new-violation check skipped."
    );
    return;
  }
  const extras = newViolations(violations, baseline);
  if (extras.length === 0) return;
  console.error("New token violations block this commit:");
  for (const violation of extras) {
    console.error(
      `  ${violation.file}:${violation.line} ${violation.kind} ${violation.value}`
    );
  }
  console.error(
    "Use theme tokens from tailwind.config.ts and globals.css, then rebuild."
  );
  process.exitCode = 1;
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exitCode = 1;
});
