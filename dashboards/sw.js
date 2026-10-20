/* Scrappy: lets the phone install this page as an app. It stores nothing and never touches the data: every request goes straight to the network. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
