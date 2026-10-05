import {
  Node,
  type ArrowFunction,
  type FunctionDeclaration,
  type FunctionExpression,
  type Project,
  type SourceFile,
  SyntaxKind,
  type TypeNode,
} from "ts-morph";
import type { GraphEdge, GraphNode, NodeType, Violation } from "./graph-model";
import {
  autoSummary,
  mergeSummary,
  relFromFrontend,
  sortUnique,
} from "./graph-model";
import { scanStrings, type LocatedString, type TokenModel } from "./styles";

type FnLike = ArrowFunction | FunctionDeclaration | FunctionExpression;

interface ExportedFn {
  exportName: string;
  fn: FnLike;
  name: string;
}

const FRAMEWORK_EXPORTS = new Set([
  "dynamic",
  "metadata",
  "revalidate",
  "runtime",
  "viewport",
]);

export interface CodeExtract {
  edges: GraphEdge[];
  nodes: GraphNode[];
  violations: Violation[];
}

export function classifyFile(rel: string): NodeType | null {
  if (!rel.startsWith("src/") || rel.endsWith(".d.ts")) return null;
  if (rel.endsWith("/page.tsx")) return "page";
  if (rel.endsWith("/layout.tsx")) return "layout";
  if (rel.endsWith("/not-found.tsx")) return "page";
  if (rel.startsWith("src/components/") && rel.endsWith(".tsx"))
    return "component";
  if (
    rel.startsWith("src/hooks/") ||
    /\/use[A-Z][^/]*\.tsx?$/.test(rel) ||
    /\/use-[^/]+\.tsx?$/.test(rel)
  ) {
    return "hook";
  }
  if (rel.startsWith("src/lib/") && /\.tsx?$/.test(rel)) return "util";
  if (rel.startsWith("src/app/api/") && rel.endsWith("/route.ts"))
    return "util";
  if (rel === "src/middleware.ts") return "util";
  return null;
}

