// Service worker de la PWA de captura. Estrategia cache-first sobre el "app
// shell" (HTML/CSS/JS/vendor/íconos) para que capturar y exportar funcionen sin
// conexión — no hay ninguna llamada de red en la lógica de la app (todo es
// IndexedDB + canvas + ZIP en el cliente), así que cachear el shell alcanza.
//
// Subí CACHE_VERSION cada vez que cambies algún archivo del shell — el evento
// "activate" borra las caches con nombre distinto, así los clientes viejos
// levantan la versión nueva en la siguiente carga.
const CACHE_VERSION = "v1";
const CACHE_NAME = `parserboletas-pwa-${CACHE_VERSION}`;

// Rutas relativas al scope del service worker (funciona igual si la PWA queda
// publicada en la raíz del dominio o en una subcarpeta, ej. GitHub Pages
// "/ParserBoletas/pwa/").
const APP_SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./css/app.css",
  "./js/app.js",
  "./js/db.js",
  "./js/capture.js",
  "./js/export-zip.js",
  "./vendor/alpine.min.js",
  "./vendor/jszip.min.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      // No estaba en el shell precacheado (ej. un asset nuevo): lo trae de red
      // y lo guarda para la próxima vez que esté offline.
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
