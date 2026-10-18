// The offline shell for the AutoEdit web app. It keeps only the app's own files:
// - /app/assets/* (names change with every build): cache first, kept;
// - pages under /app/: network first, the cached app when offline.
// Nothing from /v1 (the API) or /files (videos) is ever cached here: private and always fresh.
const CACHE = "autoedit-shell-v1";
const SHELL = ["/app/", "/app/manifest.webmanifest", "/app/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith("/app/")) return;
  if (url.pathname.startsWith("/app/assets/")) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    })));
    return;
  }
  // a page of the app: the newest from the network, the saved one when offline
  event.respondWith(fetch(req).then((res) => {
    if (res.ok && (req.mode === "navigate" || url.pathname === "/app/")) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put("/app/", copy));
    }
    return res;
  }).catch(() => caches.match(req).then((hit) => hit || caches.match("/app/"))));
});