function nodeId(
  rel: string,
  kind: NodeType,
  exportName: string | null
): string {
  if (kind === "page") {
    if (rel === "src/app/page.tsx") return "page:home";
    if (rel === "src/app/not-found.tsx") return "page:not-found";
    const route = rel.replace(/^src\/app\//, "").replace(/\/page\.tsx$/, "");
    return `page:${route}`;
  }
  if (kind === "layout") {
    if (rel === "src/app/layout.tsx") return "layout:root";
    const route = rel.replace(/^src\/app\//, "").replace(/\/layout\.tsx$/, "");
    return `layout:${route}`;
  }
  if (kind === "component" || kind === "hook") {
    const fallback = pascal(rel);
    return `${kind}:${exportName && /^[A-Z]/.test(exportName) ? exportName : fallback}`;
  }
  if (rel === "src/middleware.ts") return "util:middleware";
  if (rel.startsWith("src/lib/")) {
    return `util:lib/${rel.slice("src/lib/".length).replace(/\.tsx?$/, "")}`;
  }
  if (rel.startsWith("src/app/api/") && rel.endsWith("/route.ts")) {
    return `util:route/${rel.slice("src/app/".length, -"/route.ts".length)}`;
  }
  return `util:${rel}`;
}

function pascal(rel: string): string {
  const base =
    rel
      .split("/")
      .pop()
      ?.replace(/\.tsx?$/, "") ?? "Module";
  return base
    .split(/[-_]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
}

function exportedFunctions(source: SourceFile): ExportedFn[] {
  const found: ExportedFn[] = [];
  for (const [exportName, declarations] of Array.from(
    source.getExportedDeclarations()
  )) {
    for (const declaration of declarations) {
      if (Node.isFunctionDeclaration(declaration)) {
        found.push({
          exportName,
          fn: declaration,
          name:
            declaration.getName() ??
            (exportName === "default" ? "default" : exportName),
        });
      } else if (Node.isVariableDeclaration(declaration)) {
        const initializer = declaration.getInitializer();
        if (
          initializer &&
          (Node.isArrowFunction(initializer) ||
            Node.isFunctionExpression(initializer))
        ) {
          found.push({
            exportName,
            fn: initializer,
            name: declaration.getName(),
          });
        }
      }
    }
  }
  return found;
}

function exportNames(source: SourceFile): string[] {
  const names: string[] = [];
  for (const [exportName, declarations] of Array.from(
    source.getExportedDeclarations()
  )) {
    if (FRAMEWORK_EXPORTS.has(exportName)) continue;
    if (exportName !== "default") {
      names.push(exportName);
      continue;
    }
    for (const declaration of declarations) {
      if (Node.isFunctionDeclaration(declaration) && declaration.getName()) {
        names.push(declaration.getName() ?? "default");
      } else if (Node.isVariableDeclaration(declaration)) {
        names.push(declaration.getName());
      } else {
        names.push("default");
      }
    }
  }
  return sortUnique(names);
}

function primaryFunction(
  source: SourceFile,
  kind: NodeType
): ExportedFn | undefined {
  const functions = exportedFunctions(source);
  if (kind === "page" || kind === "layout") {
    return functions.find((fn) => fn.exportName === "default") ?? functions[0];
  }
  return (
    functions.find((fn) => /^[A-Z]/.test(fn.name)) ??
    functions.find((fn) => fn.exportName === "default") ??
    functions[0]
  );
}

function propsOfType(typeNode: TypeNode, project: Project): string[] {
  if (Node.isTypeLiteral(typeNode)) {
    return typeNode
      .getMembers()
      .flatMap((member) =>
        Node.isPropertySignature(member) || Node.isMethodSignature(member)
          ? [member.getName()]
          : []
      );
  }
  if (Node.isIntersectionTypeNode(typeNode)) {
    return typeNode
      .getTypeNodes()
      .flatMap((part) => propsOfType(part, project));
  }
  if (!Node.isTypeReference(typeNode)) return [];
  const name = typeNode.getTypeName().getText().split(".").pop() ?? "";
  for (const file of project.getSourceFiles()) {
    const iface = file.getInterface(name);
    if (iface)
      return iface.getProperties().map((property) => property.getName());
    const alias = file.getTypeAlias(name)?.getTypeNode();
    if (alias) return propsOfType(alias, project);
  }
  return [];
}

function propNames(fn: FnLike, project: Project): string[] {
  const param = fn.getParameters()[0];
  if (!param) return [];
  const nameNode = param.getNameNode();
  if (Node.isObjectBindingPattern(nameNode)) {
    return sortUnique(
      nameNode.getElements().map((element) => {
        const property = element.getPropertyNameNode();
        if (property && Node.isIdentifier(property)) return property.getText();
        return element.getName();
      })
    );
  }
  const typeNode = param.getTypeNode();
  if (!typeNode) return [];
  return sortUnique(propsOfType(typeNode, project));
}

function locatedStrings(source: SourceFile): LocatedString[] {
  const parts: LocatedString[] = [];
  const add = (text: string, line: number) => {
    if (text.trim()) parts.push({ line, text });
  };
  for (const literal of source.getDescendantsOfKind(SyntaxKind.StringLiteral)) {
    const parent = literal.getParent();
    if (
      parent &&
      (Node.isImportDeclaration(parent) || Node.isExportDeclaration(parent))
    )
      continue;
    add(literal.getLiteralValue(), literal.getStartLineNumber());
  }
  for (const literal of source.getDescendantsOfKind(
    SyntaxKind.NoSubstitutionTemplateLiteral
  )) {
    add(literal.getLiteralValue(), literal.getStartLineNumber());
  }
  for (const template of source.getDescendantsOfKind(
    SyntaxKind.TemplateExpression
  )) {
    add(
      template.getHead().getLiteralText(),
      template.getHead().getStartLineNumber()
    );
    for (const span of template.getTemplateSpans()) {
      add(
        span.getLiteral().getLiteralText(),
        span.getLiteral().getStartLineNumber()
      );
    }
  }
  return parts;
}

function resolveSpecifier(
  fromRel: string,
  spec: string,
  known: Set<string>
): string | null {
  let base = "";
  if (spec.startsWith("@/")) base = `src/${spec.slice(2)}`;
  else if (spec.startsWith(".")) {
    const dir = fromRel.split("/").slice(0, -1).join("/");
    base = normalizePosix(`${dir}/${spec}`);
  } else return null;
  const extensions = [".tsx", ".ts", ".jsx", ".js"];
  const options = [base];
  if (!extensions.some((extension) => base.endsWith(extension))) {
    for (const extension of extensions) options.push(`${base}${extension}`);
    for (const extension of extensions)
      options.push(`${base}/index${extension}`);
  }
  return options.find((option) => known.has(option)) ?? null;
}

function normalizePosix(value: string): string {
  const parts: string[] = [];
  for (const part of value.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") parts.pop();
    else parts.push(part);
  }
  return parts.join("/");
}

function jsxNames(source: SourceFile): string[] {
  const names: string[] = [];
  const take = (tag: Node) => {
    if (Node.isIdentifier(tag)) names.push(tag.getText());
  };
  for (const element of source.getDescendantsOfKind(
    SyntaxKind.JsxOpeningElement
  )) {
    take(element.getTagNameNode());
  }
  for (const element of source.getDescendantsOfKind(
    SyntaxKind.JsxSelfClosingElement
  )) {
    take(element.getTagNameNode());
  }
  return names;
}

function disambiguate(nodes: GraphNode[]): void {
  const groups = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    const group = groups.get(node.id) ?? [];
    group.push(node);
    groups.set(node.id, group);
  }
  for (const group of Array.from(groups.values())) {
    if (group.length < 2) continue;
    for (const node of group) {
      const slug = (node.path ?? "unknown").replace(/[^\w]+/g, "-");
      node.id = `${node.id}@${slug}`;
    }
  }
}

export function extractCode(
  project: Project,
  tokens: TokenModel,
  previous: Map<string, GraphNode>
): CodeExtract {
  const files = project
    .getSourceFiles()
    .map((source) => ({ rel: relFromFrontend(source.getFilePath()), source }))
    .filter((file) => classifyFile(file.rel) !== null)
    .sort((a, b) => a.rel.localeCompare(b.rel));

  const known = new Set(files.map((file) => file.rel));
  const nodes: GraphNode[] = [];
  const pathToId = new Map<string, string>();

  for (const file of files) {
    const kind = classifyFile(file.rel);
    if (!kind) continue;
    const primary = primaryFunction(file.source, kind);
    const exportName =
      primary && /^[A-Z]/.test(primary.name) ? primary.name : null;
    const id = nodeId(file.rel, kind, exportName);
    const auto = autoSummary(
      file.rel,
      kind,
      exportName ?? primary?.name ?? null
    );
    const summary = mergeSummary(previous.get(id), auto);
    const node: GraphNode = {
      exports: exportNames(file.source),
      id,
      path: file.rel,
      summary: summary.summary,
      summaryOrigin: summary.summaryOrigin,
      type: kind,
    };
    if (
      primary &&
      (kind === "component" ||
        kind === "hook" ||
        kind === "page" ||
        kind === "layout")
    ) {
      const props = propNames(primary.fn, project);
      if (props.length > 0) node.props = props;
    }
    nodes.push(node);
  }
  disambiguate(nodes);
  for (const node of nodes) {
    if (node.path) pathToId.set(node.path, node.id);
  }

  const edges: GraphEdge[] = [];
  const edgeKeys = new Set<string>();
  const addEdge = (edge: GraphEdge) => {
    const key = `${edge.from}\0${edge.to}\0${edge.type}`;
    if (edgeKeys.has(key) || edge.from === edge.to) return;
    edgeKeys.add(key);
    edges.push(edge);
  };

  const violations: Violation[] = [];
  for (const file of files) {
    const fromId = pathToId.get(file.rel);
    if (!fromId) continue;
    const localToPath = new Map<string, string>();
    for (const specifier of file.source.getImportDeclarations()) {
      const resolved = resolveSpecifier(
        file.rel,
        specifier.getModuleSpecifierValue(),
        known
      );
      if (!resolved) continue;
      const target = pathToId.get(resolved);
      if (!target) continue;
      addEdge({ from: fromId, to: target, type: "imports" });
      const localName = (name: string, alias: string | undefined) =>
        alias ?? name;
      const defaultImport = specifier.getDefaultImport();
      if (defaultImport) localToPath.set(defaultImport.getText(), resolved);
      for (const named of specifier.getNamedImports()) {
        localToPath.set(
          localName(named.getName(), named.getAliasNode()?.getText()),
          resolved
        );
      }
    }
    for (const declaration of file.source.getVariableDeclarations()) {
      const initializer = declaration.getInitializer()?.getText() ?? "";
      const dynamic = /import\(\s*["']([^"']+)["']\s*\)/.exec(initializer);
      if (!dynamic?.[1]) continue;
      const resolved = resolveSpecifier(file.rel, dynamic[1], known);
      if (!resolved) continue;
      const target = pathToId.get(resolved);
      if (!target) continue;
      addEdge({ from: fromId, to: target, type: "imports" });
      localToPath.set(declaration.getName(), resolved);
    }
    for (const tag of jsxNames(file.source)) {
      const resolved = localToPath.get(tag);
      const target = resolved ? pathToId.get(resolved) : undefined;
      if (target) addEdge({ from: fromId, to: target, type: "renders" });
    }

    const scanned = scanStrings(file.rel, locatedStrings(file.source), tokens);
    for (const tokenId of scanned.tokenIds) {
      addEdge({ from: fromId, to: tokenId, type: "uses_token" });
    }
    violations.push(...scanned.violations);
  }

  return { edges, nodes, violations };
}
