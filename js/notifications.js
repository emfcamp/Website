function setState(state) {
    document.querySelectorAll("#notification-state .state").forEach(el => el.classList.remove("visible"));
    document.getElementById(`notification-error`).classList.remove("visible");
    document.getElementById(`notification-state-${state}`).classList.add("visible");
}

function setError(message) {
    let error = document.getElementById(`notification-error`);
    error.innerText = message;
    error.classList.add("visible");
}

async function enableNotifications(event) {
    let vapid_key = document.querySelector("meta[name=vapid_key]").getAttribute("value");
    let worker = await navigator.serviceWorker.ready;
    let result = await worker.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: vapid_key,
    });

    let response = await fetch("/account/notifications/register", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(result.toJSON())
    });

    if (response.status == 200) {
        setState("granted")
    } else {
        setError("There was a problem enabling push notifications. Please try again shortly.")
    }
}

async function checkPermissions() {
    let worker = await navigator.serviceWorker.ready;

    if ("pushManager" in worker) {
        let permissions = await worker.pushManager.permissionState({
            userVisibleOnly: true,
        });
        setState(permissions);
    } else {
        setState("unsupported");
    }
}

if ("serviceWorker" in navigator) {
    checkPermissions();
    document.getElementById("enable-notifications").addEventListener("click", enableNotifications);
}
