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
}

async function checkPermissions() {
    let worker = await navigator.serviceWorker.ready;

    if ("pushManager" in worker) {
        let permissions = await worker.pushManager.permissionState({
            userVisibleOnly: true,
        });
        document.getElementById(`notification-state-${permissions}`).classList.add('visible')
    } else {
        document.getElementById(`notification-state-unsupported`).classList.add('visible');
        console.log("No push notification support.");
    }
}

if ("serviceWorker" in navigator) {
    checkPermissions();
    document.getElementById("enable-notifications").addEventListener("click", enableNotifications);
}
