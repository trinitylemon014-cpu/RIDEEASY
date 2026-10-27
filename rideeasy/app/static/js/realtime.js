/**
 * RideEasy live layer (loaded on every page for signed-in users):
 *  1. Server-sent events: instant "check now" hints and live driver positions.
 *  2. Driver GPS reporting while online or on a trip.
 *  3. Optional phone notifications (Web Push).
 * Everything degrades gracefully: without these features the pages still poll.
 */
(function () {
  "use strict";
  const config = document.getElementById("rt-config");
  if (!config) return;
  const role = config.dataset.role;
  const jsonHeaders = { "Content-Type": "application/json", "X-Requested-With": "RideEasy" };
  const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }));

  /* ------------------------------------------------------------ 1. live stream */
  let source = null;
  let failures = 0;
  let reconnectTimer = null;
  window.__rideeasyStreamLive = false;

  function closeStream() {
    window.clearTimeout(reconnectTimer);
    if (source) source.close();
    source = null;
    window.__rideeasyStreamLive = false;
  }

  function connectStream() {
    if (!("EventSource" in window) || document.hidden || !config.dataset.streamUrl) return;
    closeStream();
    source = new EventSource(config.dataset.streamUrl);
    source.addEventListener("ready", () => {
      failures = 0;
      window.__rideeasyStreamLive = true;
    });
    ["ride", "location"].forEach((name) => {
      source.addEventListener(name, (event) => {
        try {
          emit("rideeasy:" + name, JSON.parse(event.data));
        } catch (error) { /* ignore malformed event */ }
      });
    });
    source.addEventListener("reconnect", () => {
      closeStream();
      reconnectTimer = window.setTimeout(connectStream, 300);
    });
    source.onerror = () => {
      closeStream();
      failures += 1;
      reconnectTimer = window.setTimeout(connectStream, Math.min(60000, 3000 * 2 ** Math.min(failures, 5)));
    };
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) closeStream();      // frees the server thread while the tab is hidden
    else connectStream();
  });
  connectStream();

  /* ------------------------------------------------------ 2. driver GPS reporter */
  const chip = document.getElementById("driver-location-status");
  function setChip(text, state) {
    if (!chip) return;
    chip.hidden = false;
    chip.textContent = text;
    chip.dataset.state = state;
  }

  function startDriverReporter() {
    const url = config.dataset.locationUrl;
    const onTrip = Number(config.dataset.activeTrips || 0) > 0;
    const online = config.dataset.driverOnline === "1";
    if (!url || !(online || onTrip)) return;
    if (!("geolocation" in navigator)) {
      setChip("This browser cannot share location, so you cannot receive trips.", "error");
      return;
    }
    const intervalMs = onTrip ? 5000 : 15000;
    let lastFix = null;
    let lastSent = 0;
    let pausedUntil = 0;
    let sending = false;

    async function send(position) {
      if (sending || document.hidden || Date.now() < pausedUntil) return;
      sending = true;
      lastSent = Date.now();
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: jsonHeaders,
          credentials: "same-origin",
          body: JSON.stringify({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            heading: Number.isFinite(position.coords.heading) ? position.coords.heading : null,
            accuracy: position.coords.accuracy,
          }),
        });
        if (response.status === 429) pausedUntil = Date.now() + 30000;
        if (response.ok) {
          setChip("Location sharing is on", "ok");
          emit("rideeasy:driver-progress", await response.json().catch(() => ({})));
        }
      } catch (error) {
        pausedUntil = Date.now() + 10000;
      } finally {
        sending = false;
      }
    }

    navigator.geolocation.watchPosition(
      (position) => {
        lastFix = position;
        if (Date.now() - lastSent >= intervalMs) send(position);
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          setChip("Location is off. Allow location in your browser, or you will not receive trips.", "error");
        } else {
          setChip("Waiting for a GPS signal…", "warn");
        }
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 }
    );
    // A parked driver produces no new fixes, so re-send the last one to stay "fresh" for dispatch.
    window.setInterval(() => {
      if (lastFix && Date.now() - lastSent >= intervalMs) send(lastFix);
    }, 1000);

    // Keep the screen on during a trip: browsers pause GPS when the page is hidden.
    if (onTrip && "wakeLock" in navigator) {
      const hold = () => navigator.wakeLock.request("screen").catch(() => {});
      hold();
      document.addEventListener("visibilitychange", () => { if (!document.hidden) hold(); });
    }
    setChip("Starting location sharing…", "warn");
  }
  if (role === "DRIVER") startDriverReporter();

  /* ---------------------------------------------------------- 3. phone notifications */
  const pushKey = config.dataset.pushKey;
  const banner = document.getElementById("push-banner");

  function keyToBytes(base64Url) {
    const padded = (base64Url + "=".repeat((4 - (base64Url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(padded);
    return Uint8Array.from(raw, (char) => char.charCodeAt(0));
  }

  async function subscribe(registration) {
    const subscription =
      (await registration.pushManager.getSubscription()) ||
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyToBytes(pushKey),
      }));
    await fetch(config.dataset.pushSubscribeUrl, {
      method: "POST",
      headers: jsonHeaders,
      credentials: "same-origin",
      body: JSON.stringify(subscription.toJSON()),
    });
  }

  async function setupPush() {
    if (!pushKey || !("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return;
    try {
      const registration = await navigator.serviceWorker.register("/sw.js");
      if (Notification.permission === "granted") {
        if (!sessionStorage.getItem("rideeasy-push-synced")) {
          await subscribe(registration);
          sessionStorage.setItem("rideeasy-push-synced", "1");
        }
      } else if (Notification.permission === "default" && banner && !localStorage.getItem("rideeasy-push-dismissed")) {
        banner.hidden = false;
        banner.querySelector("[data-push-enable]").addEventListener("click", async () => {
          banner.hidden = true;
          if ((await Notification.requestPermission()) === "granted") await subscribe(registration);
        });
        banner.querySelector("[data-push-dismiss]").addEventListener("click", () => {
          banner.hidden = true;
          try { localStorage.setItem("rideeasy-push-dismissed", "1"); } catch (error) { /* private mode */ }
        });
      }
    } catch (error) {
      console.warn("Phone notifications are unavailable.", error);
    }
  }
  setupPush();
})();
