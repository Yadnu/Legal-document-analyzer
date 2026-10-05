import { Node, type ObjectLiteralExpression, type SourceFile } from "ts-morph";
import type {
  GraphEdge,
  GraphNode,
  Violation,
  ViolationKind,
} from "./graph-model";
import { oneLine, sortUnique } from "./graph-model";

export interface DesignToken {
  id: string;
  summary: string;
}

interface ColorToken extends DesignToken {
  key: string;
}

interface ExactToken extends DesignToken {
  className: string;
}

export interface TokenModel {
  colorKeys: Map<string, string>;
  componentExtends: GraphEdge[];
  exact: Map<string, string>;
  namespaces: Set<string>;
  nodes: GraphNode[];
}

const PALETTE = new Set([
  "slate",
  "gray",
  "zinc",
  "neutral",
  "stone",
  "red",
  "orange",
  "amber",
  "yellow",
  "lime",
  "green",
  "emerald",
  "teal",
  "cyan",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "fuchsia",
  "pink",
  "rose",
  "white",
  "black",
]);

const SHADES = new Set([
  "50",
  "100",
  "200",
  "300",
  "400",
  "500",
  "600",
  "700",
  "800",
  "900",
  "950",
]);

const COLOR_PREFIXES = [
  "placeholder",
  "ring-offset",
  "decoration",
  "border-x",
  "border-y",
  "border-t",
  "border-r",
  "border-b",
  "border-l",
  "outline",
  "divide",
  "accent",
  "caret",
  "stroke",
  "border",
  "shadow",
  "ring",
  "from",
  "via",
  "fill",
  "text",
  "bg",
  "to",
].sort((a, b) => b.length - a.length);

const SPACING_UTILITIES = new Set([
  "p",
  "px",
  "py",
  "pt",
  "pr",
  "pb",
  "pl",
  "m",
  "mx",
  "my",
  "mt",
  "mr",
  "mb",
  "ml",
  "gap",
  "gap-x",
  "gap-y",
  "space-x",
  "space-y",
]);

