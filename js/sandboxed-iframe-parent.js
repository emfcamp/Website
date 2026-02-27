/*
 * A dynamic iFrame sizing system in 2 parts.
 *
 * The parent (i.e. the page containing the iFrame element) should include this js.
 * Any iFrame element is then elibigible for resizing if its child emits the correct event (via including the -child js.)
 */

function listenForFrameResizedMessages() {
    window.addEventListener("message", receiveMessage, false);

    function receiveMessage(evt) {
        // console.log("Got message: " + JSON.stringify(evt.data) + " from origin: " + evt.origin);// + " and source: " + evt.source);
        if (evt.data.type !== "frame-resized") {
            //not our event
            return;
        }
        // NB. can't check the origin as for sandboxed iframes it is null

        const iFrames = document.getElementsByTagName("iFrame");
        for (const iFrameEle of iFrames) {
            if (iFrameEle.contentWindow == evt.source) {
                iFrameEle.style.height = evt.data.value + "px";
            }
        }
    }
}

listenForFrameResizedMessages();
