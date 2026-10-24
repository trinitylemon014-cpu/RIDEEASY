/**
 * RideEasy - Vanilla JavaScript Application Layer
 * Strict: No React, No Vue, Clean Native DOM APIs
 * MOVE. TRAVEL. ARRIVE.
 */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Mobile Navigation Drawer Toggle
  const mobileBtn = document.getElementById("mobile-menu-toggle");
  const mobileDrawer = document.getElementById("mobile-nav-drawer");

  if (mobileBtn && mobileDrawer) {
    mobileBtn.addEventListener("click", () => {
      mobileDrawer.classList.toggle("open");
    });
  }

  // 2. Auto-dismiss alerts after 6 seconds
  const alerts = document.querySelectorAll(".alert");
  alerts.forEach((alert) => {
    setTimeout(() => {
      alert.style.opacity = "0";
      alert.style.transition = "opacity 0.4s ease";
      setTimeout(() => alert.remove(), 400);
    }, 6000);
  });

  // 2a. Explain how to save a browser shortcut on the current device.
  const shortcutButtons = document.querySelectorAll("[data-add-shortcut]");
  const shortcutDialog = document.getElementById("shortcut-help");
  const shortcutInstructions = document.getElementById("shortcut-instructions");
  const shortcutHelpClose = document.getElementById("shortcut-help-close");

  function showShortcutInstructions() {
    if (!shortcutDialog || !shortcutInstructions) return;
    const userAgent = window.navigator.userAgent || "";
    if (/iPad|iPhone|iPod/i.test(userAgent)) {
      shortcutInstructions.textContent = "In Safari, tap Share, then choose “Add to Home Screen” to save a RideEasy link.";
    } else if (/Android/i.test(userAgent)) {
      shortcutInstructions.textContent = "In your browser menu, choose “Add to Home screen” or “Create shortcut” to save a RideEasy link.";
    } else {
      shortcutInstructions.textContent = "In Chrome or Edge, open the browser menu and choose Save and share, then Create shortcut. In other browsers, bookmark this page; on a laptop you can drag the bookmark to your desktop.";
    }
    if (typeof shortcutDialog.showModal === "function") {
      shortcutDialog.showModal();
    } else {
      window.alert(shortcutInstructions.textContent);
    }
  }

  shortcutButtons.forEach((button) => {
    button.addEventListener("click", showShortcutInstructions);
  });

  if (shortcutHelpClose && shortcutDialog) {
    shortcutHelpClose.addEventListener("click", () => shortcutDialog.close());
    shortcutDialog.addEventListener("click", (event) => {
      if (event.target === shortcutDialog) shortcutDialog.close();
    });
  }

  const driverOfferWatcher = document.getElementById("driver-offer-watcher");
  if (driverOfferWatcher) {
    const seenOfferIds = new Set(
      Array.from(document.querySelectorAll("[data-driver-offer-id]"))
        .map((row) => row.dataset.driverOfferId)
    );

    function showDriverOffer(offer) {
      const toast = document.createElement("div");
      toast.className = "alert alert-info";
      toast.setAttribute("role", "alert");
      toast.style.cssText = "position:fixed;right:1rem;top:1rem;z-index:1100;max-width:min(24rem,calc(100vw - 2rem));box-shadow:var(--shadow-lg);";
      const message = document.createElement("span");
      message.textContent = `New trip offer: ${offer.pickup_address} to ${offer.destination_address}.`;
      const link = document.createElement("a");
      link.href = "/driver/requests";
      link.className = "btn btn-primary btn-sm";
      link.textContent = "Review";
      link.style.marginLeft = "0.75rem";
      toast.append(message, link);
      document.body.appendChild(toast);
      window.setTimeout(() => toast.remove(), 12000);

      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("RideEasy trip offer", {
          body: `${offer.pickup_address} to ${offer.destination_address}`,
          icon: "/static/icons/rideeasy-icon.svg"
        });
      }
    }

    async function checkDriverOffers() {
      if (document.hidden) return;
      try {
        const response = await fetch(driverOfferWatcher.dataset.offersUrl, {
          headers: { "Accept": "application/json" },
          cache: "no-store"
        });
        if (!response.ok) return;
        const result = await response.json();
        if (!result.success || !Array.isArray(result.offers)) return;

        const currentOfferIds = new Set(result.offers.map((offer) => offer.id));
        const unseenOffer = result.offers.find((offer) => !seenOfferIds.has(offer.id));
        if (unseenOffer && ["/driver/dashboard", "/driver/requests"].includes(window.location.pathname)) {
          const offerIsRendered = Array.from(document.querySelectorAll("[data-driver-offer-id]"))
            .some((row) => row.dataset.driverOfferId === unseenOffer.id);
          if (!offerIsRendered) {
            window.location.reload();
            return;
          }
        }
        const removedOffer = Array.from(document.querySelectorAll("[data-driver-offer-id]"))
          .some((row) => !currentOfferIds.has(row.dataset.driverOfferId));
        if (removedOffer) {
          window.location.reload();
          return;
        }

        result.offers.forEach((offer) => {
          if (seenOfferIds.has(offer.id)) return;
          seenOfferIds.add(offer.id);
          showDriverOffer(offer);
        });
      } catch (error) {
        console.warn("Unable to check RideEasy trip offers.", error);
      }
    }

    checkDriverOffers();
    window.setInterval(checkDriverOffers, 8000);
  }

  const rideBookingForm = document.getElementById("ride-booking-form");
  if (rideBookingForm) {
    let bookingSubmitting = false;
    rideBookingForm.addEventListener("submit", (event) => {
      if (bookingSubmitting) {
        event.preventDefault();
        return;
      }
      bookingSubmitting = true;
      const submitButton = event.submitter;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "Submitting ride request…";
        submitButton.setAttribute("aria-busy", "true");
      }
    });
  }

  // 3. LocationIQ-backed fare estimate and location suggestions
  const fareDisplay = document.getElementById("estimated-fare-display");
  const distDisplay = document.getElementById("estimated-distance-display");
  const pickupInput = document.getElementById("pickup_address");
  const destInput = document.getElementById("destination_address");
  let estimateRequestId = 0;

  function showFareUnavailable(message) {
    if (fareDisplay) fareDisplay.textContent = "UGX --";
    if (distDisplay) distDisplay.textContent = message;
  }

  function setupFareAutocomplete(input, kind) {
    if (!input) return;
    const group = input.closest(".form-group");
    if (!group) return;

    const list = document.createElement("ul");
    list.className = "fare-place-suggestions";
    list.id = `${kind}-place-suggestions`;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    group.appendChild(list);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", list.id);
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("autocomplete", "off");

    let timer;
    let controller;
    let requestId = 0;
    let options = [];
    let activeIndex = -1;
    const close = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    };
    const select = (place) => {
      input.value = place.label;
      close();
      window.calculateAndDisplayEstimatedFare();
    };
    const render = (places) => {
      options = places;
      list.replaceChildren();
      places.forEach((place, index) => {
        const option = document.createElement("li");
        option.id = `${list.id}-${index}`;
        option.className = "fare-place-suggestion";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        const title = document.createElement("span");
        title.textContent = place.title || place.label;
        option.appendChild(title);
        if (place.subtitle) {
          const subtitle = document.createElement("small");
          subtitle.textContent = place.subtitle;
          option.appendChild(subtitle);
        }
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          select(place);
        });
        option.addEventListener("mousemove", () => {
          activeIndex = index;
          list.querySelectorAll("[role='option']").forEach((item, itemIndex) => {
            item.setAttribute("aria-selected", itemIndex === index ? "true" : "false");
          });
        });
        list.appendChild(option);
      });
      list.hidden = !places.length;
      input.setAttribute("aria-expanded", places.length ? "true" : "false");
    };
    const search = async (query) => {
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
        const result = await response.json();
        if (currentRequest === requestId) render(Array.isArray(result.suggestions) ? result.suggestions : []);
      } catch (error) {
        if (error.name !== "AbortError" && currentRequest === requestId) close();
      }
    };

    input.addEventListener("input", () => {
      estimateRequestId += 1;
      window.clearTimeout(timer);
      const query = input.value.trim();
      showFareUnavailable("Select a matching place or finish entering the address.");
      if (query.length < 3) {
        if (controller) controller.abort();
        requestId += 1;
        close();
        showFareUnavailable("Choose pickup and destination locations.");
        return;
      }
      timer = window.setTimeout(() => search(query), 300);
    });
    input.addEventListener("keydown", (event) => {
      if (list.hidden || !options.length) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        activeIndex = event.key === "ArrowDown"
          ? (activeIndex + 1) % options.length
          : (activeIndex <= 0 ? options.length - 1 : activeIndex - 1);
        list.querySelectorAll("[role='option']").forEach((item, index) => {
          const selected = index === activeIndex;
          item.setAttribute("aria-selected", selected ? "true" : "false");
          if (selected) {
            input.setAttribute("aria-activedescendant", item.id);
            item.scrollIntoView({ block: "nearest" });
          }
        });
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        select(options[activeIndex]);
      } else if (event.key === "Escape") {
        close();
      }
    });
    input.addEventListener("blur", () => {
      window.setTimeout(close, 100);
      if (input.value.trim()) window.calculateAndDisplayEstimatedFare();
    });
  }

  window.calculateAndDisplayEstimatedFare = function (pickupOverride, destOverride, categoryOverride) {
    const pickup = (pickupOverride !== undefined ? pickupOverride : (pickupInput ? pickupInput.value : "")).trim();
    const destination = (destOverride !== undefined ? destOverride : (destInput ? destInput.value : "")).trim();

    let category = categoryOverride;
    if (!category) {
      const checkedCat = document.querySelector("input[name='category']:checked");
      category = checkedCat ? checkedCat.value.toUpperCase() : "ECONOMY";
    } else {
      category = category.toUpperCase();
    }

    // Synchronize UI active state for vehicle category cards
    document.querySelectorAll(".category-selector-grid label").forEach((label) => {
      const radio = label.querySelector("input[name='category']");
      const card = label.querySelector(".category-card");
      if (radio && card) {
        if (radio.value.toUpperCase() === category) {
          card.classList.add("selected");
          radio.checked = true;
        } else {
          card.classList.remove("selected");
        }
      }
    });

    if (!pickup || !destination) {
      showFareUnavailable("Choose pickup and destination locations.");
      return Promise.resolve(null);
    }
    if (fareDisplay) fareDisplay.textContent = "Calculating…";
    if (distDisplay) distDisplay.textContent = "Calculating driving distance…";
    const currentRequest = ++estimateRequestId;

    return fetch("/api/estimate-fare", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ pickup, destination, category })
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.error || "A road-distance fare estimate is unavailable.");
        }
        if (currentRequest !== estimateRequestId) return null;
        if (fareDisplay) fareDisplay.textContent = `UGX ${Number(data.estimated_fare_ugx).toLocaleString()}`;
        if (distDisplay) {
          distDisplay.textContent = `${Number(data.distance_km).toFixed(1)} km driving · ${data.duration_minutes} min`;
        }
        return data;
      })
      .catch((error) => {
        if (currentRequest === estimateRequestId) {
          const message = error.name === "TypeError" || error.name === "SyntaxError"
            ? "Could not reach the route service. Check your connection and try again."
            : error.message;
          showFareUnavailable(message);
        }
        return null;
      });
  };

  // Backward compatibility alias
  window.triggerFareCalculation = window.calculateAndDisplayEstimatedFare;

  setupFareAutocomplete(pickupInput, "pickup");
  setupFareAutocomplete(destInput, "destination");
  setupFareAutocomplete(document.getElementById("pickup_location"), "school-pickup");
  setupFareAutocomplete(document.getElementById("destination"), "school-destination");

  const categoryRadios = document.querySelectorAll("input[name='category']");
  categoryRadios.forEach((r) => {
    r.addEventListener("change", () => window.calculateAndDisplayEstimatedFare(undefined, undefined, r.value));
  });

  // 6. Compute initial fare estimate if the display element is on page
  if (document.getElementById("estimated-fare-display")) {
    window.calculateAndDisplayEstimatedFare();
  }

  // 6b. Saved Frequent Routes Quick Access & Save Route Feature
  function applySavedRoute(pickup, destination, category, name) {
    if (pickupInput && pickup) pickupInput.value = pickup;
    if (destInput && destination) destInput.value = destination;

    if (category) {
      const targetRadio = document.querySelector(`input[name='category'][value='${category.toUpperCase()}']`);
      if (targetRadio) {
        targetRadio.checked = true;
      }
    }

    window.calculateAndDisplayEstimatedFare(pickup, destination, category);

    // Feedback notification toast
    const feedbackToast = document.createElement("div");
    feedbackToast.className = "alert alert-success";
    feedbackToast.style.position = "fixed";
    feedbackToast.style.bottom = "1.5rem";
    feedbackToast.style.right = "1.5rem";
    feedbackToast.style.zIndex = "9999";
    feedbackToast.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
    feedbackToast.textContent = `Applied frequent route: ${name || "Saved Route"}`;
    document.body.appendChild(feedbackToast);
    setTimeout(() => {
      feedbackToast.style.opacity = "0";
      feedbackToast.style.transition = "opacity 0.4s ease";
      setTimeout(() => feedbackToast.remove(), 400);
    }, 2500);
  }

  document.querySelectorAll(".btn-apply-route").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pickup = btn.getAttribute("data-pickup");
      const dest = btn.getAttribute("data-destination");
      const cat = btn.getAttribute("data-category");
      const name = btn.getAttribute("data-name");
      applySavedRoute(pickup, dest, cat, name);
    });
  });

  const toggleSaveRouteBtn = document.getElementById("toggle-save-route-row-btn");
  const saveRouteGroup = document.getElementById("save-route-input-group");
  const saveRouteNameInput = document.getElementById("save_route_name");
  const btnSaveCurrentRoute = document.getElementById("btn-save-current-route");
  const saveRouteStatus = document.getElementById("save-route-status");

  if (toggleSaveRouteBtn && saveRouteGroup) {
    toggleSaveRouteBtn.addEventListener("click", () => {
      const isHidden = saveRouteGroup.style.display === "none";
      saveRouteGroup.style.display = isHidden ? "block" : "none";
      toggleSaveRouteBtn.textContent = isHidden ? "✕ Close" : "+ Save Route";
      if (isHidden && saveRouteNameInput && !saveRouteNameInput.value) {
        const pVal = pickupInput ? pickupInput.value.split(/[,(/]/)[0].trim() : "";
        const dVal = destInput ? destInput.value.split(/[,(/]/)[0].trim() : "";
        if (pVal && dVal) {
          saveRouteNameInput.value = `${pVal} to ${dVal}`;
        } else {
          saveRouteNameInput.placeholder = "e.g. Home to Office, Gym to Work";
        }
        saveRouteNameInput.focus();
      }
    });
  }

  if (btnSaveCurrentRoute) {
    btnSaveCurrentRoute.addEventListener("click", (e) => {
      e.preventDefault();
      const routeName = saveRouteNameInput ? saveRouteNameInput.value.trim() : "";
      const pickup = pickupInput ? pickupInput.value.trim() : "";
      const destination = destInput ? destInput.value.trim() : "";
      const checkedCat = document.querySelector("input[name='category']:checked");
      const category = checkedCat ? checkedCat.value.toUpperCase() : "ECONOMY";

      if (!routeName) {
        if (saveRouteStatus) {
          saveRouteStatus.style.display = "block";
          saveRouteStatus.style.color = "var(--color-black)";
          saveRouteStatus.textContent = "Please enter a route label like 'Home to Office'.";
        }
        return;
      }

      if (!pickup || !destination) {
        if (saveRouteStatus) {
          saveRouteStatus.style.display = "block";
          saveRouteStatus.style.color = "var(--color-black)";
          saveRouteStatus.textContent = "Please enter both pickup and destination locations above.";
        }
        return;
      }

      btnSaveCurrentRoute.disabled = true;
      btnSaveCurrentRoute.textContent = "Saving...";

      fetch("/passenger/saved-routes", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          name: routeName,
          pickup_address: pickup,
          destination_address: destination,
          category: category
        })
      })
        .then((res) => {
          if (!res.ok) throw new Error("Could not save route");
          return res.json();
        })
        .then((data) => {
          btnSaveCurrentRoute.disabled = false;
          btnSaveCurrentRoute.textContent = "Save Route";

          if (data && data.success && data.route) {
            const rt = data.route;
            if (saveRouteStatus) {
              saveRouteStatus.style.display = "block";
              saveRouteStatus.style.color = "green";
              saveRouteStatus.textContent = `Route '${rt.name}' saved!`;
            }

            const routesList = document.getElementById("saved-routes-list");
            const emptyMsg = document.getElementById("no-saved-routes-msg");
            if (emptyMsg) emptyMsg.remove();

            if (routesList) {
              const itemDiv = document.createElement("div");
              itemDiv.className = "saved-route-item";
              itemDiv.id = `saved-route-${rt.id}`;
              itemDiv.style.border = "1px solid var(--color-light-grey)";
              itemDiv.style.borderRadius = "var(--radius-sm)";
              itemDiv.style.padding = "0.75rem 1rem";
              itemDiv.style.backgroundColor = "var(--color-white)";
              itemDiv.style.display = "flex";
              itemDiv.style.alignItems = "center";
              itemDiv.style.justifyContent = "space-between";
              itemDiv.style.gap = "0.75rem";
              itemDiv.style.flexWrap = "wrap";
              itemDiv.innerHTML = `
                <div style="flex: 1; min-width: 200px;">
                  <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                    <strong style="font-size: 0.875rem; color: var(--color-black);">${rt.name}</strong>
                    <span style="font-size: 0.6875rem; font-weight: 700; background-color: var(--color-black); color: var(--color-white); padding: 0.1rem 0.4rem; border-radius: 2px;">
                      ${rt.category}
                    </span>
                  </div>
                  <div style="font-size: 0.75rem; color: var(--color-dark-grey); line-height: 1.3;">
                    <span>${rt.pickup_address}</span>
                    <span style="color: var(--color-medium-grey); font-weight: 700; margin: 0 0.25rem;">→</span>
                    <span style="font-weight: 600;">${rt.destination_address}</span>
                  </div>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                  <button type="button" class="btn btn-primary btn-sm btn-apply-route" 
                          data-pickup="${rt.pickup_address}" 
                          data-destination="${rt.destination_address}" 
                          data-category="${rt.category}" 
                          data-name="${rt.name}">
                    Use Route
                  </button>
                  <form method="POST" action="/passenger/saved-routes/${rt.id}/delete" style="margin: 0;" class="form-delete-saved-route" data-route-id="${rt.id}">
                    <button type="submit" class="btn btn-secondary btn-sm" title="Remove route" style="padding: 0.25rem 0.5rem; font-size: 0.75rem; color: var(--color-dark-grey);">
                      ✕
                    </button>
                  </form>
                </div>
              `;
              routesList.prepend(itemDiv);

              const newApplyBtn = itemDiv.querySelector(".btn-apply-route");
              if (newApplyBtn) {
                newApplyBtn.addEventListener("click", () => {
                  applySavedRoute(rt.pickup_address, rt.destination_address, rt.category, rt.name);
                });
              }

              const newDeleteForm = itemDiv.querySelector(".form-delete-saved-route");
              if (newDeleteForm) {
                bindDeleteSavedRoute(newDeleteForm);
              }
            }

            setTimeout(() => {
              if (saveRouteGroup) saveRouteGroup.style.display = "none";
              if (toggleSaveRouteBtn) toggleSaveRouteBtn.textContent = "+ Save Route";
              if (saveRouteNameInput) saveRouteNameInput.value = "";
              if (saveRouteStatus) saveRouteStatus.style.display = "none";
            }, 1200);
          }
        })
        .catch(() => {
          btnSaveCurrentRoute.disabled = false;
          btnSaveCurrentRoute.textContent = "Save Route";
          if (saveRouteStatus) {
            saveRouteStatus.style.display = "block";
            saveRouteStatus.style.color = "red";
            saveRouteStatus.textContent = "Error saving route. Please try again.";
          }
        });
    });
  }

  function bindDeleteSavedRoute(form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const routeId = form.getAttribute("data-route-id");
      if (!routeId) return;

      fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then((res) => res.json())
        .then((data) => {
          if (data && data.success) {
            const item = document.getElementById(`saved-route-${routeId}`);
            if (item) {
              item.style.opacity = "0";
              item.style.transition = "opacity 0.3s ease";
              setTimeout(() => {
                item.remove();
                const list = document.getElementById("saved-routes-list");
                if (list && list.querySelectorAll(".saved-route-item").length === 0) {
                  list.innerHTML = `
                    <div id="no-saved-routes-msg" style="text-align: center; padding: 1rem; font-size: 0.8125rem; color: var(--color-medium-grey); background-color: var(--color-off-white); border-radius: var(--radius-sm);">
                      No saved routes yet. Enter your pickup and destination below and click <strong>"Save Route"</strong> to store routes like 'Home to Office'.
                    </div>
                  `;
                }
              }, 300);
            }
          }
        })
        .catch(() => {});
    });
  }

  document.querySelectorAll(".form-delete-saved-route").forEach(bindDeleteSavedRoute);

  // 5. Active Ride Status Auto-Polling
  const rideTrackingBox = document.getElementById("live-ride-tracker");
  if (rideTrackingBox) {
    const rideId = rideTrackingBox.getAttribute("data-ride-id");
    const connectionStatus = document.getElementById("passenger-ride-connection-status");
    let passengerPollActive = false;
    if (rideId) {
      const pollPassengerRide = async () => {
        if (passengerPollActive || document.hidden) return;
        passengerPollActive = true;
        try {
          const response = await fetch(`/api/ride-status/${encodeURIComponent(rideId)}`, {
            headers: { Accept: "application/json" },
            cache: "no-store",
          });
          if (!response.ok) throw new Error("Ride status request failed.");
          const data = await response.json();
          if (!data.success || !data.ride) throw new Error("Ride status response was invalid.");
          if (connectionStatus) connectionStatus.hidden = true;
          const driverChanged = rideTrackingBox.dataset.driverId !== (data.ride.driver_id || "");
          const responseChanged = rideTrackingBox.dataset.driverResponseStatus !== data.ride.driver_response_status;
          if (
            rideTrackingBox.dataset.status !== data.ride.status ||
            driverChanged ||
            responseChanged
          ) {
            window.location.reload();
          }
        } catch (error) {
          if (connectionStatus) connectionStatus.hidden = false;
          console.warn("Unable to refresh the passenger ride status.", error);
        } finally {
          passengerPollActive = false;
        }
      };
      pollPassengerRide();
      window.setInterval(pollPassengerRide, 5000);
    }
  }

  const driverRideTracker = document.getElementById("driver-live-ride-tracker");
  if (driverRideTracker) {
    const rideId = driverRideTracker.dataset.rideId;
    const statusLabel = document.getElementById("driver-live-ride-status");
    const controls = document.getElementById("driver-live-ride-controls");
    const cancelledAlert = document.getElementById("driver-ride-cancelled-alert");
    const connectionStatus = document.getElementById("driver-ride-connection-status");
    let stopped = false;
    let driverPollActive = false;
    const pollDriverRide = async () => {
      if (stopped || driverPollActive || document.hidden || !rideId) return;
      driverPollActive = true;
      try {
        const response = await fetch(`/api/ride-status/${encodeURIComponent(rideId)}`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Ride status request failed.");
        const result = await response.json();
        if (!result.success || !result.ride) throw new Error("Ride status response was invalid.");
        if (connectionStatus) connectionStatus.hidden = true;
        const ride = result.ride;
        if (ride.status === "CANCELLED") {
          stopped = true;
          driverRideTracker.dataset.status = ride.status;
          if (statusLabel) statusLabel.textContent = "CANCELLED";
          if (controls) controls.hidden = true;
          if (cancelledAlert) cancelledAlert.hidden = false;
          return;
        }
        if (ride.driver_id !== driverRideTracker.dataset.driverId) {
          window.location.reload();
          return;
        }
        if (ride.status !== driverRideTracker.dataset.status) {
          window.location.reload();
        }
      } catch (error) {
        if (connectionStatus) connectionStatus.hidden = false;
        console.warn("Unable to refresh the live ride status.", error);
      } finally {
        driverPollActive = false;
      }
    };
    pollDriverRide();
    window.setInterval(pollDriverRide, 5000);
  }

  // 6. Notification Dropdown Toggle and Dismiss Handlers
  window.toggleNotifDropdown = function (e) {
    if (e) e.preventDefault();
    const dropdown = document.getElementById("notif-dropdown");
    if (dropdown) {
      const isVisible = dropdown.style.display === "block";
      dropdown.style.display = isVisible ? "none" : "block";
    }
  };

  document.addEventListener("click", (e) => {
    const bellBtn = document.getElementById("notif-bell-btn");
    const dropdown = document.getElementById("notif-dropdown");
    if (dropdown && bellBtn && !bellBtn.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = "none";
    }
  });

  window.dismissNotifAjax = function (e, notifId) {
    if (e) e.preventDefault();
    fetch(`/notifications/${notifId}/dismiss`, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          const row = document.getElementById(`dropdown-notif-${notifId}`);
          if (row) row.remove();
          updateNotifBadge();
        }
      })
      .catch(() => {});
  };

  window.dismissNotifCard = function (e, notifId) {
    if (e) e.preventDefault();
    fetch(`/notifications/${notifId}/dismiss`, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          const card = document.getElementById(`notif-card-${notifId}`);
          if (card) {
            card.style.opacity = "0";
            setTimeout(() => card.remove(), 300);
          }
          updateNotifBadge();
        }
      })
      .catch(() => {});
  };

  function updateNotifBadge() {
    const badge = document.querySelector(".notification-badge");
    if (badge) {
      let count = parseInt(badge.textContent, 10) - 1;
      if (count <= 0) {
        badge.remove();
      } else {
        badge.textContent = count;
      }
    }
  }

  // 7. AI Customer Service Care Concierge (Gemini 3.8 Flash)
  const aiSupportToggle = document.getElementById("ai-support-toggle");
  const aiSupportPanel = document.getElementById("ai-support-panel");
  const aiSupportClose = document.getElementById("ai-support-close");
  const aiChatForm = document.getElementById("ai-chat-form");
  const aiChatInput = document.getElementById("ai-chat-input");
  const aiChatThread = document.getElementById("ai-chat-thread");
  const aiSendBtn = document.getElementById("ai-chat-send-btn");
  const aiPromptButtons = document.querySelectorAll(".ai-prompt-btn");

  const chatHistory = [];

  function setAISupportOpen(isOpen) {
    if (!aiSupportToggle || !aiSupportPanel) return;
    aiSupportPanel.hidden = !isOpen;
    aiSupportToggle.setAttribute("aria-expanded", String(isOpen));
    aiSupportToggle.setAttribute("aria-label", isOpen ? "Close RideEasy support chat" : "Open RideEasy support chat");
    if (isOpen && aiChatInput) aiChatInput.focus();
  }

  if (aiSupportToggle) {
    aiSupportToggle.addEventListener("click", () => {
      setAISupportOpen(aiSupportToggle.getAttribute("aria-expanded") !== "true");
    });
  }

  if (aiSupportClose) {
    aiSupportClose.addEventListener("click", () => {
      setAISupportOpen(false);
      if (aiSupportToggle) aiSupportToggle.focus();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && aiSupportPanel && !aiSupportPanel.hidden) {
      setAISupportOpen(false);
      if (aiSupportToggle) aiSupportToggle.focus();
    }
  });

  function formatAIResponse(rawText) {
    if (!rawText) return "";
    let safe = rawText
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    // Bold: **text**
    safe = safe.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    // Bullet points: lines starting with • or * or -
    safe = safe.replace(/^[•*-]\s+(.+)$/gm, "<div style='display: flex; gap: 0.35rem; margin-bottom: 0.25rem;'><span style='font-weight: 700;'>•</span><span>$1</span></div>");
    // Line breaks
    safe = safe.replace(/\n\n/g, "<br><br>");
    safe = safe.replace(/\n/g, "<br>");
    return safe;
  }

  function appendChatMessage(sender, text, isAI = false) {
    if (!aiChatThread) return;
    const msgDiv = document.createElement("div");
    msgDiv.className = `ai-chat-message ${isAI ? "bot" : "user"}`;

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (isAI) {
      msgDiv.style.alignSelf = "flex-start";
      msgDiv.style.maxWidth = "85%";
      msgDiv.style.backgroundColor = "var(--color-white)";
      msgDiv.style.border = "1px solid var(--color-light-grey)";
      msgDiv.style.borderRadius = "var(--radius-sm)";
      msgDiv.style.padding = "0.875rem 1rem";
      msgDiv.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.35rem;">
          <strong style="font-size: 0.8125rem; color: var(--color-black); display: flex; align-items: center; gap: 0.35rem;">
            <span>RideEasy Concierge</span>
            <span style="font-size: 0.625rem; font-weight: 700; background-color: var(--color-black); color: var(--color-white); padding: 0.1rem 0.35rem; border-radius: 2px;">AI</span>
          </strong>
          <span class="text-subtle" style="font-size: 0.6875rem;">${timeStr}</span>
        </div>
        <div class="ai-msg-content" style="font-size: 0.875rem; color: var(--color-dark-grey); line-height: 1.45;">
          ${formatAIResponse(text)}
        </div>
      `;
    } else {
      msgDiv.style.alignSelf = "flex-end";
      msgDiv.style.maxWidth = "80%";
      msgDiv.style.backgroundColor = "var(--color-black)";
      msgDiv.style.color = "var(--color-white)";
      msgDiv.style.borderRadius = "var(--radius-sm)";
      msgDiv.style.padding = "0.75rem 1rem";
      msgDiv.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.25rem;">
          <strong style="font-size: 0.75rem; color: var(--color-light-grey); text-transform: uppercase;">You</strong>
          <span style="font-size: 0.6875rem; color: var(--color-medium-grey);">${timeStr}</span>
        </div>
        <div style="font-size: 0.875rem; color: var(--color-white); line-height: 1.4;">
          ${text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}
        </div>
      `;
    }

    aiChatThread.appendChild(msgDiv);
    aiChatThread.scrollTop = aiChatThread.scrollHeight;
  }

  function sendAIQuestion(questionText) {
    if (!questionText || !questionText.trim()) return;
    const cleanQ = questionText.trim();

    appendChatMessage("user", cleanQ, false);
    chatHistory.push({ sender: "user", text: cleanQ });

    if (aiChatInput) aiChatInput.value = "";
    if (aiSendBtn) {
      aiSendBtn.disabled = true;
      aiSendBtn.innerHTML = `<span>Thinking...</span>`;
    }

    // Typing indicator
    const typingIndicator = document.createElement("div");
    typingIndicator.id = "ai-typing-indicator";
    typingIndicator.style.alignSelf = "flex-start";
    typingIndicator.style.padding = "0.5rem 0.875rem";
    typingIndicator.style.fontSize = "0.8125rem";
    typingIndicator.style.color = "var(--color-medium-grey)";
    typingIndicator.style.fontStyle = "italic";
    typingIndicator.textContent = "RideEasy Concierge is writing response...";
    aiChatThread.appendChild(typingIndicator);
    aiChatThread.scrollTop = aiChatThread.scrollHeight;

    fetch("/api/support/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: cleanQ, history: chatHistory })
    })
      .then((res) => {
        if (!res.ok) throw new Error("Support service unavailable");
        return res.json();
      })
      .then((data) => {
        if (typingIndicator) typingIndicator.remove();
        const reply = data.reply || "Our support team is currently assisting other passengers. Please call +256 700 123 456.";
        appendChatMessage("ai", reply, true);
        chatHistory.push({ sender: "ai", text: reply });
      })
      .catch((err) => {
        if (typingIndicator) typingIndicator.remove();
        appendChatMessage("ai", "I am having temporary trouble reaching the care network. You can reach our 24/7 Kampala team directly at +256 700 123 456 or support@rideeasy.ug.", true);
      })
      .finally(() => {
        if (aiSendBtn) {
          aiSendBtn.disabled = false;
          aiSendBtn.innerHTML = `
            <span class="ai-send-label">Send</span>
            <svg class="icon icon-sm" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          `;
        }
        if (aiChatInput && (!aiSupportPanel || !aiSupportPanel.hidden)) aiChatInput.focus();
      });
  }

  if (aiChatForm) {
    aiChatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (aiChatInput) {
        sendAIQuestion(aiChatInput.value);
      }
    });
  }

  if (aiPromptButtons && aiPromptButtons.length > 0) {
    aiPromptButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const query = btn.getAttribute("data-query");
        if (query) {
          sendAIQuestion(query);
        }
      });
    });
  }

  // 10. Passenger Dashboard Ride Search & Real-time Filtering
  const dashboardSearchInput = document.getElementById("dashboard-ride-search");
  const clearSearchBtn = document.getElementById("clear-ride-search-btn");
  const searchStatus = document.getElementById("search-filter-status");
  const quickSearchPills = document.querySelectorAll(".quick-search-pill");

  function filterDashboardRides(query) {
    const q = (query || "").toLowerCase().trim();
    const completedCards = document.querySelectorAll(".completed-ride-card");
    const recentRows = document.querySelectorAll(".recent-ride-row");

    if (clearSearchBtn) {
      clearSearchBtn.style.display = q ? "block" : "none";
    }

    let matchCount = 0;
    let totalItems = completedCards.length;

    completedCards.forEach((card) => {
      if (!q) {
        card.style.display = "";
        matchCount++;
        return;
      }
      const route = (card.getAttribute("data-route") || "").toLowerCase();
      const date = (card.getAttribute("data-date") || "").toLowerCase();
      const driver = (card.getAttribute("data-driver") || "").toLowerCase();
      const ref = (card.getAttribute("data-ref") || "").toLowerCase();
      const fullText = (card.textContent || "").toLowerCase();

      if (route.includes(q) || date.includes(q) || driver.includes(q) || ref.includes(q) || fullText.includes(q)) {
        card.style.display = "";
        matchCount++;
      } else {
        card.style.display = "none";
      }
    });

    recentRows.forEach((row) => {
      if (!q) {
        row.style.display = "";
        return;
      }
      const route = (row.getAttribute("data-route") || "").toLowerCase();
      const date = (row.getAttribute("data-date") || "").toLowerCase();
      const driver = (row.getAttribute("data-driver") || "").toLowerCase();
      const ref = (row.getAttribute("data-ref") || "").toLowerCase();
      const fullText = (row.textContent || "").toLowerCase();

      if (route.includes(q) || date.includes(q) || driver.includes(q) || ref.includes(q) || fullText.includes(q)) {
        row.style.display = "";
      } else {
        row.style.display = "none";
      }
    });

    if (searchStatus) {
      if (q) {
        searchStatus.textContent = `Showing ${matchCount} of ${totalItems} completed trip${totalItems === 1 ? '' : 's'} matching "${query.trim()}"`;
      } else {
        searchStatus.textContent = "";
      }
    }
  }

  if (dashboardSearchInput) {
    dashboardSearchInput.addEventListener("input", (e) => {
      filterDashboardRides(e.target.value);
    });

    // Check if initial value exists (e.g. from server-side query param)
    if (dashboardSearchInput.value) {
      filterDashboardRides(dashboardSearchInput.value);
    }
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener("click", () => {
      if (dashboardSearchInput) {
        dashboardSearchInput.value = "";
        dashboardSearchInput.focus();
      }
      filterDashboardRides("");
    });
  }

  if (quickSearchPills && quickSearchPills.length > 0) {
    quickSearchPills.forEach((pill) => {
      pill.addEventListener("click", () => {
        const query = pill.getAttribute("data-query") || "";
        if (dashboardSearchInput) {
          dashboardSearchInput.value = query;
          filterDashboardRides(query);
          dashboardSearchInput.focus();
        }
      });
    });
  }

  // 11. Interactive Star Rating and Trip Feedback AJAX Handling
  const ratingForms = document.querySelectorAll(".form-ride-rating");
  ratingForms.forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const rideId = form.getAttribute("data-ride-id");
      const submitBtn = form.querySelector(".btn-submit-rating");
      const originalBtnText = submitBtn ? submitBtn.innerHTML : "Submit Rating";
      const feedbackMsg = document.getElementById(`rating-feedback-${rideId}`);

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Saving...";
      }

      const formData = new FormData(form);

      fetch(form.action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest"
        },
        body: formData
      })
        .then((res) => {
          if (!res.ok) throw new Error("Failed to save rating");
          return res.json();
        })
        .then((data) => {
          const ratingVal = parseInt(data.rating, 10) || 5;
          const reviewText = (data.review || "").trim();

          // Build or update the rated badge box
          const ratingSection = document.getElementById(`rating-section-${rideId}`);
          let ratedBox = document.getElementById(`rated-badge-box-${rideId}`);

          let starsHtml = "";
          for (let s = 1; s <= 5; s++) {
            starsHtml += `<span class="${s <= ratingVal ? 'star-filled' : 'star-empty'}">★</span>`;
          }

          const boxHtml = `
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
              <span style="font-size: 0.6875rem; font-weight: 700; text-transform: uppercase; color: var(--color-medium-grey);">Your Rating:</span>
              <div class="star-display">
                ${starsHtml}
                <strong style="font-size: 0.8125rem; color: var(--color-black);">${ratingVal}/5</strong>
              </div>
              ${reviewText ? `<span style="font-size: 0.75rem; color: var(--color-dark-grey); font-style: italic;">“${escapeHtml(reviewText)}”</span>` : ''}
            </div>
            <button type="button" class="btn btn-secondary btn-sm btn-edit-rating" data-ride-id="${rideId}" style="font-size: 0.6875rem; padding: 0.15rem 0.5rem;">
              Edit Feedback
            </button>
          `;

          if (ratedBox) {
            ratedBox.innerHTML = boxHtml;
            ratedBox.style.display = "flex";
          } else if (ratingSection) {
            const newBox = document.createElement("div");
            newBox.className = "rated-badge-box";
            newBox.id = `rated-badge-box-${rideId}`;
            newBox.style.cssText = "display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; background-color: var(--color-off-white); padding: 0.5rem 0.75rem; border-radius: var(--radius-sm); border: 1px solid var(--color-light-grey); margin-bottom: 0.5rem;";
            newBox.innerHTML = boxHtml;
            ratingSection.insertBefore(newBox, form);
          }

          // Hide form and show cancel button inside form for future edits
          form.style.display = "none";
          let cancelBtn = form.querySelector(".btn-cancel-edit-rating");
          if (!cancelBtn) {
            cancelBtn = document.createElement("button");
            cancelBtn.type = "button";
            cancelBtn.className = "btn btn-secondary btn-sm btn-cancel-edit-rating";
            cancelBtn.setAttribute("data-ride-id", rideId);
            cancelBtn.style.fontSize = "0.75rem";
            cancelBtn.textContent = "Cancel";
            const rowActions = form.querySelector("div[style*='flex-wrap: wrap']");
            if (rowActions) rowActions.appendChild(cancelBtn);
          }

          // Re-attach edit & cancel listeners
          attachRatingToggles();

          // Also update rating column in the Recent City Rides table if present
          const tableRow = document.querySelector(`.recent-ride-row[data-ref="${rideId}"]`);
          if (tableRow) {
            const ratingCell = tableRow.children[5]; // Rating column
            if (ratingCell) {
              ratingCell.innerHTML = `
                <span class="star-display" style="font-size: 0.8125rem;" title="${escapeHtml(reviewText)}">
                  <span class="star-filled">★</span> ${ratingVal}/5
                </span>
              `;
            }
          }

          // Show temporary toast confirmation
          showRatingToast(`Thank you! Your ${ratingVal}-star rating has been recorded.`);
        })
        .catch((err) => {
          if (feedbackMsg) {
            feedbackMsg.style.display = "block";
            feedbackMsg.style.color = "var(--color-black)";
            feedbackMsg.textContent = "Could not save rating. Please check connection and try again.";
          }
        })
        .finally(() => {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnText;
          }
        });
    });
  });

  function attachRatingToggles() {
    document.querySelectorAll(".btn-edit-rating").forEach((btn) => {
      btn.onclick = () => {
        const rideId = btn.getAttribute("data-ride-id");
        const ratedBox = document.getElementById(`rated-badge-box-${rideId}`);
        const form = document.getElementById(`rating-form-${rideId}`);
        if (ratedBox) ratedBox.style.display = "none";
        if (form) {
          form.style.display = "block";
          const input = form.querySelector(".input-review-text");
          if (input) input.focus();
        }
      };
    });

    document.querySelectorAll(".btn-cancel-edit-rating").forEach((btn) => {
      btn.onclick = () => {
        const rideId = btn.getAttribute("data-ride-id");
        const ratedBox = document.getElementById(`rated-badge-box-${rideId}`);
        const form = document.getElementById(`rating-form-${rideId}`);
        if (form) form.style.display = "none";
        if (ratedBox) ratedBox.style.display = "flex";
      };
    });
  }

  attachRatingToggles();

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function showRatingToast(message) {
    const toast = document.createElement("div");
    toast.className = "alert alert-success";
    toast.style.cssText = "position: fixed; bottom: 2rem; right: 2rem; z-index: 9999; box-shadow: 0 4px 12px rgba(0,0,0,0.15); max-width: 380px; animation: fadeIn 0.3s ease;";
    toast.innerHTML = `
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span style="font-size: 1.1rem;">★</span>
        <span>${escapeHtml(message)}</span>
      </div>
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.4s ease";
      setTimeout(() => toast.remove(), 400);
    }, 4500);
  }

  window.focusRideRating = function (rideId) {
    const card = document.getElementById(`completed-ride-card-${rideId}`) || document.getElementById(`rating-section-${rideId}`);
    const form = document.getElementById(`rating-form-${rideId}`);
    const ratedBox = document.getElementById(`rated-badge-box-${rideId}`);

    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.style.outline = "2px solid var(--color-black)";
      setTimeout(() => {
        card.style.outline = "";
      }, 2000);
    }

    if (form) {
      if (ratedBox && ratedBox.style.display !== "none") {
        ratedBox.style.display = "none";
      }
      form.style.display = "block";
      const input = form.querySelector(".input-review-text");
      if (input) input.focus();
    }
  };

  // 12. Real-Time Driver Earnings Summary & Weekly Income Trend Chart
  const svgChartMount = document.getElementById("svg-chart-mount");
  const initialEarningsScript = document.getElementById("initial-earnings-data");

  if (svgChartMount && initialEarningsScript) {
    let earningsData = null;
    try {
      earningsData = JSON.parse(initialEarningsScript.textContent);
    } catch (e) {
      console.error("Failed to parse initial earnings data", e);
    }

    let currentMode = "bar"; // "bar" or "line"
    let selectedDate = earningsData && earningsData.days && earningsData.days.length > 0
      ? earningsData.days[earningsData.days.length - 1].date
      : null;

    const tooltip = document.getElementById("chart-tooltip");
    const chartWrapper = document.getElementById("earnings-chart-wrapper");
    const btnBar = document.getElementById("btn-chart-mode-bar");
    const btnLine = document.getElementById("btn-chart-mode-line");
    const btnRefresh = document.getElementById("btn-refresh-earnings");
    const refreshLabel = document.getElementById("refresh-earnings-label");
    const syncStatus = document.getElementById("earnings-sync-status");
    const pillsContainer = document.getElementById("day-pills-container");
    const dayDrawer = document.getElementById("selected-day-drawer");
    const drawerTitle = document.getElementById("drawer-day-title");
    const drawerMeta = document.getElementById("drawer-day-meta");
    const drawerTotal = document.getElementById("drawer-day-total");
    const drawerBody = document.getElementById("drawer-trips-body");

    function formatUgx(num) {
      return "UGX " + (num || 0).toLocaleString();
    }

    function formatK(num) {
      if (num >= 1000) {
        return (num / 1000).toFixed(num % 1000 === 0 ? 0 : 1) + "k";
      }
      return num.toString();
    }

    function renderChart() {
      if (!earningsData || !earningsData.days || earningsData.days.length === 0) {
        svgChartMount.innerHTML = `<div style="text-align: center; padding: 2rem; color: var(--color-medium-grey);">No earnings records available for the past week.</div>`;
        return;
      }

      const days = earningsData.days;
      const svgW = 800;
      const svgH = 260;
      const padL = 80;
      const padR = 35;
      const padT = 30;
      const padB = 60;
      const plotW = svgW - padL - padR;
      const plotH = svgH - padT - padB;
      const baseY = svgH - padB;

      const maxVal = Math.max(...days.map((d) => d.earnings_ugx), 20000);
      const step = Math.max(10000, Math.ceil(maxVal / 4 / 5000) * 5000);
      const ceiling = step * 4;

      let svgHtml = `<svg viewBox="0 0 ${svgW} ${svgH}" style="width: 100%; height: auto; overflow: visible; display: block;" role="img" aria-label="7-Day Earnings Trend Chart">`;

      // 1. Horizontal Reference Gridlines
      for (let i = 0; i <= 4; i++) {
        const gridVal = step * i;
        const gridY = baseY - (gridVal / ceiling) * plotH;
        svgHtml += `
          <line x1="${padL}" y1="${gridY}" x2="${svgW - padR}" y2="${gridY}" stroke="${i === 0 ? '#000000' : '#E5E5E5'}" stroke-width="${i === 0 ? '1.5' : '1'}" stroke-dasharray="${i === 0 ? 'none' : '3,3'}" />
          <text x="${padL - 10}" y="${gridY + 4}" text-anchor="end" font-size="10" font-weight="${i === 0 ? '700' : '500'}" fill="#666666">
            ${i === 0 ? '0' : formatK(gridVal)}
          </text>
        `;
      }

      const colW = plotW / days.length;
      const points = [];

      days.forEach((day, idx) => {
        const xCenter = padL + idx * colW + colW / 2;
        const val = day.earnings_ugx;
        const barH = val > 0 ? Math.max(6, Math.round((val / ceiling) * plotH)) : 3;
        const barY = baseY - barH;
        const isSelected = day.date === selectedDate;
        points.push({ x: xCenter, y: barY, day: day, idx: idx, val: val });

        if (currentMode === "bar") {
          const barW = Math.min(50, colW * 0.58);
          const barX = xCenter - barW / 2;
          svgHtml += `
            <g class="chart-group" data-idx="${idx}" style="cursor: pointer;">
              <rect class="chart-bar ${day.is_today ? 'bar-today' : ''} ${isSelected ? 'is-selected' : ''}"
                    x="${barX}" y="${barY}" width="${barW}" height="${barH}" rx="3"
                    data-idx="${idx}" data-date="${day.date}" data-fare="${val}" data-trips="${day.trip_count}" />
              <text x="${xCenter}" y="${barY - 8}" text-anchor="middle" font-size="11" font-weight="${day.is_today || isSelected ? '700' : '600'}" fill="${val > 0 ? '#000000' : '#999999'}">
                ${val > 0 ? formatK(val) : '0'}
              </text>
            </g>
          `;
        }

        // X Axis labels
        svgHtml += `
          <g class="x-axis-group" data-idx="${idx}" style="cursor: pointer;">
            <text x="${xCenter}" y="${baseY + 18}" text-anchor="middle" font-size="11" font-weight="${day.is_today ? '700' : '500'}" fill="#000000">
              ${day.day_name}
            </text>
            <text x="${xCenter}" y="${baseY + 32}" text-anchor="middle" font-size="10" fill="#777777">
              ${day.short_label}
            </text>
            ${
              day.is_today
                ? `<rect x="${xCenter - 22}" y="${baseY + 37}" width="44" height="15" rx="2" fill="#000000" />
                   <text x="${xCenter}" y="${baseY + 48}" text-anchor="middle" font-size="8.5" font-weight="700" fill="#FFFFFF">TODAY</text>`
                : ""
            }
          </g>
        `;
      });

      if (currentMode === "line") {
        // Area polygon
        let areaPoints = `${points[0].x},${baseY} `;
        points.forEach((p) => {
          areaPoints += `${p.x},${p.y} `;
        });
        areaPoints += `${points[points.length - 1].x},${baseY}`;

        svgHtml += `<polygon points="${areaPoints}" fill="rgba(0, 0, 0, 0.07)" />`;

        // Connecting line
        let polyPoints = points.map((p) => `${p.x},${p.y}`).join(" ");
        svgHtml += `<polyline points="${polyPoints}" fill="none" stroke="#000000" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />`;

        // Dots & text
        points.forEach((p) => {
          const isSelected = p.day.date === selectedDate;
          svgHtml += `
            <g class="chart-group" data-idx="${p.idx}" style="cursor: pointer;">
              <circle class="chart-dot ${isSelected ? 'is-selected' : ''}" cx="${p.x}" cy="${p.y}" r="${isSelected ? 7 : 5}" data-idx="${p.idx}" />
              <text x="${p.x}" y="${p.y - 12}" text-anchor="middle" font-size="11" font-weight="${p.day.is_today || isSelected ? '700' : '600'}" fill="${p.val > 0 ? '#000000' : '#999999'}">
                ${p.val > 0 ? formatK(p.val) : '0'}
              </text>
            </g>
          `;
        });
      }

      svgHtml += `</svg>`;
      svgChartMount.innerHTML = svgHtml;

      attachChartEvents();
    }

    function attachChartEvents() {
      const groups = svgChartMount.querySelectorAll(".chart-group, .x-axis-group");
      groups.forEach((el) => {
        const idx = parseInt(el.getAttribute("data-idx"), 10);
        const day = earningsData.days[idx];
        if (!day) return;

        el.addEventListener("mouseenter", (e) => {
          if (!tooltip || !chartWrapper) return;
          const rect = chartWrapper.getBoundingClientRect();
          const targetRect = el.getBoundingClientRect();
          const x = targetRect.left - rect.left + targetRect.width / 2;
          const y = targetRect.top - rect.top;

          tooltip.innerHTML = `
            <div style="font-weight: 700; margin-bottom: 2px;">${day.label}${day.is_today ? ' · (Today)' : ''}</div>
            <div style="font-size: 0.8125rem; font-weight: 800; color: #FFFFFF;">${formatUgx(day.earnings_ugx)}</div>
            <div style="color: #BBBBBB; font-size: 0.6875rem;">${day.trip_count} trip${day.trip_count === 1 ? '' : 's'} completed</div>
          `;
          tooltip.style.left = `${x}px`;
          tooltip.style.top = `${y}px`;
          tooltip.style.display = "block";
          tooltip.style.opacity = "1";
        });

        el.addEventListener("mouseleave", () => {
          if (tooltip) {
            tooltip.style.opacity = "0";
            tooltip.style.display = "none";
          }
        });

        el.addEventListener("click", () => {
          selectDay(day.date);
        });
      });
    }

    function renderDayPills() {
      if (!pillsContainer || !earningsData || !earningsData.days) return;
      let html = "";
      earningsData.days.forEach((day) => {
        const isSelected = day.date === selectedDate;
        html += `
          <div class="day-pill-btn ${isSelected ? 'active' : ''}" data-date="${day.date}">
            <div style="font-weight: 700;">${day.day_name}</div>
            <div class="text-subtle" style="font-size: 0.6875rem;">${day.short_label}</div>
            <div style="font-weight: 800; margin-top: 0.2rem; font-size: 0.75rem;">${formatK(day.earnings_ugx)}</div>
            ${day.is_today ? '<span style="display:inline-block; font-size: 0.5625rem; font-weight:700; padding:0 3px; border-radius:2px; background:' + (isSelected ? '#fff' : '#000') + '; color:' + (isSelected ? '#000' : '#fff') + ';">TODAY</span>' : ''}
          </div>
        `;
      });
      pillsContainer.innerHTML = html;

      pillsContainer.querySelectorAll(".day-pill-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          selectDay(btn.getAttribute("data-date"));
        });
      });
    }

    function selectDay(dateStr) {
      selectedDate = dateStr;
      renderChart();
      renderDayPills();

      if (!dayDrawer || !earningsData || !earningsData.days) return;
      const day = earningsData.days.find((d) => d.date === dateStr);
      if (!day) return;

      dayDrawer.style.display = "block";
      if (drawerTitle) {
        drawerTitle.textContent = `${day.label} ${day.is_today ? '(Today)' : ''}`;
      }
      if (drawerMeta) {
        drawerMeta.textContent = `· ${day.trip_count} completed trip${day.trip_count === 1 ? '' : 's'}`;
      }
      if (drawerTotal) {
        drawerTotal.textContent = formatUgx(day.earnings_ugx);
      }

      if (drawerBody) {
        if (!day.trips || day.trips.length === 0) {
          drawerBody.innerHTML = `<p style="margin: 0; color: var(--color-medium-grey); font-style: italic;">No completed trips recorded on this day.</p>`;
        } else {
          let listHtml = `<div style="display: flex; flex-direction: column; gap: 0.5rem;">`;
          day.trips.forEach((t) => {
            listHtml += `
              <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; background: var(--color-white); padding: 0.5rem 0.75rem; border-radius: var(--radius-sm); border: 1px solid var(--color-light-grey);">
                <div>
                  <div style="font-weight: 700; color: var(--color-black);">${escapeHtml(t.route)}</div>
                  <div class="text-subtle" style="font-size: 0.6875rem;">
                    #${t.id ? t.id.substring(0, 8).toUpperCase() : ''} · ${t.category} · Passenger: ${escapeHtml(t.passenger || 'Verified Passenger')} · ${t.time || ''}
                  </div>
                </div>
                <div style="font-weight: 800; font-size: 0.9375rem; color: var(--color-black);">
                  ${formatUgx(t.fare_ugx)}
                </div>
              </div>
            `;
          });
          listHtml += `</div>`;
          drawerBody.innerHTML = listHtml;
        }
      }
    }

    // Chart Mode Toggle: Bar vs Line
    if (btnBar && btnLine) {
      btnBar.addEventListener("click", () => {
        currentMode = "bar";
        btnBar.style.backgroundColor = "var(--color-black)";
        btnBar.style.color = "var(--color-white)";
        btnLine.style.backgroundColor = "var(--color-white)";
        btnLine.style.color = "var(--color-dark-grey)";
        renderChart();
      });

      btnLine.addEventListener("click", () => {
        currentMode = "line";
        btnLine.style.backgroundColor = "var(--color-black)";
        btnLine.style.color = "var(--color-white)";
        btnBar.style.backgroundColor = "var(--color-white)";
        btnBar.style.color = "var(--color-dark-grey)";
        renderChart();
      });
    }

    // Refresh Live Earnings
    if (btnRefresh) {
      btnRefresh.addEventListener("click", () => {
        if (refreshLabel) refreshLabel.textContent = "Syncing...";
        btnRefresh.disabled = true;

        fetch("/driver/api/earnings-summary")
          .then((res) => {
            if (!res.ok) throw new Error("Earnings API error");
            return res.json();
          })
          .then((data) => {
            if (data.success && data.summary) {
              earningsData = data.summary;

              // Update KPIs
              const kpiWeek = document.getElementById("kpi-week-earnings");
              const kpiWeekTrips = document.getElementById("kpi-week-trips");
              const kpiToday = document.getElementById("kpi-today-earnings");
              const kpiTodayTrips = document.getElementById("kpi-today-trips");
              const kpiAvg = document.getElementById("kpi-avg-earnings");
              const kpiPeak = document.getElementById("kpi-peak-earnings");
              const kpiPeakLabel = document.getElementById("kpi-peak-label");

              if (kpiWeek) kpiWeek.textContent = formatUgx(earningsData.total_week_earnings);
              if (kpiWeekTrips) kpiWeekTrips.textContent = earningsData.total_week_trips;
              if (kpiToday) kpiToday.textContent = formatUgx(earningsData.today_earnings);
              if (kpiTodayTrips) kpiTodayTrips.textContent = `${earningsData.today_trips} trip${earningsData.today_trips === 1 ? '' : 's'}`;
              if (kpiAvg) kpiAvg.textContent = formatUgx(earningsData.avg_daily_earnings);
              if (kpiPeak) kpiPeak.textContent = formatUgx(earningsData.max_day_earnings);
              if (kpiPeakLabel) kpiPeakLabel.innerHTML = `Best: <strong>${earningsData.max_day_label}</strong>`;

              renderChart();
              renderDayPills();
              selectDay(selectedDate || (earningsData.days[earningsData.days.length - 1]?.date));

              if (syncStatus) {
                const nowStr = new Date().toLocaleTimeString();
                syncStatus.textContent = `Live synced at ${nowStr}`;
              }
            }
          })
          .catch((err) => {
            console.error(err);
            if (syncStatus) syncStatus.textContent = "Sync failed. Retry shortly.";
          })
          .finally(() => {
            btnRefresh.disabled = false;
            if (refreshLabel) refreshLabel.textContent = "Refresh Live";
          });
      });
    }

    // Initial render
    renderChart();
    renderDayPills();
    if (selectedDate) {
      selectDay(selectedDate);
    }
  }

  // 13. RideEasy Rewards Points Tracker & Benefits Redemption
  const redeemForms = document.querySelectorAll(".form-redeem-perk");
  redeemForms.forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const rewardId = form.getAttribute("data-reward-id");
      const rewardTitle = form.getAttribute("data-reward-title") || "Perk";
      const cost = form.getAttribute("data-cost") || "points";
      const submitBtn = form.querySelector(".btn-redeem-action");
      const originalText = submitBtn ? submitBtn.textContent : "Redeem Perk";

      if (!confirm(`Redeem "${rewardTitle}" for ${cost} points?`)) {
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Redeeming...";
      }

      const formData = new FormData(form);

      fetch(form.action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest"
        },
        body: formData
      })
        .then((res) => {
          if (!res.ok) {
            return res.json().then((errData) => {
              throw new Error(errData.error || "Redemption failed");
            });
          }
          return res.json();
        })
        .then((data) => {
          if (data.success && data.voucher) {
            const v = data.voucher;
            // Update points KPI counters
            const availPtsEl = document.getElementById("rewards-available-pts");
            const spentPtsEl = document.getElementById("rewards-spent-pts");
            const neededPtsEl = document.getElementById("rewards-pts-needed");

            if (availPtsEl && data.rewards) {
              availPtsEl.innerHTML = `${data.rewards.available_points.toLocaleString()} <span style="font-size: 0.875rem; font-weight: 600; color: var(--color-medium-grey);">PTS</span>`;
            }
            if (spentPtsEl && data.rewards) {
              spentPtsEl.textContent = data.rewards.total_spent_points.toLocaleString();
            }

            // Prepend new voucher to active vouchers list
            let voucherContainer = document.getElementById("active-vouchers-container");
            if (!voucherContainer) {
              const rewardsCard = document.getElementById("rideeasy-rewards-card");
              const catalogSection = document.getElementById("redeemable-benefits-section");
              const wrapper = document.createElement("div");
              wrapper.style.marginBottom = "1.5rem";
              wrapper.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                  <span style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-black);">
                    Your Active Vouchers & Travel Perks:
                  </span>
                  <span class="text-subtle" style="font-size: 0.75rem;">1 Active Perk</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.5rem;" id="active-vouchers-container"></div>
              `;
              if (rewardsCard && catalogSection) {
                rewardsCard.insertBefore(wrapper, catalogSection);
              }
              voucherContainer = document.getElementById("active-vouchers-container");
            }

            if (voucherContainer) {
              const newVoucherEl = document.createElement("div");
              newVoucherEl.className = "voucher-item-box";
              newVoucherEl.style.cssText = "display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem; background-color: var(--color-off-white); border: 2px solid var(--color-black); padding: 0.75rem 1rem; border-radius: var(--radius-sm); animation: fadeIn 0.4s ease;";
              newVoucherEl.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                  <div style="font-size: 1.25rem;">🎟️</div>
                  <div>
                    <div style="font-weight: 700; color: var(--color-black); font-size: 0.9375rem;">
                      ${escapeHtml(v.title)} <span style="font-size: 0.625rem; font-weight: 700; background-color: var(--color-black); color: var(--color-white); padding: 0.1rem 0.35rem; border-radius: 2px; margin-left: 0.25rem;">NEW</span>
                    </div>
                    <div class="text-subtle" style="font-size: 0.75rem;">
                      Redeemed for ${v.points_spent} pts · ${v.discount_percent ? `${v.discount_percent}% off one ride` : "Valid for 60 days"}
                    </div>
                  </div>
                </div>

                <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                  <span class="voucher-code-badge" title="Click to copy voucher code" onclick="copyVoucherCode('${v.voucher_code}', this)">
                    <span>${v.voucher_code}</span>
                    <svg class="icon icon-sm" viewBox="0 0 24 24" style="cursor: pointer; stroke: #FFFFFF;"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                  </span>
                  <span style="font-size: 0.6875rem; font-weight: 700; background-color: var(--color-black); color: var(--color-white); padding: 0.15rem 0.4rem; border-radius: var(--radius-sm);">
                    ACTIVE
                  </span>
                </div>
              `;
              voucherContainer.insertBefore(newVoucherEl, voucherContainer.firstChild);
            }

            // Update benefits catalog cards dynamically if points decreased
            if (data.rewards && data.rewards.benefits) {
              data.rewards.benefits.forEach((b) => {
                const card = document.getElementById(`benefit-card-${b.id}`);
                if (!card) return;
                const actionContainer = card.querySelector("div:last-child");
                if (b.can_redeem) {
                  card.classList.remove("is-locked");
                  card.classList.add("is-unlocked");
                } else {
                  card.classList.remove("is-unlocked");
                  card.classList.add("is-locked");
                  if (actionContainer) {
                    actionContainer.innerHTML = `
                      <span class="text-subtle" style="font-size: 0.75rem;">${b.points_cost} points · ${Math.ceil(b.points_cost / 100)} paid trips</span>
                      <button type="button" class="btn btn-secondary btn-sm" disabled style="opacity: 0.6; cursor: not-allowed; font-size: 0.75rem; padding: 0.25rem 0.5rem;" title="Complete more journeys to earn points">
                        Need ${b.needed_points} pts (${b.needed_trips} paid trips)
                      </button>
                    `;
                  }
                }
              });
            }

            showRatingToast(`Perk redeemed! Voucher Code: ${v.voucher_code}`);
          }
        })
        .catch((err) => {
          alert(err.message || "Failed to redeem perk. Please try again.");
        })
        .finally(() => {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
          }
        });
    });
  });

  window.copyVoucherCode = function (code, badgeEl) {
    if (!navigator.clipboard) {
      prompt("Copy voucher code:", code);
      return;
    }
    navigator.clipboard.writeText(code).then(() => {
      showRatingToast(`Voucher code "${code}" copied to clipboard!`);
      if (badgeEl) {
        const originalBg = badgeEl.style.backgroundColor;
        badgeEl.style.backgroundColor = "#333333";
        setTimeout(() => {
          badgeEl.style.backgroundColor = originalBg;
        }, 1200);
      }
    });
  };
});
