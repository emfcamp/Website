const { verified } = require("@primer/octicons");
const filterStorageKey = "volunteer-filters:v6";

function saveFilters() {
  localStorage.setItem(filterStorageKey, JSON.stringify(getFilters()));
}

function loadFilters() {
  let savedFilters = localStorage.getItem(filterStorageKey);
  if (savedFilters === null) {
    let interestedRoles = Array.from(
      document.querySelectorAll("input[data-role-id]"),
    )
      .filter((box) => box.getAttribute("data-interested") == "True")
      .map((box) => box.getAttribute("data-role-id"));
    savedFilters = JSON.stringify({
      role_ids: interestedRoles,
      show_past: false,
      signed_up: true,
      hide_full: true,
      hide_staffed: true,
      hide_conflicting: true,
      hide_unfinalised: false,
    });
  }

  let filters = JSON.parse(savedFilters);
  document.querySelectorAll("input[data-role-id]").forEach((node) => {
    node.checked = filters.role_ids.includes(node.getAttribute("data-role-id"));
  });
  document.getElementById("show_past").checked = filters.show_past;
  document.getElementById("show_signed_up_only").checked = filters.signed_up;
  document.getElementById("hide_full").checked = filters.hide_full;
  document.getElementById("is_understaffed").checked = filters.hide_staffed;
  document.getElementById("hide_conflicting").checked =
    filters.hide_conflicting;

  // Only admins have that button.
  hide_unfinalised = document.getElementById("hide_unfinalised");
  if (hide_unfinalised) {
    document.getElementById("hide_unfinalised").checked =
      filters.hide_unfinalised;
  }

  updateRowDisplay();
}

function getFilters() {
  let filters = {
    role_ids: Array.from(
      document.querySelectorAll("input[data-role-id]:checked"),
    ).map((node) => node.getAttribute("data-role-id")),
    show_past: document.getElementById("show_past").checked,
    signed_up: document.getElementById("show_signed_up_only").checked,
    hide_full: document.getElementById("hide_full").checked,
    hide_staffed: document.getElementById("is_understaffed").checked,
    hide_conflicting: document.getElementById("hide_conflicting").checked,
    hide_unfinalised: document.getElementById("hide_unfinalised").checked,
  };
  return filters;
}

function getNodeData(node) {
  return {
    start: node.getAttribute("data-shift-start"),
    end: node.getAttribute("data-shift-end"),
    role_id: node.getAttribute("data-role-id"),
    staffed: node.getAttribute("data-staffed") == "True",
    signed_up: node.getAttribute("data-signed-up") == "True",
    full: node.getAttribute("data-full") == "True",
    min_staff: parseInt(node.getAttribute("data-min-staff")),
    max_staff: parseInt(node.getAttribute("data-max-staff")),
    current_staff: parseInt(node.getAttribute("data-current-staff")),
    conflicts_with: node.getAttribute("data-conflicts-with"),
    finalised: node.getAttribute("data-finalised") == "True",
  };
}

function shouldDisplayNode(node_data, filters, node) {
  // If the signed up shifts filter is active, or we're not set to show shifts
  // in the past then those take precedence over all others and we short
  // circuit everything else.
  if (!filters["show_past"]) {
    let now = new Date().toISOString();
    if (now > node_data["end"]) {
      return false;
    }
  }

  if (filters["signed_up"] && node_data["signed_up"]) {
    return true;
  }

  // Now run through the other filters and see if there's any other reasons to
  // filter out a shift. This is done by collecting a list of keys because it
  // makes debugging easier (they're attached to the node as data-filter-reasons).
  let filter_reasons = [];
  if (!filters["role_ids"].includes(node_data["role_id"])) {
    filter_reasons.push("role_id");
  }
  if (filters["hide_full"] && node_data["full"]) {
    filter_reasons.push("full");
  }
  if (filters["hide_staffed"] && node_data["staffed"]) {
    filter_reasons.push("staffed");
  }
  if (
    filters["hide_conflicting"] &&
    node_data["conflicts_with"] == "volunteer_shift"
  ) {
    filter_reasons.push("conflicting");
  }
  if (filters["hide_unfinalised"] && !node_data["finalised"]) {
    filter_reasons.push("unfinalised");
  }
  if (filter_reasons.length > 0) {
    node.setAttribute("data-filter-reasons", filter_reasons.join(","));
  } else {
    node.setAttribute("data-filter-reasons", "");
  }

  return filter_reasons.length === 0;
}

function spanStartTimeCell(firstNodeOfHour, rowCount) {
  if (firstNodeOfHour !== null) {
    let start_time_cell = firstNodeOfHour.querySelector(".start_time");
    start_time_cell.setAttribute("rowspan", rowCount);
    start_time_cell.classList.remove("hidden");
  }
}

function updateRoleList(role_ids) {
  let roleNames = role_ids
    .map((id) => document.getElementById(`role-${id}-label`).textContent.trim())
    .join(", ");
  document.getElementById("role-list").textContent = roleNames;
}

