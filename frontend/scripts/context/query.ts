import path from "node:path";
import {
  DECISIONS_PATH,
  FRONTEND_ROOT,
  GRAPH_PATH,
  loadDecisions,
  matchesAnyGlob,
  oneLine,
  readGraph,
  type Graph,
  type GraphNode,
} from "./graph-model";

const TOKEN_LIMIT = 1500;

function normalizeArg(arg: string): string {
  let filePath = arg.trim().replace(/\\/g, "/");
  if (path.isAbsolute(arg)) {
    filePath = path.relative(FRONTEND_ROOT, arg).split(path.sep).join("/");
  }
  if (filePath.startsWith("./")) filePath = filePath.slice(2);
  if (filePath.startsWith("frontend/"))
    filePath = filePath.slice("frontend/".length);
  return filePath;
}

function tokenLabel(id: string): string {
  if (id.startsWith("token:color."))
    return id.slice("token:color.".length).replace(/\./g, "-");
  if (id.startsWith("token:font."))
    return `font-${id.slice("token:font.".length)}`;
  if (id.startsWith("token:shadow."))
    return `shadow-${id.slice("token:shadow.".length)}`;
  if (id.startsWith("token:animation."))
    return `animate-${id.slice("token:animation.".length)}`;
  if (id.startsWith("token:class.")) return id.slice("token:class.".length);
  return id;
}

function estimate(text: string): number {
  return Math.ceil(text.length / 4);
}

function nodeLine(node: GraphNode, via?: string): string {
  const where = node.path ? ` \`${node.path}\`` : "";
  const how = via ? ` (${via})` : "";
  const review = node.needsReview ? " [needs review]" : "";
  return `- \`${node.id}\`${how}${where}${review} — ${oneLine(node.summary)}`;
}

interface Section {
  id: string;
  lines: string[];
  priority: number;
  title: string;
}

function render(sections: Section[]): string {
  return sections
    .filter((section) => section.lines.length > 0)
    .map((section) => `## ${section.title}\n${section.lines.join("\n")}`)
    .join("\n\n");
}

function fit(
  header: string,
  sections: Section[]
): { dropped: number; text: string } {
  const ranked = [...sections].sort((a, b) => a.priority - b.priority);
  let dropped = 0;
  const body = () => [header, render(sections)].filter(Boolean).join("\n\n");
  while (estimate(body()) > TOKEN_LIMIT) {
    const distant = ranked.find(
      (section) => section.priority < 90 && section.lines.length > 0
    );
    const target =
      distant ??
      ranked.find(
        (section) => section.priority < 100 && section.lines.length > 0
      );
    if (!target) break;
    target.lines.pop();
    dropped += 1;
  }
  return { dropped, text: `${body()}\n` };
}

function decisionsFor(
  filePath: string,
  graph: Graph,
  node: GraphNode | undefined
): GraphNode[] {
  if (node) {
    const ids = new Set(
      graph.edges
        .filter(
          (edge) => edge.type === "constrained_by" && edge.from === node.id
        )
        .map((edge) => edge.to)
    );
    return graph.nodes.filter((item) => ids.has(item.id));
  }
  const wanted = new Set(
    loadDecisions(DECISIONS_PATH)
      .filter((decision) => matchesAnyGlob(decision.applies_to, filePath))
      .map((decision) => `decision:${decision.id}`)
  );
  return graph.nodes.filter((item) => wanted.has(item.id));
}

function catalog(graph: Graph, prefix: string): string[] {
  return graph.nodes
    .filter((node) => node.id.startsWith(prefix))
    .map((node) => tokenLabel(node.id))
    .sort((a, b) => a.localeCompare(b));
}

