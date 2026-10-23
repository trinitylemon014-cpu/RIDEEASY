(() => {
  document.querySelectorAll(".route-planner-link").forEach((link) => {
    link.addEventListener("click", (event) => {
      const start = document.getElementById(link.dataset.startId);
      const destination = document.getElementById(link.dataset.destinationId);
      if (!start || !destination) return;

      event.preventDefault();
      const url = new URL(link.href, window.location.origin);
      url.searchParams.set("pickup", start.value.trim());
      url.searchParams.set("destination", destination.value.trim());
      window.location.assign(url);
    });
  });
})();
