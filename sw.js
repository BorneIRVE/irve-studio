// Service Worker VoltExpert CRM
const CACHE = 'voltexpert-v27';
const ASSETS = ['./index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;
  // Ne jamais mettre en cache les appels API (toujours frais)
  if (url.includes('/api/') || url.includes('vercel') || e.request.method !== 'GET') {
    return; // laisse passer vers le réseau
  }
  // Network-first pour le HTML, cache fallback hors-ligne
  e.respondWith(
    fetch(e.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy).catch(() => {}));
      return resp;
    }).catch(() => caches.match(e.request))
  );
});
