import { notFound } from "next/navigation";
import type { CanvasNode, GraphModel, ViolationsModel } from "../load-context";
import { loadGraph, loadViolations } from "../load-context";

export const dynamic = "force-dynamic";

const DEFAULT_NODE = "component:WorkspaceChat";

const SEGMENT_CLASS: Record<string, string> = {
  "hardcoded-color": "bg-status-failed",
  "hardcoded-font-size": "bg-ink",
  "unknown-token": "bg-status-ready",
};

function segmentClass(kind: string): string {
  return SEGMENT_CLASS[kind] ?? "bg-ink-muted";
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen items-center justify-center overflow-hidden bg-surface-deep">
      <style>
        {
          "html,body{overflow:hidden!important;height:100%}#clerk-components,nextjs-portal,.tsqd-open-btn-container,.tsqd-parent-container{display:none!important}"
        }
      </style>
      {children}
    </div>
  );
}

function Artboard({ children }: { children: React.ReactNode }) {
  return (
    <article
      data-artboard
      className="flex h-[1350px] w-[1080px] flex-col overflow-hidden bg-surface-deep p-16 text-ink"
    >
      {children}
    </article>
  );
}

function Footer({ scanDate }: { scanDate: string }) {
  return (
    <footer className="mt-auto flex items-end justify-between pt-8 font-sans text-2xl text-ink-muted">
      <p>Legal Document Navigator · context graph</p>
      <p className="font-mono">{scanDate}</p>
    </footer>
  );
}

