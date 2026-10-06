const count = document.getElementById("ticket-count");
if (count) {
  fetch("/api/tickets")
    .then((response) => {
      if (!response.ok) throw new Error("Queue unavailable");
      return response.json();
    })
    .then((data) => {
      count.textContent = String(data.items.length);
      document.getElementById("api-status").textContent =
        "Live queue connected";
    })
    .catch(() => {
      document.getElementById("api-status").textContent =
        "Queue temporarily unavailable";
    });
}
