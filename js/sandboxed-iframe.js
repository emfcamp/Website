function sendFrameResizedMessage() {
    //postMessage to set iframe height
    window.parent.postMessage({ "type": "frame-resized", "value": document.body.parentElement.scrollHeight }, '*');
}

function listenForFrameResizedMessages(iFrameEle) {
    window.addEventListener('message', receiveMessage, false);

    function receiveMessage(evt) {
        console.log("Got message: " + JSON.stringify(evt.data) + " from origin: " + evt.origin);
        // Do we trust the sender of this message?
        // origin of sandboxed iframes is null but is this a useful check?
        // if (evt.origin !== null) {
        //     return;
        // }

        if (evt.data.type === "frame-resized") {
            iFrameEle.style.height = evt.data.value + "px";
        }
    }
}

window.listenForFrameResizedMessages = listenForFrameResizedMessages;
window.sendFrameResizedMessage = sendFrameResizedMessage;