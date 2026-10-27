/** SOS alert and trip-sharing controls for passengers and drivers. */
(function () {
  "use strict";
  const headers = { "Content-Type": "application/json", "X-Requested-With": "RideEasy" };

  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST", headers, credentials: "same-origin", body: JSON.stringify(body || {}),
    });
    return { ok: response.ok, data: await response.json().catch(() => ({})) };
  }

  function currentPosition() {
    return new Promise((resolve) => {
      if (!("geolocation" in navigator)) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (position) => resolve({ lat: position.coords.latitude, lng: position.coords.longitude }),
        () => resolve(null),
        { enableHighAccuracy: true, timeout: 4000, maximumAge: 10000 }
      );
    });
  }

  const sosButton = document.querySelector("[data-sos-url]");
  const sosResult = document.getElementById("sos-result");
  if (sosButton) {
    sosButton.addEventListener("click", async () => {
      if (!window.confirm("Send an emergency alert to RideEasy and your emergency contacts?\n\nIf you are in immediate danger, call " + (sosButton.dataset.emergencyNumber || "999") + " first.")) return;
      sosButton.disabled = true;
      const place = (await currentPosition()) || {};
      const { ok, data } = await post(sosButton.dataset.sosUrl, place);
      sosButton.disabled = false;
      if (!sosResult) return;
      sosResult.hidden = false;
      sosResult.className = "alert " + (ok ? "alert-warning" : "alert-error");
      if (ok) {
        const contacts = data.contacts_notified
          ? `${data.contacts_notified} emergency contact(s) were texted.`
          : "Add emergency contacts so we can text them next time.";
        sosResult.textContent = `Alert sent to RideEasy safety staff. ${contacts} If you are in danger, call ${data.emergency_number || "999"} now.`;
      } else {
        sosResult.textContent = data.error || "We could not send the alert. Call emergency services now.";
      }
    });
  }

  const shareButton = document.querySelector("[data-share-url]");
  const shareBox = document.getElementById("share-box");
  const shareLink = document.getElementById("share-link");
  const revokeButton = document.getElementById("share-revoke");

  function showLink(url) {
    if (!shareBox || !shareLink) return;
    shareBox.hidden = false;
    shareLink.value = url;
  }

  if (shareButton) {
    shareButton.addEventListener("click", async () => {
      shareButton.disabled = true;
      const { ok, data } = await post(shareButton.dataset.shareUrl);
      shareButton.disabled = false;
      if (!ok) { window.alert(data.error || "Could not create a tracking link."); return; }
      showLink(data.url);
      if (navigator.share) {
        navigator.share({ title: "Follow my RideEasy trip", url: data.url }).catch(() => {});
      }
    });
  }
  const copyButton = document.getElementById("share-copy");
  if (copyButton && shareLink) {
    copyButton.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(shareLink.value); copyButton.textContent = "Copied"; }
      catch (error) { shareLink.select(); }
    });
  }
  if (revokeButton && shareButton) {
    revokeButton.addEventListener("click", async () => {
      const { ok } = await post(revokeButton.dataset.revokeUrl);
      if (ok && shareBox) { shareBox.hidden = true; if (copyButton) copyButton.textContent = "Copy"; }
    });
  }
  if (shareLink && shareLink.value) showLink(shareLink.value);

  // Driver page: live distance/ETA from the GPS reporter.
  const driverEta = document.getElementById("driver-eta");
  if (driverEta) {
    window.addEventListener("rideeasy:driver-progress", (event) => {
      const info = event.detail || {};
      if (!Number.isFinite(info.eta_minutes)) return;
      const where = info.target === "destination" ? "destination" : "pickup";
      driverEta.textContent = `About ${Math.max(1, Math.round(info.eta_minutes))} min (${info.distance_km.toFixed(1)} km) to the ${where}.`;
    });
  }
})();
