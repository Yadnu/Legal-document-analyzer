import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

export const FRONTEND_ROOT = path.resolve(__dirname, "../..");
export const CONTEXT_DIR = path.join(FRONTEND_ROOT, "context");
export const GRAPH_PATH = path.join(CONTEXT_DIR, "graph.json");
export const VIOLATIONS_PATH = path.join(CONTEXT_DIR, "violations.json");
export const DECISIONS_PATH = path.join(CONTEXT_DIR, "decisions.yaml");

export type NodeType =
  "page" | "layout" | "component" | "hook" | "util" | "token" | "decision";

export type EdgeType =
  "imports" | "renders" | "uses_token" | "constrained_by" | "extends";

export type SummaryOrigin = "auto" | "human";

export interface GraphNode {
  exports?: string[];
  id: string;
  needsReview?: boolean;
  path?: string;
  props?: string[];
  rationale?: string;
  summary: string;
  summaryOrigin?: SummaryOrigin;
  title?: string;
  type: NodeType;
}

export interface GraphEdge {
  from: string;
  to: string;
  type: EdgeType;
}

export interface Graph {
  edges: GraphEdge[];
  nodes: GraphNode[];
  version: number;
}

export type ViolationKind =
  | "hardcoded-color"
  | "hardcoded-font-size"
  | "hardcoded-spacing"
  | "unknown-token";

export interface Violation {
  file: string;
  kind: ViolationKind;
  line: number;
  message: string;
  value: string;
}

export interface ViolationsFile {
  violations: Violation[];
}

export interface Decision {
  applies_to: string[];
  id: string;
  needs_review: boolean;
  rationale: string;
  rule: string;
  title: string;
}

export function oneLine(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function toPosix(filePath: string): string {
  return filePath.split(path.sep).join("/");
}

export function relFromFrontend(filePath: string): string {
  return toPosix(path.relative(FRONTEND_ROOT, filePath));
}

export function sortUnique(values: string[]): string[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
}

export function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort((a, b) => a.localeCompare(b))) {
      sorted[key] = sortValue(record[key]);
    }
    return sorted;
  }
  return value;
}

export function stableStringify(value: unknown): string {
  return `${JSON.stringify(sortValue(value), null, 2)}\n`;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function globMatch(pattern: string, filePath: string): boolean {
  const target = filePath.replace(/\\/g, "/");
  let expression = "^";
  for (let i = 0; i < pattern.length; i += 1) {
    if (pattern.startsWith("**", i)) {
      expression += ".*";
      i += 1;
      continue;
    }
    const char = pattern[i] ?? "";
    if (char === "*") expression += "[^/]*";
    else if ("\\.+^${}()|[]".includes(char)) expression += `\\${char}`;
    else expression += char;
  }
  expression += "$";
  return new RegExp(expression).test(target);
}

export function matchesAnyGlob(patterns: string[], filePath: string): boolean {
  return patterns.some((pattern) => globMatch(pattern, filePath));
}

function requiredString(
  record: Record<string, unknown>,
  key: string,
  id: string
): string {
  const value = record[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(
      `Decision ${id} is missing a ${key} string in context/decisions.yaml`
    );
  }
  return value.trim();
}

export function loadDecisions(filePath = DECISIONS_PATH): Decision[] {
  const raw: unknown = parse(fs.readFileSync(filePath, "utf8"));
  if (!isRecord(raw) || !Array.isArray(raw.decisions)) {
    throw new Error(
      "context/decisions.yaml must be a mapping with a decisions list"
    );
  }
  return raw.decisions.map((entry) => {
    if (!isRecord(entry)) throw new Error("Each decision must be a mapping");
    const id = requiredString(entry, "id", "(unknown)");
    const applies = entry.applies_to;
    if (
      !Array.isArray(applies) ||
      applies.some((item) => typeof item !== "string")
    ) {
      throw new Error(
        `Decision ${id} needs applies_to as a list of glob strings`
      );
    }
    return {
      applies_to: applies,
      id,
      needs_review: entry.needs_review === true,
      rationale: requiredString(entry, "rationale", id),
      rule: requiredString(entry, "rule", id),
      title: requiredString(entry, "title", id),
    };
  });
}

export function readGraph(filePath = GRAPH_PATH): Graph | null {
  if (!fs.existsSync(filePath)) return null;
  const raw: unknown = JSON.parse(fs.readFileSync(filePath, "utf8"));
  if (!isRecord(raw) || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges))
    return null;
  return raw as unknown as Graph;
}

export function violationFingerprint(
  violation: Pick<Violation, "file" | "kind" | "value">
): string {
  return `${violation.file}\0${violation.kind}\0${violation.value}`;
}

