class WorkshopSteward {
  static async handleTicketCodeClick(e) {
    const button = e.target.closest("button[data-ticket_code_id]");
    if (!button) return;

    e.preventDefault();

    const action = button.dataset.action;
    const ticket_code_id = Number(button.dataset.ticket_code_id);
    const data = { action, ticket_code_id };

    const url = e.target.closest("form").dataset.url;
    const response = await fetch(url, {
      method: "PUT",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (response.status == 409) {
      alert(
        `This ticket was already ${action == "use" ? "checked in" : "un-checked in"}.`,
      );
      // fall through
    } else if (response.status != 200) {
      alert(`Unexpected error: ${result.error}`);
      return;
    }

    const container = button.closest(".ticket-code");
    if (!container) return;
    container.classList.toggle("used", result.used);
    container.classList.toggle("unused", result.unused);

    await WorkshopSteward.updateStats(result.stats);
  }

  static async handleOnTheDoorClick(e) {
    const button = e.target.closest("button[data-action]");
    if (!button) return;

    e.preventDefault();

    const action = button.dataset.action;
    const data = { action };

    const url = e.target.closest("form").dataset.url;
    const response = await fetch(url, {
      method: "PUT",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (response.status == 409) {
      if (action == "inc") {
        // Should never happen
      } else {
        alert(`All attendees have been checked out already.`);
      }
    } else if (response.status != 200) {
      alert(`Unexpected error: ${result.error}`);
      return;
    }

    await WorkshopSteward.updateStats(result.stats);
  }

  static async fetchStats() {
    const url = document.getElementById("stats").dataset.url;
    const response = await fetch(url, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
    });
    if (response.status != 200) return;
    const result = await response.json();

    await WorkshopSteward.updateStats(result.stats);
  }

  static async updateStats(stats) {
    const panel = document.querySelector(".capacity-panel");
    panel.querySelector(".total-tickets-used").textContent =
      stats.ticket_codes_used + stats.on_the_door_used;
    panel.querySelector(".total-tickets").textContent = stats.total_tickets;
    const full =
      stats.ticket_codes_used + stats.on_the_door_used >= stats.total_tickets;
    panel.classList.toggle("full", full);

    panel.querySelector(".ticket-codes-used").textContent =
      stats.ticket_codes_used;
    panel.querySelector(".ticket-codes").textContent = stats.ticket_codes;

    panel.querySelector(".on-the-door-used").textContent =
      stats.on_the_door_used;
    panel.querySelector(".on-the-door").textContent = stats.on_the_door;

    const disableDec = stats.reserved_tickets_used == 0;
    panel.querySelector('button[data-action="dec"]').disabled = disableDec;

    // TODO: disable ticket-code check-in when we're at capacity?
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document
    .querySelector("form.ticket-codes")
    .addEventListener("click", WorkshopSteward.handleTicketCodeClick);
  document
    .querySelector("form.on-the-door")
    .addEventListener("click", WorkshopSteward.handleOnTheDoorClick);
  document.querySelector("body").classList.add("js-inited");
  setInterval(WorkshopSteward.fetchStats, 10 * 1000);
});
