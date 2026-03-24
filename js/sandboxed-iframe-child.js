/*
 * A dynamic iFrame sizing system in 2 parts.
 *
 * The child (i.e. the page inside the iFrame) should include this js.
 * It will then emit an event for it's parent to resize.
 */

let lastHeight = null;

function sendHeight() {
    const height = document.body.scrollHeight;
    if (height == lastHeight) return;
    lastHeight = height;

    // console.log(`Sending new height ${height} to parent`);
    window.parent.postMessage(
        {
            type: "frame-resized",
            height: height,
        },
        "*",
    );
}

function registerFrameResizeObserver() {
    const resizeObserver = new ResizeObserver(sendHeight);
    resizeObserver.observe(document.body);
    // send initial event
    sendHeight();
}

document.body.style.overflow = "hidden";
registerFrameResizeObserver();
