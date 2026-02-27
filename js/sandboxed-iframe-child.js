/*
 * A dynamic iFrame sizing system in 2 parts.
 *
 * The child (i.e. the page inside the iFrame) should include this js.
 * It will then emit an event for it's parent to resize.
 */

function sendMsg(height) {
    window.parent.postMessage(
        {
            type: "frame-resized",
            value: height,
        },
        "*",
    );
}

function registerFrameResizeObserver() {
    const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
            sendMsg(entry.target.scrollHeight);
        }
    });
    resizeObserver.observe(document.body);
    //send initial event
    sendMsg(document.body.scrollHeight);
}

registerFrameResizeObserver();