function updateRowDisplay() {
  let filters = getFilters();

  updateRoleList(filters.role_ids);

  // Hackery to do row spans.
  let currentHour = "null";
  let firstNodeOfHour = null;
  let rowCount = 0;

  // Iterate over each row (representing a shift), and choose which ones to
  // display.
  var rows = document.querySelectorAll("table.shifts-table tbody tr");
  rows.forEach((node, idx) => {
    let node_data = getNodeData(node);

    if (shouldDisplayNode(node_data, filters, node)) {
      if (node.getAttribute("data-shift-start") != currentHour) {
        // When we transition to a new hour we calculate how many rows
        // are shown for that hour, and span the first start time cell
        // over all of them.
        spanStartTimeCell(firstNodeOfHour, rowCount);

        firstNodeOfHour = node;
        rowCount = 0;
        currentHour = node.getAttribute("data-shift-start");
      } else {
        // Otherwise we hide the start time cell.
        node.querySelector(".start_time").classList.add("hidden");
      }

      rowCount += 1;

      node.classList.remove("hidden");
    } else {
      node.classList.add("hidden");
    }

    if (idx == rows.length - 1) {
      spanStartTimeCell(firstNodeOfHour, rowCount);
    }
  });
}

function init_volunteer_schedule() {
  loadFilters();
  [
    "show_past",
    "show_signed_up_only",
    "hide_full",
    "is_understaffed",
    "hide_conflicting",
    "hide_unfinalised",
  ].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      saveFilters();
      updateRowDisplay();
    });
  });

  ["filters", "roles"].forEach((panel) => {
    document.getElementById(panel).style.display = "";
    if (
      panel == "roles" &&
      document.querySelectorAll("input[data-role-id]:checked").length == 0
    ) {
      // Show the roles panel if none are selected
      $(`#roles-body`).toggle(true);
    }
    document.getElementById(`${panel}-toggle`).addEventListener("click", () => {
      $(`#${panel}-body`).toggle();
    });
  });

  document.querySelectorAll("input[data-role-id]").forEach((node) => {
    node.addEventListener("change", () => {
      saveFilters();
      updateRowDisplay();
    });
  });

  document.getElementById("select-all-roles").addEventListener("click", () => {
    document
      .querySelectorAll("input[data-role-id]")
      .forEach((checkbox) => (checkbox.checked = true));
    saveFilters();
    updateRowDisplay();
  });
  document.getElementById("select-no-roles").addEventListener("click", () => {
    document
      .querySelectorAll("input[data-role-id]")
      .forEach((checkbox) => (checkbox.checked = false));
    saveFilters();
    updateRowDisplay();
  });
  document
    .getElementById("select-interested-roles")
    .addEventListener("click", () => {
      document
        .querySelectorAll("input[data-role-id]")
        .forEach(
          (checkbox) =>
            (checkbox.checked =
              checkbox.getAttribute("data-interested") == "True"),
        );
      saveFilters();
      updateRowDisplay();
    });
  document
    .getElementById("select-trained-roles")
    .addEventListener("click", () => {
      document
        .querySelectorAll("input[data-role-id]")
        .forEach(
          (checkbox) =>
            (checkbox.checked =
              checkbox.getAttribute("data-trained") == "True"),
        );
      saveFilters();
      updateRowDisplay();
    });
  document
    .getElementById("select-owned-roles")
    .addEventListener("click", () => {
      document
        .querySelectorAll("input[data-role-id]")
        .forEach(
          (checkbox) =>
            (checkbox.checked = checkbox.getAttribute("data-owned") == "True"),
        );
      saveFilters();
      updateRowDisplay();
    });
  document.getElementById("select-day").addEventListener("change", (ev) => {
    document.location.replace(ev.target.value);
  });

  function showConflictModal(details) {
    const time = (iso) =>
      new Date(iso).toLocaleTimeString([], {
        timeStyle: "short",
      });
    const msgEl = document.getElementById("conflict-modal-message");
    msgEl.innerHTML = "";
    details.forEach((conflict) => {
      const p = document.createElement("p");
      const title = conflict.title;
      p.textContent = `Conflicts with ${conflict.human_type.toLowerCase()}: ${title} (${time(conflict.start_time)}–${time(conflict.end_time)})`;
      msgEl.appendChild(p);
    });
    $("#conflict-modal").modal("show");
  }

  document.querySelectorAll("td.conflicts").forEach((cell) => {
    const row = cell.closest("tr");
    if (
      !row.getAttribute("data-conflicts-with") ||
      row.getAttribute("data-signed-up") == "True"
    )
      return;

    cell.style.cursor = "pointer";

    cell.addEventListener("click", () => {
      const details = JSON.parse(
        row.getAttribute("data-conflicts-detail") || "[]",
      );

      if (row.getAttribute("data-signed-up") != "True") {
        showConflictModal(details);
      }
    });
  });
}

init_volunteer_schedule();
