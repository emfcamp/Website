function saveFilters() {
    localStorage.setItem("volunteer-filters:v2", JSON.stringify(getFilters()))
}

function loadFilters() {
    let savedFilters = localStorage.getItem("volunteer-filters:v2");
    if (savedFilters === null) {
        return
    }

    filters = JSON.parse(savedFilters)
    document.querySelectorAll("input[data-role-id]").forEach(node => {
        node.checked = filters.role_ids.includes(node.getAttribute("data-role-id"))
    })
    document.getElementById("show_past").checked = filters.show_finished_shifts;
    document.getElementById("show_signed_up_only").checked = filters.signed_up
    document.getElementById("hide_full").checked = filters.hide_full
    document.getElementById("is_understaffed").checked = filters.hide_staffed
    document.getElementById("colourful_mode").checked = filters.colourful_mode
    updateRowDisplay();
}

function getFilters() {
    let filters = {
        "role_ids": Array.from(document.querySelectorAll('input[data-role-id]:checked')).map(node => node.getAttribute('data-role-id')),
        "show_finished_shifts": document.getElementById("show_past").checked,
        "signed_up": document.getElementById("show_signed_up_only").checked,
        "hide_full": document.getElementById("hide_full").checked,
        "hide_staffed": document.getElementById("is_understaffed").checked,
        "colourful_mode": document.getElementById("colourful_mode").checked,
    }
    return filters
}

function getNodeData(node) {
    return {
        "start": node.getAttribute("data-shift-start"),
        "end": node.getAttribute("data-shift-end"),
        "role_id": node.getAttribute("data-role-id"),
        "staffed": node.getAttribute("data-staffed") == "True",
        "signed_up": node.getAttribute("data-signed-up") == "True",
        "full": node.getAttribute("data-full") == "True",
        "min_staff": parseInt(node.getAttribute("data-min-staff")),
        "max_staff": parseInt(node.getAttribute("data-max-staff")),
        "current_staff": parseInt(node.getAttribute("data-current-staff")),
    }
}

function shouldDisplayNode(node_data, filters) {
    // Yes, there are more efficient ways, but this makes debugging why
    // a row was filtered easier.
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
    if (filters["signed_up"] && !node_data["signed_up"]) {
        filter_reasons.push("signed_up");
    }
    return filter_reasons.length === 0;
}


function spanStartTimeCell(firstNodeOfHour, rowCount) {
    if (firstNodeOfHour !== null) {
        firstNodeOfHour.children[0].setAttribute("rowspan", rowCount);
        $(firstNodeOfHour.children[0]).show();
    }
}

function rowClass(node_data) {
    if (node_data.current_staff < node_data.min_staff) {
        return 'danger';
    }

    if (node_data.current_staff == node_data.max_staff) {
        return 'info';
    }

    return 'warning';
}

function updateRowDisplay() {
    let filters = getFilters();

    // Hackery to do row spans.
    let currentHour = "null";
    let firstNodeOfHour = null;
    let rowCount = 0;

    // Iterate over each row (representing a shift), and choose which ones to
    // display.
    var rows = document.querySelectorAll("table.shifts-table tbody tr");
    rows.forEach((node, idx) => {
        let node_data = getNodeData(node);

        if (shouldDisplayNode(node_data, filters)) {
            if (node.getAttribute("data-shift-start") != currentHour) {
                // When we transition to a new hour we calculate how many rows
                // are shown for that hour, and span the first start time cell
                // over all of them.
                spanStartTimeCell(firstNodeOfHour, rowCount)

                firstNodeOfHour = node
                rowCount = 0
                currentHour = node.getAttribute("data-shift-start")
            } else {
                // Otherwise we hide the start time cell. q
                $(node.children[0]).hide()
            }

            node.classList.remove("danger")
            node.classList.remove("warning")
            node.classList.remove("info")

            if (filters.colourful_mode) {
                node.classList.add(rowClass(node_data))
            }

            rowCount += 1;

            $(node).show();
        } else {
            $(node).hide();
        }

        if (idx == rows.length - 1) { spanStartTimeCell(firstNodeOfHour, rowCount); }
    });
}

function init_volunteer_schedule() {
    loadFilters();
    document.getElementById('filters').style.display = "";
    document.getElementById('filters-toggle').addEventListener("click", () => {
        $('#filters-body').toggle()
    });

    ['show_past', 'show_signed_up_only', 'hide_full', 'is_understaffed', 'colourful_mode'].forEach(id => {
        document.getElementById(id).addEventListener("change", () => {
            saveFilters()
            updateRowDisplay()
        });
    });

    document.querySelectorAll('input[data-role-id]').forEach(node => node.addEventListener("change", () => {
        saveFilters()
        updateRowDisplay()
    }));

    document.getElementById('select-all-roles').addEventListener("click", () => {
        document.querySelectorAll('input[data-role-id]').forEach((checkbox) => checkbox.checked = true)
        saveFilters()
        updateRowDisplay()
    });
    document.getElementById('select-no-roles').addEventListener("click", () => {
        document.querySelectorAll('input[data-role-id]').forEach((checkbox) => checkbox.checked = false)
        saveFilters()
        updateRowDisplay()
    });
    document.getElementById('select-interested-roles').addEventListener("click", () => {
        document.querySelectorAll('input[data-role-id]').forEach((checkbox) => checkbox.checked = checkbox.getAttribute('data-interested') == 'True')
        saveFilters()
        updateRowDisplay()
    });
    document.getElementById('select-trained-roles').addEventListener("click", () => {
        document.querySelectorAll('input[data-role-id]').forEach((checkbox) => checkbox.checked = checkbox.getAttribute('data-trained') == 'True')
        saveFilters()
        updateRowDisplay()
    });
};

init_volunteer_schedule()