function propMap(object: ObjectLiteralExpression): Map<string, Node> {
  const map = new Map<string, Node>();
  for (const property of object.getProperties()) {
    if (!Node.isPropertyAssignment(property)) continue;
    const initializer = property.getInitializer();
    if (!initializer) continue;
    map.set(property.getName().replace(/^['"]|['"]$/g, ""), initializer);
  }
  return map;
}

function stringValue(node: Node | undefined): string | null {
  if (!node) return null;
  if (
    Node.isStringLiteral(node) ||
    Node.isNoSubstitutionTemplateLiteral(node)
  ) {
    return node.getLiteralValue();
  }
  return null;
}

function walkColors(
  node: Node,
  parts: string[],
  out: Array<{ parts: string[]; value: string }>
): void {
  const literal = stringValue(node);
  if (literal !== null) {
    out.push({ parts: [...parts], value: literal });
    return;
  }
  if (!Node.isObjectLiteralExpression(node)) return;
  for (const [name, child] of Array.from(propMap(node))) {
    walkColors(child, name === "DEFAULT" ? parts : [...parts, name], out);
  }
}

function stringList(node: Node | undefined): string[] {
  if (!node || !Node.isArrayLiteralExpression(node)) return [];
  return node
    .getElements()
    .map((element) => stringValue(element))
    .filter((value): value is string => value !== null);
}

function pushColor(colors: ColorToken[], parts: string[], value: string): void {
  const key = parts.join("-");
  const id = `token:color.${parts.join(".")}`;
  colors.push({
    id,
    key,
    summary: `Color ${key} (${value}).`,
  });
}

function layerBody(css: string, layerName: string): string | null {
  const match = new RegExp(`@layer\\s+${layerName}\\s*\\{`).exec(css);
  if (!match) return null;
  const open = css.indexOf("{", match.index);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  return null;
}

interface ClassRule {
  applyClasses: string[];
  name: string;
}

function classRules(body: string): ClassRule[] {
  const rules: ClassRule[] = [];
  const finder = /\.([A-Za-z0-9_-]+)\s*\{/g;
  let match = finder.exec(body);
  while (match) {
    const name = match[1] ?? "";
    const open = match.index + match[0].length - 1;
    let depth = 0;
    let close = open;
    for (let i = open; i < body.length; i += 1) {
      if (body[i] === "{") depth += 1;
      else if (body[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          close = i;
          break;
        }
      }
    }
    const block = body.slice(open + 1, close);
    const apply = /@apply\s+([^;]+);/.exec(block);
    const applyClasses = apply?.[1]?.trim().split(/\s+/).filter(Boolean) ?? [];
    rules.push({ applyClasses, name });
    match = finder.exec(body);
  }
  return rules;
}

export function loadTokens(
  tailwindSource: SourceFile,
  css: string
): TokenModel {
  const colors: ColorToken[] = [];
  const exact: ExactToken[] = [];
  const decl = tailwindSource.getVariableDeclaration("config");
  const init = decl?.getInitializer();
  if (init && Node.isObjectLiteralExpression(init)) {
    const theme = propMap(init).get("theme");
    if (theme && Node.isObjectLiteralExpression(theme)) {
      const themeProps = propMap(theme);
      const extendNode = themeProps.get("extend");
      const extend =
        extendNode && Node.isObjectLiteralExpression(extendNode)
          ? propMap(extendNode)
          : themeProps;
      const colorNode = extend.get("colors");
      if (colorNode) {
        const flat: Array<{ parts: string[]; value: string }> = [];
        walkColors(colorNode, [], flat);
        for (const color of flat) {
          if (color.parts.length === 0) continue;
          pushColor(colors, color.parts, color.value);
        }
      }
      const fonts = extend.get("fontFamily");
      if (fonts && Node.isObjectLiteralExpression(fonts)) {
        for (const [name, value] of Array.from(propMap(fonts))) {
          const stack = stringList(value);
          exact.push({
            className: `font-${name}`,
            id: `token:font.${name}`,
            summary: `Font ${name} (${stack.join(", ") || name}).`,
          });
        }
      }
      const shadows = extend.get("boxShadow");
      if (shadows && Node.isObjectLiteralExpression(shadows)) {
        for (const [name, value] of Array.from(propMap(shadows))) {
          exact.push({
            className: `shadow-${name}`,
            id: `token:shadow.${name}`,
            summary: `Shadow ${name} (${oneLine(stringValue(value) ?? name)}).`,
          });
        }
      }
      const animations = extend.get("animation");
      if (animations && Node.isObjectLiteralExpression(animations)) {
        for (const [name, value] of Array.from(propMap(animations))) {
          exact.push({
            className: `animate-${name}`,
            id: `token:animation.${name}`,
            summary: `Animation ${name} (${oneLine(stringValue(value) ?? name)}).`,
          });
        }
      }
    }
  }

  const colorKeys = new Map(colors.map((color) => [color.key, color.id]));
  const exactMap = new Map(exact.map((token) => [token.className, token.id]));
  const namespaces = new Set(
    colors.map((color) => color.key.split("-")[0] ?? color.key)
  );
  const partial: TokenModel = {
    colorKeys,
    componentExtends: [],
    exact: exactMap,
    namespaces,
    nodes: [],
  };

  const components = layerBody(css, "components");
  const classTokens: ExactToken[] = [];
  const extendEdges: GraphEdge[] = [];
  const rules = components ? classRules(components) : [];
  for (const rule of rules) {
    const id = `token:class.${rule.name}`;
    classTokens.push({
      className: rule.name,
      id,
      summary: `Component class ${rule.name}.`,
    });
    exactMap.set(rule.name, id);
  }
  for (const rule of rules) {
    const id = `token:class.${rule.name}`;
    const targets = sortUnique(
      rule.applyClasses
        .map((className) => classifyClass(className, partial).tokenId)
        .filter((tokenId): tokenId is string =>
          Boolean(tokenId && tokenId !== id)
        )
    );
    for (const target of targets) {
      extendEdges.push({ from: id, to: target, type: "extends" });
    }
  }

  const nodes: GraphNode[] = [...colors, ...exact, ...classTokens]
    .map((token) => ({
      id: token.id,
      path: token.id.startsWith("token:class.")
        ? "src/app/globals.css"
        : "tailwind.config.ts",
      summary: token.summary,
      type: "token" as const,
    }))
    .sort((a, b) => a.id.localeCompare(b.id));

  return {
    colorKeys,
    componentExtends: extendEdges,
    exact: exactMap,
    namespaces,
    nodes,
  };
}

export interface ClassHit {
  tokenId?: string;
  violation?: Pick<Violation, "kind" | "message" | "value">;
}

function stripVariants(className: string): string {
  let rest = className.trim();
  while (rest.startsWith("!")) rest = rest.slice(1);
  while (true) {
    const match = /^((?:\[[^\]]+\]|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*):)(.+)$/.exec(
      rest
    );
    if (!match?.[2]) break;
    rest = match[2];
    while (rest.startsWith("!")) rest = rest.slice(1);
  }
  return rest;
}

function isLength(value: string): boolean {
  return /^-?\d*\.?\d+(px|rem|em|ch|ex|vh|vw|vmin|vmax|%)$/.test(value);
}

function isColorValue(value: string): boolean {
  const inner = value.replace(/^(color|length):/, "");
  return (
    /^#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})$/.test(
      inner
    ) || /^(?:rgba?|hsla?)\(/i.test(inner)
  );
}

function colorMessage(value: string): string {
  return `Hardcoded color ${value}. Use surface, ink, gold, or status tokens.`;
}

function paletteName(base: string): string | null {
  if (PALETTE.has(base)) return base;
  const split = base.lastIndexOf("-");
  if (split <= 0) return null;
  const name = base.slice(0, split);
  const shade = base.slice(split + 1);
  if (PALETTE.has(name) && SHADES.has(shade)) return base;
  return null;
}

export function classifyClass(raw: string, tokens: TokenModel): ClassHit {
  const original = raw.trim().replace(/[;,]+$/g, "");
  if (
    !original ||
    original.includes("{") ||
    (original.includes("(") && !original.includes("["))
  ) {
    return {};
  }
  const core = stripVariants(original);
  if (!core) return {};

  const arbitrary = /^(-?[a-z][a-z0-9-]*)-\[(.+)\]$/i.exec(core);
  if (arbitrary) {
    const utility = (arbitrary[1] ?? "").replace(/^-/, "");
    const inner = arbitrary[2] ?? "";
    if (inner.startsWith("var(")) return {};
    if (SPACING_UTILITIES.has(utility)) {
      return violation(
        original,
        "hardcoded-spacing",
        `Arbitrary spacing ${original}. Use the spacing scale.`
      );
    }
    if (utility === "text" && isLength(inner)) {
      return violation(
        original,
        "hardcoded-font-size",
        `Arbitrary font size ${original}. Use the type scale (text-xs, text-sm, text-base).`
      );
    }
    if (
      isColorValue(inner) ||
      /#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\(/i.test(inner)
    ) {
      return violation(original, "hardcoded-color", colorMessage(original));
    }
    return {};
  }

  const exact = tokens.exact.get(core);
  if (exact) return { tokenId: exact };

  for (const prefix of COLOR_PREFIXES) {
    if (!core.startsWith(`${prefix}-`)) continue;
    const rest = core.slice(prefix.length + 1);
    const base = rest.split("/")[0] ?? "";
    if (!/[a-z]/i.test(base)) break;
    const tokenId = tokens.colorKeys.get(base);
    if (tokenId) return { tokenId };
    const first = base.split("-")[0] ?? "";
    if (tokens.namespaces.has(first)) {
      return violation(
        original,
        "unknown-token",
        `Undefined token ${original}. It is not declared in tailwind.config.ts.`
      );
    }
    if (paletteName(base)) {
      return violation(original, "hardcoded-color", colorMessage(original));
    }
    break;
  }

  return {};
}

function violation(
  value: string,
  kind: ViolationKind,
  message: string
): ClassHit {
  return { violation: { kind, message, value } };
}

const HEX_RE =
  /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b/g;
const FUNC_COLOR_RE = /(?:rgba?|hsla?)\([^)]*\)/gi;

export interface LocatedString {
  line: number;
  text: string;
}

export function scanStrings(
  file: string,
  parts: LocatedString[],
  tokens: TokenModel
): { tokenIds: string[]; violations: Violation[] } {
  const tokenIds = new Set<string>();
  const violations: Violation[] = [];
  const seen = new Set<string>();

  const addViolation = (violationItem: Violation) => {
    const key = `${violationItem.line}\0${violationItem.kind}\0${violationItem.value}`;
    if (seen.has(key)) return;
    seen.add(key);
    violations.push(violationItem);
  };

  for (const part of parts) {
    const pieces = part.text.split(/\s+/).filter(Boolean);
    let cursor = 0;
    for (const piece of pieces) {
      const index = part.text.indexOf(piece, cursor);
      const line = lineAt(part.line, part.text, index < 0 ? 0 : index);
      if (index >= 0) cursor = index + piece.length;
      const hit = classifyClass(piece, tokens);
      if (hit.tokenId) tokenIds.add(hit.tokenId);
      if (hit.violation) {
        addViolation({ file, line, ...hit.violation });
      }
    }

    scanRawColors(file, part.text, part.line, addViolation);
  }

  const pruned = violations.filter((item) => {
    const isRaw =
      item.value.startsWith("#") || /^(?:rgba?|hsla?)\(/i.test(item.value);
    if (!isRaw) return true;
    return !violations.some(
      (other) =>
        other !== item &&
        other.line === item.line &&
        other.value.includes(item.value) &&
        other.value !== item.value
    );
  });

  return {
    tokenIds: Array.from(tokenIds).sort((a, b) => a.localeCompare(b)),
    violations: pruned,
  };
}

function lineAt(startLine: number, text: string, index: number): number {
  let line = startLine;
  for (let i = 0; i < index && i < text.length; i += 1) {
    if (text[i] === "\n") line += 1;
  }
  return line;
}

function scanRawColors(
  file: string,
  text: string,
  startLine: number,
  addViolation: (violationItem: Violation) => void
): void {
  for (const match of Array.from(text.matchAll(HEX_RE))) {
    const value = match[0] ?? "";
    const line = lineAt(startLine, text, match.index ?? 0);
    addViolation({
      file,
      kind: "hardcoded-color",
      line,
      message: colorMessage(value),
      value,
    });
  }
  for (const match of Array.from(text.matchAll(FUNC_COLOR_RE))) {
    const value = match[0] ?? "";
    const line = lineAt(startLine, text, match.index ?? 0);
    addViolation({
      file,
      kind: "hardcoded-color",
      line,
      message: colorMessage(value),
      value,
    });
  }
}

export function scanStylesheet(
  file: string,
  css: string,
  tokens: TokenModel
): Violation[] {
  const masked = css.replace(/\/\*[\s\S]*?\*\//g, (comment) =>
    comment.replace(/[^\n]/g, " ")
  );
  const applyParts: LocatedString[] = [];
  const applyRe = /@apply\s+([^;]+);/g;
  let match = applyRe.exec(masked);
  while (match) {
    const body = match[1] ?? "";
    const line = lineAt(1, masked, match.index);
    applyParts.push({ line, text: body });
    match = applyRe.exec(masked);
  }
  const scanned = scanStrings(file, applyParts, tokens);
  const raw = scanStrings(file, [{ line: 1, text: masked }], tokens);
  const applyValues = new Set(scanned.violations.map((item) => item.value));
  const rawOnly = raw.violations.filter((item) => {
    if (item.kind !== "hardcoded-color") return false;
    if (applyValues.has(item.value)) return false;
    return !scanned.violations.some(
      (existing) =>
        existing.line === item.line && existing.value.includes(item.value)
    );
  });
  return [...scanned.violations, ...rawOnly].sort(compareViolations);
}

export function compareViolations(a: Violation, b: Violation): number {
  return (
    a.file.localeCompare(b.file) ||
    a.line - b.line ||
    a.kind.localeCompare(b.kind) ||
    a.value.localeCompare(b.value)
  );
}

export function dedupeViolations(violations: Violation[]): Violation[] {
  const seen = new Set<string>();
  const out: Violation[] = [];
  for (const violation of [...violations].sort(compareViolations)) {
    const key = `${violation.file}\0${violation.line}\0${violation.kind}\0${violation.value}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(violation);
  }
  return out;
}