function ViolationsArtboard({ model }: { model: ViolationsModel }) {
  const scale = model.rows.reduce((max, row) => Math.max(max, row.total), 1);
  return (
    <Artboard>
      <header>
        <h1 className="font-display text-5xl leading-none text-ink">
          {model.total} design-system violations
        </h1>
        <div className="mt-6 h-1 w-16 bg-gold" />
        <p className="mt-6 font-sans text-2xl leading-snug text-ink-muted">
          {model.topTwoCount} of them in two tables built late in long agent
          sessions
        </p>
      </header>
      <div className="mt-8 flex flex-wrap gap-x-8 gap-y-3">
        {model.categories.map((category) => (
          <div key={category.kind} className="flex items-center gap-3">
            <span
              className={`size-6 rounded-sm ${segmentClass(category.kind)}`}
            />
            <span className="font-sans text-2xl text-ink">
              {category.label}
            </span>
            <span className="font-mono text-2xl text-ink-muted">
              {category.count}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-10 flex min-h-0 flex-1 flex-col justify-between">
        {model.rows.map((row) => (
          <div key={row.file} className="flex items-center gap-4">
            <div
              className={
                row.highlighted
                  ? "h-8 w-1.5 shrink-0 rounded-full bg-gold"
                  : "h-8 w-1.5 shrink-0"
              }
            />
            <p
              className={
                row.highlighted
                  ? "shrink-0 whitespace-nowrap font-mono text-2xl font-medium text-ink"
                  : "shrink-0 whitespace-nowrap font-mono text-2xl text-ink"
              }
              style={{ width: `${model.labelCh}ch` }}
            >
              {row.label}
            </p>
            <div className="flex h-8 min-w-0 flex-1 overflow-hidden rounded-sm bg-surface-card">
              <div className="w-px shrink-0 bg-ink-faint" />
              <div
                className="flex h-full gap-1"
                style={{ width: `${(row.total / scale) * 100}%` }}
              >
                {row.segments.map((segment) => (
                  <div
                    key={segment.kind}
                    className={segmentClass(segment.kind)}
                    style={{ flexBasis: 0, flexGrow: segment.count }}
                  />
                ))}
              </div>
            </div>
            <p
              className="shrink-0 text-right font-mono text-2xl text-ink"
              style={{ width: `${model.countCh}ch` }}
            >
              {row.total}
            </p>
          </div>
        ))}
      </div>
      <Footer scanDate={model.scanDate} />
    </Artboard>
  );
}

function NodeCard({ node, focus }: { node: CanvasNode; focus?: boolean }) {
  return (
    <div
      className={
        focus
          ? "rounded-xl border-2 border-gold bg-surface-card px-6 py-5 shadow-gold"
          : "rounded-xl border border-ink-faint/40 bg-surface-card px-6 py-5"
      }
    >
      <p className="font-sans text-2xl text-ink-muted">{node.typeLabel}</p>
      <p
        className={
          focus
            ? "mt-1 break-words font-sans text-4xl leading-tight text-ink"
            : "mt-1 break-words font-sans text-3xl leading-tight text-ink"
        }
      >
        {node.name}
      </p>
    </div>
  );
}

function FocusEdges({ count }: { count: number }) {
  if (count <= 0) return null;
  if (count === 1) return <div className="h-14 w-0.5 bg-gold" />;
  if (count === 2) {
    return (
      <svg
        aria-hidden
        className="h-16 w-full text-gold"
        preserveAspectRatio="none"
        viewBox="0 0 100 48"
      >
        <path
          d="M50 0 V16 H25 V48 M50 16 H75 V48"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    );
  }
  return (
    <div className="flex w-full flex-col items-center">
      <div className="h-8 w-0.5 bg-gold" />
      <div className="h-0.5 w-full bg-gold" />
    </div>
  );
}

function GraphArtboard({ model }: { model: GraphModel }) {
  return (
    <Artboard>
      <header>
        <h1 className="max-w-[22ch] font-display text-5xl leading-tight text-ink">
          What the agent sees before editing a file
        </h1>
        <div className="mt-6 h-1 w-16 bg-gold" />
      </header>
      <div className="mt-10 flex min-h-0 flex-1 items-center gap-8">
        <div className="flex min-w-0 flex-1 flex-col items-center justify-center">
          {model.parents.length > 0 ? (
            <div className="flex w-full max-w-lg flex-col gap-4">
              {model.parents.map((node) => (
                <NodeCard key={node.id} node={node} />
              ))}
            </div>
          ) : null}
          {model.parents.length > 0 ? (
            <div className="h-14 w-0.5 bg-gold" />
          ) : null}
          <div className="w-full max-w-lg">
            <NodeCard focus node={model.focus} />
          </div>
          <div className="w-full">
            <FocusEdges count={model.imports.length} />
          </div>
          {model.imports.length > 0 ? (
            <div
              className={
                model.imports.length > 1
                  ? "grid w-full grid-cols-2 gap-4"
                  : "flex w-full justify-center"
              }
            >
              {model.imports.map((node) => (
                <div
                  key={node.id}
                  className={
                    model.imports.length > 1 ? "min-w-0" : "w-full max-w-md"
                  }
                >
                  <NodeCard node={node} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
        <aside className="flex w-96 shrink-0 flex-col gap-8">
          {model.tokens.length > 0 ? (
            <div>
              <h2 className="font-sans text-2xl font-medium text-ink">
                Tokens this file uses
              </h2>
              <div className="mt-4 flex flex-wrap gap-2">
                {model.tokens.map((token) => (
                  <span
                    key={token}
                    className="rounded-md border border-ink-faint/40 bg-surface-card px-3 py-1 font-mono text-2xl text-ink"
                  >
                    {token}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {model.rules.length > 0 ? (
            <div>
              <h2 className="font-sans text-2xl font-medium text-ink">
                Rules that apply
              </h2>
              <ul className="mt-4 flex flex-col gap-3">
                {model.rules.map((rule) => (
                  <li
                    key={rule.id}
                    className="font-sans text-2xl leading-snug text-ink"
                  >
                    {rule.title}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
      </div>
      <Footer scanDate={model.scanDate} />
    </Artboard>
  );
}

export default function ContextCanvasPage({
  params,
  searchParams,
}: {
  params: { view: string };
  searchParams: { node?: string | string[] };
}) {
  if (process.env.NODE_ENV === "production") notFound();

  if (params.view === "violations") {
    return (
      <Shell>
        <ViolationsArtboard model={loadViolations()} />
      </Shell>
    );
  }

  if (params.view === "graph") {
    const requested = Array.isArray(searchParams.node)
      ? searchParams.node[0]
      : searchParams.node;
    const nodeId = requested && requested.length > 0 ? requested : DEFAULT_NODE;
    const model = loadGraph(nodeId);
    if (!model) notFound();
    return (
      <Shell>
        <GraphArtboard model={model} />
      </Shell>
    );
  }

  notFound();
}
