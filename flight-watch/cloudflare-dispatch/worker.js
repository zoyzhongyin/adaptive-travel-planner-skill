// External scheduling fallback for the Altay flight watcher.
// Deploy to Cloudflare Workers with a Cron Trigger. GH_ACTIONS_TOKEN must
// be stored as a Worker secret (never hard-coded or committed).
// GitHub workflow handles all fare data and WeChat notifications.
const dispatchUrl =
  "https://api.github.com/repos/zoyzhongyin/adaptive-travel-planner-skill/actions/workflows/altay-fare-watch.yml/dispatches";

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      if (!env.GH_ACTIONS_TOKEN) {
        throw new Error("GH_ACTIONS_TOKEN secret not configured");
      }
      const response = await fetch(dispatchUrl, {
        method: "POST",
        headers: {
          "Accept": "application/vnd.github+json",
          "Authorization": "Bearer " + env.GH_ACTIONS_TOKEN,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "AltayFareCron/1.0",
        },
        body: JSON.stringify({ ref: "main", inputs: { dry_run: "false" } }),
      });
      if (response.status !== 204) {
        // Never log response bodies or the request (its headers contain the token).
        throw new Error("GitHub workflow dispatch HTTP " + response.status);
      }
    })());
  },
  async fetch() {
    // Do not expose an unauthenticated manual invocation endpoint.
    return new Response("Scheduler only. No public HTTP triggers.", { status: 404 });
  },
};
