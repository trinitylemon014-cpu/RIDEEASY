/**
 * Live trip map (passenger tracker and the public share page).
 * Shows pickup, destination and the driver's moving position with an ETA.
 */
(function () {
  "use strict";
  const mapElement = document.getElementById("trip-map");
  if (!mapElement || !window.L) return;

  const number = (value) => {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const pickup = [number(mapElement.dataset.pickupLat), number(mapElement.dataset.pickupLng)];
  const destination = [number(mapElement.dataset.destinationLat), number(mapElement.dataset.destinationLng)];
  const hasPoint = (point) => point[0] !== null && point[1] !== null;
  const rideId = mapElement.dataset.rideId || "";
  const etaElement = document.getElementById("trip-eta");

  const map = L.map(mapElement, { scrollWheelZoom: false }).setView(hasPoint(pickup) ? pickup : [0.35, 32.58], 13);
  const tileUrl = mapElement.dataset.tileUrl;
  L.tileLayer(tileUrl || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const dot = (color) => ({ radius: 8, color: "#ffffff", weight: 3, fillColor: color, fillOpacity: 1 });
  if (hasPoint(pickup)) L.circleMarker(pickup, dot("#067647")).addTo(map).bindTooltip("Pickup");
  if (hasPoint(destination)) L.circleMarker(destination, dot("#101828")).addTo(map).bindTooltip("Destination");
  if (hasPoint(pickup) && hasPoint(destination)) map.fitBounds([pickup, destination], { padding: [30, 30] });

  const carIcon = (heading) =>
    L.divIcon({
      className: "trip-driver-icon",
      html:
        '<div class="trip-driver-arrow" style="transform: rotate(' + (Number.isFinite(heading) ? heading : 0) + 'deg)">' +
        '<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path d="M12 2 4 21l8-4 8 4z" fill="#1d4ed8" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg></div>',
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  let driverMarker = null;
  let framed = false;

  function describeEta(location, status) {
    if (!etaElement || !location || !Number.isFinite(location.eta_minutes)) return;
    const minutes = Math.max(1, Math.round(location.eta_minutes));
    const distance = Number.isFinite(location.distance_km) ? ` (${location.distance_km.toFixed(1)} km)` : "";
    if (status === "DRIVER_ARRIVED") etaElement.textContent = "Your driver has arrived at the pickup point.";
    else if (location.target === "destination") etaElement.textContent = `Arriving at your destination in about ${minutes} min${distance}.`;
    else etaElement.textContent = `Your driver is about ${minutes} min away${distance}.`;
  }

  function update(location, status) {
    if (!location || !Number.isFinite(location.lat) || !Number.isFinite(location.lng)) return;
    const point = [location.lat, location.lng];
    if (!driverMarker) {
      driverMarker = L.marker(point, { icon: carIcon(location.heading), keyboard: false }).addTo(map);
    } else {
      driverMarker.setLatLng(point);
      driverMarker.setIcon(carIcon(location.heading));
    }
    if (!framed) {
      const bounds = [point];
      [pickup, destination].forEach((p) => hasPoint(p) && bounds.push(p));
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
      framed = true;
    }
    describeEta(location, status);
  }
  window.rideeasyTripMap = { update };

  // Live positions pushed by the server (instant), for the passenger's own ride.
  window.addEventListener("rideeasy:location", (event) => {
    const detail = event.detail || {};
    if (rideId && detail.ride_id !== rideId) return;
    update(detail, detail.status);
  });

  // Public share page: it has no sign-in, so it polls its own read-only endpoint.
  const statusUrl = mapElement.dataset.statusUrl;
  if (statusUrl) {
    const statusText = document.getElementById("trip-status-text");
    const labels = {
      DRIVER_ASSIGNED: "Driver confirmed", DRIVER_ARRIVING: "Driver is on the way",
      DRIVER_ARRIVED: "Driver has arrived", TRIP_STARTED: "Trip in progress",
      TRIP_COMPLETED: "Trip finished", COMPLETED: "Trip finished", CANCELLED: "Trip cancelled",
    };
    let stopped = false;
    async function poll() {
      if (stopped || document.hidden) return schedule();
      try {
        const response = await fetch(statusUrl, { cache: "no-store" });
        if (response.status === 404) {
          if (statusText) statusText.textContent = "This tracking link has expired.";
          stopped = true;
          return;
        }
        const data = await response.json();
        const trip = data.trip;
        if (statusText) statusText.textContent = labels[trip.status] || trip.status;
        if (trip.driver_location) update(trip.driver_location, trip.status);
        if (!trip.active) {
          if (etaElement) etaElement.textContent = "This trip has ended.";
          stopped = true;
          return;
        }
      } catch (error) { /* keep trying */ }
      schedule();
    }
    function schedule() { window.setTimeout(poll, 8000); }
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !stopped) poll(); });
    poll();
  }
})();
