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

  const DEFAULT_STATUS = "Map centered on Uganda. Calculate a route to see directions.";

  let map;
  let routeLayers;
  if (window.L) {
    map = L.map(mapElement, { scrollWheelZoom: false }).setView([1.2, 32.3], 7);

    // Tiles are served by RideEasy's own /map/tiles proxy (LocationIQ, key kept
    // server-side). Public OpenStreetMap tile servers block apps that don't follow
    // their tile usage policy (HTTP 403 "Access blocked"), so they are only used
    // as a low-volume fallback when LocationIQ is not configured.
    const tileLayer = locationiqConfigured
      ? L.tileLayer("/map/tiles/{z}/{x}/{y}.png", {
          maxZoom: 18,
          attribution:
            '&copy; <a href="https://locationiq.com/">LocationIQ</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        })
      : L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          referrerPolicy: "strict-origin-when-cross-origin",
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        });

    let tileErrorShown = false;
    tileLayer.on("tileerror", () => {
      if (tileErrorShown) return;
      tileErrorShown = true;
      mapStatus.textContent =
        "Map tiles could not be loaded right now. Route distance can still be calculated.";
    });
    tileLayer.on("tileload", () => {
      if (tileErrorShown) {
        tileErrorShown = false;
        mapStatus.textContent = DEFAULT_STATUS;
      }
    });
    tileLayer.addTo(map);

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

  // ---------------------------------------------------------------------------
  // Place suggestions (type-ahead). Suggestions come from RideEasy's own
  // /api/places/autocomplete endpoint, so the LocationIQ key never reaches the browser.
  // ---------------------------------------------------------------------------
  const selectedPlaces = { start: null, destination: null };
  const suggestionCache = new Map();
  const MIN_CHARS = 3;
  const DEBOUNCE_MS = 300;

  const setupAutocomplete = (input, kind) => {
    if (!locationiqConfigured) return;

    const group = input.closest(".route-input-wrap") || input.closest(".form-group");
    const listId = `route-${kind}-suggestions`;
    const list = document.createElement("ul");
    list.className = "route-suggestions";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", kind === "start" ? "Start point suggestions" : "Destination suggestions");
    list.hidden = true;
    group.appendChild(list);

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", listId);
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("autocomplete", "off");

    let items = [];
    let activeIndex = -1;
    let timer = null;
    let controller = null;
    let requestId = 0;

    const close = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    };

    const setActive = (index) => {
      const options = list.querySelectorAll("[role='option']");
      options.forEach((option, i) => {
        const isActive = i === index;
        option.classList.toggle("is-active", isActive);
        option.setAttribute("aria-selected", isActive ? "true" : "false");
        if (isActive) {
          input.setAttribute("aria-activedescendant", option.id);
          option.scrollIntoView({ block: "nearest" });
        }
      });
      activeIndex = index;
      if (index < 0) input.removeAttribute("aria-activedescendant");
    };

    const choose = (place) => {
      input.value = place.label;
      selectedPlaces[kind] = { lat: place.lat, lng: place.lng, label: place.label };
      close();
    };

    const render = (places) => {
      items = places;
      list.replaceChildren();
      if (!places.length) {
        close();
        return;
      }
      places.forEach((place, index) => {
        const option = document.createElement("li");
        option.id = `${listId}-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.className = "route-suggestion";

        const title = document.createElement("span");
        title.className = "route-suggestion-title";
        title.textContent = place.title || place.label;
        option.appendChild(title);

        if (place.subtitle) {
          const subtitle = document.createElement("span");
          subtitle.className = "route-suggestion-subtitle";
          subtitle.textContent = place.subtitle;
          option.appendChild(subtitle);
        }

        // mousedown (not click) so the input keeps focus and does not blur first.
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          choose(place);
        });
        option.addEventListener("mousemove", () => {
          if (activeIndex !== index) setActive(index);
        });
        list.appendChild(option);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      setActive(-1);
    };

    const fetchSuggestions = async (query) => {
      const cacheKey = query.toLocaleLowerCase();
      if (suggestionCache.has(cacheKey)) {
        render(suggestionCache.get(cacheKey));
        return;
      }
      if (controller) controller.abort();
      controller = new AbortController();
      const currentRequest = ++requestId;
      try {
        const response = await fetch(`/api/places/autocomplete?q=${encodeURIComponent(query)}`, {
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!response.ok) {
          close();
          return;
        }
        const data = await response.json();
        if (currentRequest !== requestId) return; // a newer search replaced this one
        const places = Array.isArray(data.suggestions) ? data.suggestions : [];
        suggestionCache.set(cacheKey, places);
        if (input.value.trim().toLocaleLowerCase() === cacheKey) render(places);
      } catch {
        // Aborted or offline: suggestions are optional, typing still works.
        if (currentRequest === requestId) close();
      }
    };

    input.addEventListener("input", () => {
      selectedPlaces[kind] = null; // typed text no longer matches a picked place
      if (kind === "start" && locateStatus) locateStatus.hidden = true;
      window.clearTimeout(timer);
      const query = input.value.trim();
      if (query.length < MIN_CHARS) {
        if (controller) controller.abort();
        requestId += 1;
        close();
        return;
      }
      timer = window.setTimeout(() => fetchSuggestions(query), DEBOUNCE_MS);
    });

    input.addEventListener("keydown", (event) => {
      if (list.hidden || !items.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((activeIndex + 1) % items.length);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive(activeIndex <= 0 ? items.length - 1 : activeIndex - 1);
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        choose(items[activeIndex]);
      } else if (event.key === "Escape") {
        close();
      }
    });

    input.addEventListener("route:close", close);
    input.addEventListener("blur", close);
    input.addEventListener("focus", () => {
      const cached = suggestionCache.get(input.value.trim().toLocaleLowerCase());
      if (cached && cached.length && !selectedPlaces[kind]) render(cached);
    });
  };

  setupAutocomplete(startInput, "start");
  setupAutocomplete(destinationInput, "destination");

  // ---------------------------------------------------------------------------
  // "Use my current location": read the device position, name it on the server,
  // and use it as the start point (exact coordinates, no geocoding needed).
  // ---------------------------------------------------------------------------
  const locateButton = document.getElementById("use-my-location");
  const locateStatus = document.getElementById("route-locate-status");

  const setLocateStatus = (message, isError = false) => {
    if (!locateStatus) return;
    locateStatus.textContent = message;
    locateStatus.hidden = !message;
    locateStatus.classList.toggle("is-error", isError);
  };

  const getDevicePosition = () => new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 60000,
    });
  });

  const geolocationMessage = (error) => {
    if (error && error.code === 1) {
      return "Location access is blocked. Allow location for this site in your browser settings, or type your start point.";
    }
    if (error && error.code === 3) {
      return "Finding your location took too long. Try again, or type your start point.";
    }
    return "We could not find your location. Type your start point instead.";
  };

  if (locateButton) {
    if (!("geolocation" in navigator)) {
      locateButton.hidden = true;
    } else {
      const locateLabel = locateButton.querySelector(".route-locate-label");
      locateButton.addEventListener("click", async () => {
        if (window.isSecureContext === false) {
          setLocateStatus("Your browser only shares location on secure (HTTPS) pages.", true);
          return;
        }
        locateButton.disabled = true;
        locateLabel.textContent = "Finding your location…";
        setLocateStatus("");
        try {
          const position = await getDevicePosition();
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;
          const accuracy = Math.round(position.coords.accuracy || 0);

          let label = `Current location (${lat.toFixed(5)}, ${lng.toFixed(5)})`;
          try {
            const response = await fetch(`/api/places/reverse?lat=${lat}&lng=${lng}`, {
              headers: { Accept: "application/json" },
            });
            const data = response.ok ? await response.json() : null;
            if (data && data.success && data.place && data.place.label) label = data.place.label;
          } catch {
            // Keep the coordinate label; the route can still be calculated from the position.
          }

          startInput.value = label;
          selectedPlaces.start = { lat, lng, label };
          startInput.dispatchEvent(new Event("route:close"));
          errorElement.hidden = true;
          if (map) map.setView([lat, lng], 14);
          setLocateStatus(
            accuracy > 1000
              ? `Using your approximate location (within about ${Math.round(accuracy / 1000)} km).`
              : "Using your current location as the start point."
          );
          if (!destinationInput.value.trim()) destinationInput.focus();
        } catch (error) {
          setLocateStatus(geolocationMessage(error), true);
        } finally {
          locateButton.disabled = false;
          locateLabel.textContent = "Use my current location";
        }
      });
    }
  }

  const pickedPoint = (kind, input) => {
    const picked = selectedPlaces[kind];
    return picked && picked.label === input.value.trim() ? picked : null;
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
        body: JSON.stringify({
          start,
          destination,
          start_point: pickedPoint("start", startInput),
          destination_point: pickedPoint("destination", destinationInput),
        }),
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
