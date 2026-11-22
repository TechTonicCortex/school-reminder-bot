// Service Worker for School Reminder PWA
const CACHE_NAME = 'school-reminder-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
];

// Install — cache assets
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — serve from cache, fall back to network
self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

// Push notifications
self.addEventListener('push', e => {
  const data = e.data?.json() || {};
  e.waitUntil(
    self.registration.showNotification(data.title || '🏫 School Reminder', {
      body: data.body || 'You have a new school alert',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      tag: 'school-reminder',
      requireInteraction: true,
      actions: [
        { action: 'view', title: '👀 View' },
        { action: 'done', title: '✅ Mark Done' }
      ]
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'view' || !e.action) {
    e.waitUntil(clients.openWindow('/'));
  }
});