export function countFingerprints(
  violations: Violation[]
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const violation of violations) {
    const key = violationFingerprint(violation);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

const CODE_SUMMARIES: Record<string, string> = {
  "src/app/page.tsx": "Redirects the index route to the workspace.",
  "src/app/layout.tsx":
    "Root layout that wraps the app in Clerk and the query provider.",
  "src/app/not-found.tsx": "Not-found screen in the reading theme.",
  "src/app/workspace/page.tsx":
    "Workspace home with the document list, quota, and cross-document chat.",
  "src/app/workspace/[docId]/page.tsx":
    "Opens one document and can highlight a citation from the query string.",
  "src/app/workspace/obligations/page.tsx": "Tenant-wide obligations screen.",
  "src/app/workspace/settings/page.tsx":
    "Settings screen for workspace members, invites, and the audit log.",
  "src/app/invite/[token]/page.tsx":
    "Accepts a workspace invite and switches into that organization.",
  "src/app/sign-in/[[...sign-in]]/page.tsx": "Clerk sign-in screen.",
  "src/app/sign-up/[[...sign-up]]/page.tsx": "Clerk sign-up screen.",
  "src/app/dev/context-canvas/[view]/page.tsx":
    "Dev-only LinkedIn artboard of the context graph. Returns 404 in production.",
  "src/middleware.ts":
    "Clerk gate. Sign-in, sign-up, health, and the dev context canvas are public.",
  "src/lib/api.ts":
    "Browser helpers that call the Next.js BFF, never FastAPI directly.",
  "src/lib/backend.ts":
    "Server-side FastAPI fetch that attaches the Clerk session token.",
  "src/lib/types.ts":
    "Response types shared by the BFF routes and client helpers.",
  "src/components/providers.tsx": "TanStack Query client provider for the app.",
  "src/components/document-list.tsx":
    "Lists uploaded documents with processing status and upload.",
  "src/components/upload-button.tsx":
    "Requests a presigned URL and uploads a file straight to storage.",
  "src/components/quota-bar.tsx":
    "Shows storage and question quota for the tenant.",
  "src/components/workspace-chat.tsx":
    "Cross-document question panel with citation chips.",
  "src/components/doc-layout.tsx":
    "Document workspace shell with the PDF, summary, chat, comments, and obligations.",
  "src/components/pdf-viewer.tsx": "PDF pager, zoom, and clause selection.",
  "src/components/pdf-renderer.tsx":
    "react-pdf page renderer with citation highlight overlays.",
  "src/components/chat-panel.tsx":
    "Document-scoped Q&A panel with clause citations.",
  "src/components/summary-card.tsx":
    "Shows extracted key clauses for one document.",
  "src/components/cross-ref-panel.tsx":
    "Lists cross-references for the active clause.",
  "src/components/comment-thread.tsx":
    "Clause comment thread with post, resolve, and delete.",
  "src/components/obligation-list.tsx":
    "Per-document obligations table with extract and resolve.",
  "src/components/obligations-dashboard.tsx":
    "Tenant-wide obligations table with type filters.",
  "src/components/audit-log-table.tsx":
    "Paginated audit-event table with an action filter.",
  "src/components/workspace-header.tsx":
    "Shared workspace chrome with navigation and the organization switcher.",
  "src/components/workspace-members.tsx":
    "Lists members and pending invites, and lets an admin manage them.",
  "src/components/accept-invite.tsx":
    "Redeems an invite token and activates that workspace.",
};

export function autoSummary(
  rel: string,
  kind: NodeType,
  exportName: string | null
): string {
  const known = CODE_SUMMARIES[rel];
  if (known) return known;
  if (kind === "page") {
    const route =
      rel.replace(/^src\/app\//, "").replace(/\/page\.tsx$/, "") || "/";
    return `Route /${route}.`;
  }
  if (kind === "layout") return `Layout ${rel}.`;
  if (kind === "component") return `UI component ${exportName ?? rel}.`;
  if (kind === "hook") return `Hook ${exportName ?? rel}.`;
  if (
    kind === "util" &&
    rel.startsWith("src/app/api/") &&
    rel.endsWith("/route.ts")
  ) {
    const route = rel.replace(/^src\/app\//, "").replace(/\/route\.ts$/, "");
    return `BFF route handler for /${route}.`;
  }
  if (rel === "src/middleware.ts") return "Request middleware.";
  return `Shared module ${rel}.`;
}

export function mergeSummary(
  previous: GraphNode | undefined,
  auto: string
): { summary: string; summaryOrigin: SummaryOrigin } {
  if (!previous) return { summary: auto, summaryOrigin: "auto" };
  if (previous.summaryOrigin === "human") {
    return { summary: previous.summary, summaryOrigin: "human" };
  }
  if (previous.summary !== auto) {
    return { summary: previous.summary, summaryOrigin: "human" };
  }
  return { summary: auto, summaryOrigin: "auto" };
}
