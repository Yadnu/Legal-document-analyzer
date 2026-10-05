import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const FRONTEND_ROOT = path.resolve(__dirname, "../..");
const OUT_DIR = path.join(FRONTEND_ROOT, "context", "export");
const PORT = Number(process.env.CONTEXT_CANVAS_PORT ?? 3000);
const BASE = (
  process.env.CONTEXT_CANVAS_URL ?? `http://127.0.0.1:${PORT}`
).replace(/\/$/, "");

const VIEWS = ["violations", "graph"] as const;

function stop(child: ChildProcess): void {
  if (!child.pid) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { shell: true });
    return;
  }
  child.kill("SIGTERM");
}

async function reachable(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { redirect: "manual" });
    return response.ok;
  } catch {
    return false;
  }
}

function startDevServer(): ChildProcess {
  return spawn("pnpm", ["exec", "next", "dev", "--port", String(PORT)], {
    cwd: FRONTEND_ROOT,
    env: process.env,
    shell: true,
    stdio: "inherit",
  });
}

async function waitForServer(url: string): Promise<void> {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (await reachable(url)) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Dev server did not answer ${url}`);
}

async function main(): Promise<void> {
  const probe = `${BASE}/dev/context-canvas/violations`;
  let child: ChildProcess | undefined;
  let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
  try {
    if (!(await reachable(probe))) {
      child = startDevServer();
      await waitForServer(probe);
    }

    fs.mkdirSync(OUT_DIR, { recursive: true });
    browser = await chromium.launch();
    const page = await browser.newPage({
      deviceScaleFactor: 1,
      viewport: { width: 1080, height: 1350 },
    });

    for (const view of VIEWS) {
      const url = `${BASE}/dev/context-canvas/${view}`;
      await page.goto(url, { waitUntil: "load" });
      const artboard = page.locator("[data-artboard]");
      await artboard.waitFor({ state: "visible", timeout: 60_000 });
      await page.evaluate(async () => {
        await document.fonts.load("48px Fraunces");
        await document.fonts.load("24px Outfit");
        await document.fonts.load("24px 'JetBrains Mono'");
        await document.fonts.ready;
      });
      const overflow = await artboard.evaluate(
        (element) => element.scrollHeight - element.clientHeight
      );
      if (overflow > 1) {
        throw new Error(`${view} artboard overflows by ${overflow}px`);
      }
      const box = await artboard.boundingBox();
      if (
        !box ||
        Math.abs(box.width - 1080) > 1 ||
        Math.abs(box.height - 1350) > 1
      ) {
        throw new Error(
          `${view} artboard is ${box?.width ?? 0}x${box?.height ?? 0}, expected 1080x1350`
        );
      }
      const file = path.join(OUT_DIR, `${view}.png`);
      await artboard.screenshot({ path: file, type: "png" });
      console.log(`Wrote ${path.relative(FRONTEND_ROOT, file)}`);
    }
  } finally {
    if (browser) await browser.close();
    if (child) stop(child);
  }
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exitCode = 1;
});
