import { DASHBOARD_HTML } from "./dashboard-page.mjs";
import { PUBLIC_SNAPSHOT } from "./dashboard-data.mjs";
// Reuse the existing altay-fare-cron Worker. Secrets stay in Cloudflare.
const dispatchUrl =
  "https://api.github.com/repos/zoyzhongyin/adaptive-travel-planner-skill/actions/workflows/altay-fare-watch.yml/dispatches";

export async function dispatch(env, scheduledTime, io = {}) {
  const call = io.fetch || fetch;
  const pause = io.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const log = io.log || ((record) => console.log(JSON.stringify(record)));
  if (!env.GH_ACTIONS_TOKEN) throw new Error("GH_ACTIONS_TOKEN secret not configured");
  const timestamp = new Date(scheduledTime).toISOString();
  if (scheduledTime >= Date.parse("2026-12-24T00:00:00+08:00")) {
    log({ event: "dispatch_inactive", scheduled_at: timestamp });
    return;
  }
  for (let attempt = 1; attempt <= 3; attempt++) {
    let response;
    try {
      response = await call(dispatchUrl, {
        method: "POST",
        signal: AbortSignal.timeout(10000),
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: "Bearer " + env.GH_ACTIONS_TOKEN,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "AltayFareCron/2.0",
        },
        body: JSON.stringify({
          ref: "main", inputs: { dry_run: "false", trigger_source: "cloudflare" },
        }),
      });
    } catch {
      log({ event: "dispatch_network_error", attempt, scheduled_at: timestamp });
      if (attempt === 3) throw new Error("GitHub dispatch network failure after 3 attempts");
    }
    if (response) {
      const status = response.status;
      await response.body?.cancel();
      log({ event: status === 204 ? "dispatch_accepted" : "dispatch_rejected", status, attempt, scheduled_at: timestamp });
      if (status === 204) return;
      if (!(status === 429 || status >= 500) || attempt === 3) {
        throw new Error("GitHub workflow dispatch HTTP " + status);
      }
    }
    // Ambiguous timeouts may queue twice. Actions shares concurrency and scan
    // cooldown across both schedulers, limiting duplicate fare requests.
    await pause(attempt * 1000);
  }
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatch(env, controller.scheduledTime));
  },
  async fetch(request) {
    // Only read-only, sanitized public data. Never expose the dispatch secret,
    // internal state.json, monitoring logs, or GitHub Actions controls.
    const url = new URL(request.url);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Read-only monitoring page.", { status: 405, headers: { Allow: "GET, HEAD" } });
    }
    const isHead = request.method === "HEAD";
    const common = {
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Cache-Control": "public, max-age=60, s-maxage=60",
    };
    if (url.pathname === "/" || url.pathname === "/index.html") {
      return new Response(isHead ? null : DASHBOARD_HTML, {
        status: 200,
        headers: {
          ...common,
          "Content-Type": "text/html; charset=utf-8",
          "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        },
      });
    }
    if (url.pathname === "/api/fares") {
      return new Response(isHead ? null : JSON.stringify(PUBLIC_SNAPSHOT), {
        status: 200, headers: { ...common, "Content-Type": "application/json; charset=utf-8" },
      });
    }
    return new Response("Not found", { status: 404, headers: common });
  },
};
