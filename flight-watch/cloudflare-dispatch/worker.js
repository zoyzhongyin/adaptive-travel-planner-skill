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
  async fetch() {
    return new Response("Scheduler only. No public HTTP triggers.", { status: 404 });
  },
};
