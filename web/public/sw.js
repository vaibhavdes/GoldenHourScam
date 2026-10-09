// Cache only the public application shell. Cloud API responses and evidence are never cached.
const CACHE = "goldenhour-shell-v6";
const PUBLIC_PATHS = ["/", "/index.html", "/icon.svg", "/manifest.webmanifest", "/pcm-recorder.js"];
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(PUBLIC_PATHS);
    const html = await (await cache.match("/index.html")).text();
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)].map(match => match[1]);
    await cache.addAll(assets);
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("goldenhour-shell-") && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (event.request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        // Bypass the HTTP cache so a page never references assets from an older release.
        const response = await fetch(event.request, { cache: "no-store" });
        if (response.ok) await (await caches.open(CACHE)).put("/index.html", response.clone());
        return response;
      } catch {
        return (await caches.match("/index.html")) || Response.error();
      }
    })());
  } else if (PUBLIC_PATHS.includes(url.pathname) || url.pathname.startsWith("/assets/")) {
    event.respondWith((async () => {
      const cached = await caches.match(event.request);
      if (cached) return cached;
      const response = await fetch(event.request);
      if (response.ok) await (await caches.open(CACHE)).put(event.request, response.clone());
      return response;
    })());
  }
});
