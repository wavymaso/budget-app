/* Budget on your phone, when the Mac can't be reached.

   - The interface is kept on the phone, so Budget opens instantly, anywhere.
   - Your numbers: each answer from the Mac is saved. When the Mac is asleep or
     out of reach, the last saved answer is shown (marked, so the app can say so).
   - New expenses are kept by the app itself (see "outbox" in app.js) and sent
     when the Mac is back. This file never stores or replays anything you send.

   Served at /sw.js with the version filled in, so a new interface replaces the old. */
const VERSION = "__VERSION__";
const SHELL = `budget-shell-${VERSION}`;
const DATA = "budget-data";
const SHELL_FILES = ["/", "/login", "/static/app.js", "/static/theme.js", "/static/vendor/tailwind-3.4.17.js",
  "/static/vendor/chart-4.4.1.umd.js", "/static/apple-touch-icon.png", "/static/icon-192.png", "/manifest.webmanifest"];
const WAIT_MS = 4000;   // how long to wait for the Mac before showing saved data

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => Promise.all(SHELL_FILES.map((u) =>
    c.add(new Request(u, { credentials: "same-origin" })).catch(() => {})))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("budget-shell-") && k !== SHELL)
    .map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("message", (e) => {
  if (e.data === "forget") e.waitUntil(caches.delete(DATA));   // signing out
});

function fromMac(request) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), WAIT_MS);
    fetch(request).then((res) => {
      clearTimeout(timer);
      // Tailscale answers 502/504 while Budget is closed: that's "not reachable" too.
      if (res.status >= 502 && res.status <= 504) reject(new Error("unreachable"));
      else resolve(res);
    }, (err) => { clearTimeout(timer); reject(err); });
  });
}

function offlineCopy(saved) {
  const headers = new Headers(saved.headers);
  headers.set("X-Budget-Offline", saved.headers.get("X-Budget-Saved-At") || "");
  return saved.blob().then((b) => new Response(b, { status: 200, headers }));
}

async function data(request) {
  const cache = await caches.open(DATA);
  try {
    const res = await fromMac(request);
    if (res.ok) {
      const headers = new Headers(res.headers);
      headers.set("X-Budget-Saved-At", new Date().toISOString());
      const body = await res.clone().blob();
      cache.put(request, new Response(body, { status: 200, headers }));
    }
    return res;
  } catch {
    const saved = await cache.match(request);
    if (saved) return offlineCopy(saved);
    return new Response(JSON.stringify({ detail: "Your Mac can't be reached right now." }),
      { status: 503, headers: { "Content-Type": "application/json", "X-Budget-Offline": "none" } });
  }
}

async function shell(request) {
  const cache = await caches.open(SHELL);
  const saved = await cache.match(request, { ignoreSearch: true });
  const fresh = fromMac(request).then((res) => {
    if (res.ok && res.type === "basic" && !res.redirected) cache.put(request, res.clone());
    return res;
  });
  if (saved) { fresh.catch(() => {}); return saved; }
  return fresh.catch(() => caches.match("/"));
}

async function page(request) {
  try {
    const res = await fromMac(request);
    if (res.ok && !res.redirected) (await caches.open(SHELL)).put("/", res.clone());
    return res;
  } catch {
    return (await caches.match("/", { cacheName: SHELL })) || Response.error();
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname === "/api/export.csv") return;   // always live
  if (url.pathname.startsWith("/api/")) e.respondWith(data(req));
  else if (req.mode === "navigate" && url.pathname === "/") e.respondWith(page(req));
  else if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest" || url.pathname === "/login") e.respondWith(shell(req));
});
