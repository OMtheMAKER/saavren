/* Saavren service worker — makes the app installable on a phone.
   Rules, on purpose:
     * API calls are never cached (a stale medicine list is dangerous).
     * Navigations are network-first, so a new build always wins.
     * Only /assets/* (content-hashed by Vite) are cache-first.
     * NOTHING is cached unless the response was ok. Caching a 404 once meant
       the phone kept serving that 404 forever, which looked exactly like a
       broken deploy.
   Bump CACHE when you ship a breaking build — the old cache is then deleted. */
const CACHE = 'saavren-v2'

self.addEventListener('install', (e) => {
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

const remember = (cache, req, res) => {
  if (!res || !res.ok) return res
  try {
    const copy = res.clone()
    caches.open(cache).then((c) => c.put(req, copy)).catch(() => {})
  } catch (err) { /* cloning failed, serve without caching */ }
  return res
}

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return            // always live

  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => remember(CACHE, './index.html', res))
        .catch(() => caches.match('./index.html').then((r) => r || Response.error()))
    )
    return
  }

  if (url.pathname.includes('/assets/')) {
    e.respondWith(
      caches.match(req).then((hit) => {
        if (hit && hit.ok) return hit          // good copy, use it
        return fetch(req).then((res) => remember(CACHE, req, res))
      })
    )
  }
})
