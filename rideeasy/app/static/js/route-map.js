(() => {
  const planner = document.getElementById("route-planner");
  if (!planner) return;

  const mapElement = document.getElementById("route-map");
  const form = document.getElementById("route-form");
  const startInput = document.getElementById("route-start");
  const destinationInput = document.getElementById("route-destination");
  const calculateButton = document.getElementById("calculate-route");
  const buttonLabel = calculateButton.querySelector(".route-button-label");
  const errorElement = document.getElementById("route-error");
  const summaryElement = document.getElementById("route-summary");
  const mapStatus = document.getElementById("map-status");
  const useRouteLink = document.getElementById("use-route");
  const locationiqConfigured = planner.dataset.locationiqConfigured === "true";

  let map;
  let routeLayers;
  if (window.L) {
    map = L.map(mapElement, { scrollWheelZoom: false }).setView([1.2, 32.3], 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    routeLayers = L.featureGroup().addTo(map);
  } else {
    mapStatus.textContent = "The interactive map could not be loaded. Route distance can still be calculated.";
  }
  const markerIcon = (kind, label) => L.divIcon({
    className: `route-map-marker route-map-marker-${kind}`,
    html: `<span>${label}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });

  const formatDuration = (minutes) => {
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours === 0) return `${remainingMinutes} min`;
    return remainingMinutes ? `${hours} hr ${remainingMinutes} min` : `${hours} hr`;
  };

  const showError = (message) => {
    errorElement.textContent = message;
    errorElement.hidden = false;
    summaryElement.hidden = true;
    if (useRouteLink) useRouteLink.hidden = true;
  };

  const makeBookingUrl = (route) => {
    const role = planner.dataset.role;
    const target = role === "school" ? "/school/request" : "/passenger/book-ride";
    const params = new URLSearchParams({
      pickup: route.start.label,
      destination: route.destination.label,
    });
    return `${target}?${params.toString()}`;
  };

  const renderRoute = (route) => {
    if (map) {
      routeLayers.clearLayers();
      const line = L.geoJSON(route.geometry, {
        style: { color: "#111827", weight: 5, opacity: 0.88 },
      }).addTo(routeLayers);

      const startMarker = L.marker([route.start.lat, route.start.lng], {
        icon: markerIcon("start", "A"),
        title: "Start point",
      }).addTo(routeLayers);
      const destinationMarker = L.marker([route.destination.lat, route.destination.lng], {
        icon: markerIcon("end", "B"),
        title: "Destination",
      }).addTo(routeLayers);

      const startPopup = document.createElement("span");
      startPopup.textContent = route.start.label;
      const destinationPopup = document.createElement("span");
      destinationPopup.textContent = route.destination.label;
      startMarker.bindPopup(startPopup);
      destinationMarker.bindPopup(destinationPopup);

      const bounds = line.getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      mapStatus.textContent = "Driving route calculated. Select a marker to view its location.";
    }

    document.getElementById("route-distance").textContent = `${Number(route.distance_km).toFixed(1)} km`;
    document.getElementById("route-duration").textContent = formatDuration(Math.round(route.duration_minutes));
    document.getElementById("route-start-label").textContent = route.start.label;
    document.getElementById("route-destination-label").textContent = route.destination.label;
    summaryElement.hidden = false;
    errorElement.hidden = true;

    if (useRouteLink) {
      useRouteLink.href = makeBookingUrl(route);
      useRouteLink.hidden = false;
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!locationiqConfigured) {
      showError("Route planning is not configured. Ask your administrator to set a LocationIQ API key.");
      return;
    }

    const start = startInput.value.trim();
    const destination = destinationInput.value.trim();
    if (!start || !destination) {
      showError("Enter both a start point and a destination.");
      return;
    }
    if (start.toLocaleLowerCase() === destination.toLocaleLowerCase()) {
      showError("Choose two different locations.");
      return;
    }

    calculateButton.disabled = true;
    buttonLabel.textContent = "Calculating route…";
    errorElement.hidden = true;
    mapStatus.textContent = "Finding locations and calculating the road route…";
    try {
      const response = await fetch("/api/route", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ start, destination }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        showError(data.error || "We could not calculate this route. Review the locations and try again.");
        mapStatus.textContent = "Route unavailable.";
        return;
      }
      renderRoute(data.route);
    } catch {
      showError("We could not reach the route service. Check your connection and try again.");
      mapStatus.textContent = "Route unavailable.";
    } finally {
      calculateButton.disabled = false;
      buttonLabel.textContent = "Calculate road distance";
    }
  });

  if (startInput.value.trim() && destinationInput.value.trim() && locationiqConfigured) {
    form.requestSubmit();
  }
})();