function main(): void {
  const arg = process.argv.slice(2).find((value) => value !== "--");
  if (!arg) {
    console.error("Usage: npm run context -- <file-path>");
    process.exitCode = 1;
    return;
  }
  const filePath = normalizeArg(arg);
  const graph = readGraph(GRAPH_PATH);
  if (!graph) {
    console.error(
      "context/graph.json is missing. Run npm run context:build first."
    );
    process.exitCode = 1;
    return;
  }
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const matches = graph.nodes.filter(
    (node) => node.path === filePath && node.type !== "token"
  );
  const node = matches[0];

  const header = node
    ? `# Context: ${filePath}\n\n**${node.id}** (${node.type}) — ${oneLine(node.summary)}`
    : `# Context: ${filePath}\n\nThis file is not in the graph yet. The decisions and tokens below still apply. Run \`npm run context:build\` after you add it.`;

  const decisionLines = decisionsFor(filePath, graph, node).map((decision) => {
    const review = decision.needsReview ? " [needs review]" : "";
    const title = decision.title ?? decision.id;
    const why = decision.rationale ? ` ${decision.rationale}` : "";
    return `- **${title}**${review}: ${oneLine(decision.summary)}${why}`;
  });

  const tokenLines = [
    `Colors: ${catalog(graph, "token:color.").join(", ")}`,
    `Fonts: ${catalog(graph, "token:font.").join(", ")}`,
    `Shadows: ${catalog(graph, "token:shadow.").join(", ")}`,
    `Classes: ${catalog(graph, "token:class.").join(", ")}`,
  ];

  const sections: Section[] = [
    {
      id: "decisions",
      lines: decisionLines,
      priority: 100,
      title: "Decisions",
    },
    { id: "tokens", lines: tokenLines, priority: 95, title: "Tokens to use" },
  ];

  if (!node) {
    sections.push({
      id: "reuse",
      lines: graph.nodes
        .filter((item) => item.type === "component")
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((item) => nodeLine(item)),
      priority: 40,
      title: "Reuse a component before creating one",
    });
  } else {
    const outgoing = (type: Graph["edges"][number]["type"]) =>
      graph.edges.filter((edge) => edge.from === node.id && edge.type === type);
    const incoming = (type: Graph["edges"][number]["type"]) =>
      graph.edges.filter((edge) => edge.to === node.id && edge.type === type);

    const used = outgoing("uses_token")
      .map((edge) => tokenLabel(edge.to))
      .sort((a, b) => a.localeCompare(b));
    sections.push({
      id: "used",
      lines: used.length > 0 ? [used.join(", ")] : ["None yet."],
      priority: 90,
      title: "Tokens this file uses",
    });
    sections.push({
      id: "components",
      lines: [
        graph.nodes
          .filter((item) => item.type === "component")
          .map((item) => item.id.replace(/^component:/, ""))
          .sort((a, b) => a.localeCompare(b))
          .join(", "),
      ],
      priority: 60,
      title: "Components already in the graph",
    });

    const relate = (
      id: string,
      title: string,
      edges: Graph["edges"],
      direction: "to" | "from",
      via: string,
      priority: number
    ) => {
      const lines = edges
        .map((edge) => byId.get(direction === "to" ? edge.to : edge.from))
        .filter((item): item is GraphNode => Boolean(item))
        .filter((item) => item.type !== "token" && item.type !== "decision")
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((item) => nodeLine(item, via));
      sections.push({ id, lines, priority, title });
    };

    relate("imports", "Imports", outgoing("imports"), "to", "imports", 80);
    relate("renders", "Renders", outgoing("renders"), "to", "renders", 80);
    relate(
      "rendered-by",
      "Rendered by",
      incoming("renders"),
      "from",
      "rendered by",
      75
    );
    relate(
      "imported-by",
      "Imported by",
      incoming("imports"),
      "from",
      "imported by",
      70
    );

    const renderedTargets = new Set(outgoing("renders").map((edge) => edge.to));
    const siblingIds = new Set<string>();
    for (const edge of graph.edges) {
      if (
        edge.type !== "renders" ||
        edge.from === node.id ||
        !renderedTargets.has(edge.to)
      )
        continue;
      siblingIds.add(edge.from);
    }
    sections.push({
      id: "siblings",
      lines: Array.from(siblingIds)
        .map((id) => byId.get(id))
        .filter((item): item is GraphNode => Boolean(item))
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((item) => nodeLine(item, "shares a rendered component")),
      priority: 30,
      title: "Siblings",
    });

    const direct = new Set<string>([node.id]);
    for (const section of sections) {
      if (section.priority >= 70) {
        for (const line of section.lines) {
          const match = /`([^`]+)`/.exec(line);
          if (match?.[1]) direct.add(match[1]);
        }
      }
    }
    const depth2: GraphNode[] = [];
    const seen = new Set<string>([node.id]);
    const queue: Array<{ depth: number; id: string }> = [
      { depth: 0, id: node.id },
    ];
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current || current.depth >= 2) continue;
      for (const edge of graph.edges) {
        if (edge.type !== "imports" && edge.type !== "renders") continue;
        const nextId =
          edge.from === current.id
            ? edge.to
            : edge.to === current.id
              ? edge.from
              : null;
        if (!nextId || seen.has(nextId)) continue;
        const next = byId.get(nextId);
        if (!next || next.type === "token" || next.type === "decision")
          continue;
        seen.add(nextId);
        const depth = current.depth + 1;
        if (depth === 2 && !direct.has(nextId)) depth2.push(next);
        queue.push({ depth, id: nextId });
      }
    }
    sections.push({
      id: "depth2",
      lines: depth2
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((item) => nodeLine(item, "depth 2")),
      priority: 10,
      title: "Also nearby",
    });

    if (node.props && node.props.length > 0) {
      sections.push({
        id: "props",
        lines: [node.props.join(", ")],
        priority: 85,
        title: "Props",
      });
    }
    if (node.exports && node.exports.length > 0) {
      sections.push({
        id: "exports",
        lines: [node.exports.join(", ")],
        priority: 85,
        title: "Exports",
      });
    }
  }

  const fitted = fit(header, sections);
  process.stdout.write(fitted.text);
  if (fitted.dropped > 0) {
    console.error(
      `Truncated ${fitted.dropped} distant lines to stay under ${TOKEN_LIMIT} tokens.`
    );
  }
}

main();
