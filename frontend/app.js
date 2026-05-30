/**
 * KnitX-ultra HMI Core Controller
 * Redesigned to map Figma v4 specifications exactly.
 */

// ─────────────────────────────────────────────────────────────────────────────
// BACKEND URL CONFIG — Change this to your Raspberry Pi's IP address
// Example: const BACKEND_URL = "http://10.111.217.38:5000";
// To find your Pi's IP: run  hostname -I  in the Pi terminal
// ─────────────────────────────────────────────────────────────────────────────
const BACKEND_URL = "http://localhost:5000";


// Global state variables matching the Figma prototype state structure
let isRunning = false;
let isPaused = false;
let sessionTime = 0; // Elapsed inspection time in seconds
let elapsedTimerInterval = null;

let RollId = "";
let BatchId = "";
let Operator = "";

// HMI Integration Bridge State
let useBackendBridge = false;
let bridgeStatusInterval = null;
const bridgeImg = new Image();
bridgeImg.src = `${BACKEND_URL}/video_feed`;

let totalDefects = 0;
let totalPenaltyPoints = 0;
let holeCount = 0;
let needleLineCount = 0;
let qualityScore = 100.0; // Math.max(0, Math.min(100, 100 - (totalPenaltyPoints / 40 * 100)))

// Log Arrays
let defectLogs = [];
let trendData = [{ time: "0m", holes: 0, needleLines: 0, id: "0" }];

// Canvas Scrolling feed variables
const canvas = document.getElementById('live-canvas');
const ctx = canvas.getContext('2d');
let scrollOffset = 0;
let activeDefectsInFeed = [];
let scanlineY = 0;
let scanlineDirection = 1;
let currentFps = 60.0;
let currentInferenceLatency = 0.0;
let lastAutoSpawnTime = 0;
let lastUploadTime = 0;

let webcamVideo = null;

// Mock Google Drive & SQLite DB States
let isGDriveConnected = false;
let gdriveUserEmail = "operator.alpha@knitx-ultra.com";
let uploadQueue = [];
let localCacheCount = 0;

// Audio synthesis context
let audioCtx = null;
let soundAlarmEnabled = true;

// Tab Navigation state
let activeTab = "home";

// RPi 5 CPU & Temperature History
let tempHistory = Array(15).fill(35.0);

// Alerts System History & Unread Notifications
let alertsHistory = [
    { time: new Date().toLocaleTimeString(), title: "SYSTEM BOOT ONLINE", desc: "YOLO26n ONNX Inference Framework and CSI-2 Camera Module 3 wide interface initialized.", type: "system" }
];
let alertsUnacknowledgedCount = 0;

// ==========================================================================
// 1. INITIALIZATION & LAYOUT CONFIG
// ==========================================================================
window.addEventListener('DOMContentLoaded', () => {
    initSystemClock();
    resizeCanvas();
    window.addEventListener('resize', () => {
        resizeCanvas();
        renderSvgTrendChart();
    });

    // Set default HMI header displays to unconfigured until session login
    document.getElementById('active-roll-id').innerText = "NOT RUNNING";
    document.getElementById('active-batch-id').innerText = "UNCONFIGURED";
    document.getElementById('operator-name').innerText = "LOG IN REQUIRED";

    // Vertical Control Bar Listeners
    document.getElementById('btn-start').addEventListener('click', onStartInspection);
    document.getElementById('btn-stop').addEventListener('click', onStopInspection);
    document.getElementById('btn-pause').addEventListener('click', onPauseInspection);
    document.getElementById('btn-reset').addEventListener('click', onReset);
    document.getElementById('btn-capture').addEventListener('click', onCapture);
    document.getElementById('btn-save').addEventListener('click', onSave);

    // Settings Modal & Extra Actions
    document.getElementById('btn-gdrive-login').addEventListener('click', handleGoogleDriveAuth);
    document.getElementById('btn-sound-alarm').addEventListener('click', toggleAcousticAlarm);
    document.getElementById('btn-clear-sqlite').addEventListener('click', clearSQLiteHistory);
    document.getElementById('btn-download-pdf').addEventListener('click', downloadPdfReport);

    // Initial SVG render
    renderSvgTrendChart();
    
    // Initialize tactile resizable dividers
    initResizers();
    
    // Begin continuous canvas loop
    requestAnimationFrame(canvasConveyorLoop);
    
    // Periodically update diagnostics
    updateHardwareFluctuations();
    setInterval(updateHardwareFluctuations, 1000);

    // Initial status beacons display (all offline/red)
    updateBeaconsState();

    // Start auto-detecting the local Python YOLO AI bridge (runs once after 3s)
    setTimeout(detectBackendBridge, 3000);
});

function detectBackendBridge() {
    fetch(`${BACKEND_URL}/api/status`)
        .then(res => res.json())
        .then(data => {
            if (!useBackendBridge) {
                useBackendBridge = true;
                logToCloudConsole("[SYSTEM] Edge-AI bridge detected at ${BACKEND_URL}. Synchronizing YOLO/RPi sensors.");
                pushAlert("EDGE-AI ONLINE", "Linked with local Python camera capture and YOLO inspection runtime.", "success");
                
                // Swap buttons class visual to match backend initial config state
                syncHmiWithBackendState(data);
                
                // Start status polling
                startBackendPolling();
            }
        })
        .catch(err => {
            if (useBackendBridge) {
                useBackendBridge = false;
                logToCloudConsole("[WARNING] Edge-AI bridge disconnected. Switched back to standalone simulated feed.");
                pushAlert("EDGE-AI OFFLINE", "Python inspection runtime disconnected. Standalone mode active.", "alarm");
                
                // Clear polling
                if (bridgeStatusInterval) {
                    clearInterval(bridgeStatusInterval);
                    bridgeStatusInterval = null;
                }
            }
        });
}

function startBackendPolling() {
    if (bridgeStatusInterval) clearInterval(bridgeStatusInterval);
    
    bridgeStatusInterval = setInterval(() => {
        if (!useBackendBridge) return;
        
        // 1. Fetch Status
        fetch(`${BACKEND_URL}/api/status`)
            .then(res => res.json())
            .then(data => {
                // Update HMI global state variables
                isRunning = data.isRunning;
                isPaused = data.isPaused;
                isGDriveConnected = data.gdriveConnected;
                
                // Session details
                RollId = data.rollId;
                BatchId = data.batchId;
                Operator = data.operator;
                sessionTime = data.sessionTime;
                totalDefects = data.totalDefects;
                totalPenaltyPoints = data.totalPoints;
                holeCount = data.holeCount;
                needleLineCount = data.needleLineCount;
                qualityScore = data.qualityScore;
                
                // Update UI text fields
                document.getElementById('active-roll-id').innerText = RollId;
                document.getElementById('active-batch-id').innerText = BatchId;
                document.getElementById('operator-name').innerText = Operator;
                updateTimerDisplay();
                
                // Conveyor yardage
                const yds = (sessionTime * 0.25).toFixed(1);
                document.getElementById('conveyor-yardage').innerText = `${yds} YD`;
                
                // Analytics, Report tabs
                refreshHmiMetrics();
                updateBeaconsState();
                
                // Hardware diagnostics
                const cpuLoad = data.cpuLoad;
                const cpuTemp = data.cpuTemp;
                currentInferenceLatency = data.inferenceLatency;
                
                const latencyEl = document.getElementById('inf-latency');
                if (latencyEl) latencyEl.innerText = `${currentInferenceLatency.toFixed(1)} ms`;
                
                const cpuValEl = document.getElementById('pb-cpu-val');
                const cpuBarEl = document.getElementById('pb-cpu-bar');
                const tempValEl = document.getElementById('pb-temp-val');
                const tempBarEl = document.getElementById('pb-temp-bar');

                if (cpuValEl) cpuValEl.innerText = `${cpuLoad}%`;
                if (cpuBarEl) cpuBarEl.style.width = `${cpuLoad}%`;
                if (tempValEl) tempValEl.innerText = `${cpuTemp.toFixed(1)} °C`;
                if (tempBarEl) {
                    tempBarEl.style.width = `${cpuTemp}%`;
                    tempBarEl.className = "h-full bg-green-500 transition-all duration-300";
                }

                // Maintain temp history for sparkline
                tempHistory.push(cpuTemp);
                if (tempHistory.length > 15) tempHistory.shift();
                if (activeTab === 'analytics') {
                    drawHardwareSparkline();
                }


                // Sync button visual classes
                syncHmiWithBackendState(data);
            })
            .catch(err => {
                console.error("Status polling failed", err);
            });

        // 2. Fetch Defects
        fetch(`${BACKEND_URL}/api/defects`)
            .then(res => res.json())
            .then(data => {
                // If a new defect is registered
                if (data.length > defectLogs.length) {
                    const newDefect = data[data.length - 1];
                    playHarshAcousticAlarm(newDefect.points);
                    pushAlert("DEFECT DETECTED", `AI target '${newDefect.type}' detected (${newDefect.size.toFixed(1)}mm) adding ${newDefect.points} ASTM points.`, "defect");
                }
                
                defectLogs = data;
                refreshDefectTableLogs();
                // Map to summary matrix
                const tbody = document.getElementById('summary-matrix-body');
                if (tbody) {
                    tbody.innerHTML = defectLogs.map((log, idx) => {
                        return `
                            <tr class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                                <td class="py-1 px-2 text-gray-300 text-xs">${idx + 1}</td>
                                <td class="py-1 px-2 text-center text-xs">${log.type === 'Hole' ? '🔴' : '-'}</td>
                                <td class="py-1 px-2 text-center text-xs">${log.type !== 'Hole' ? '🟡' : '-'}</td>
                                <td class="py-1 px-2 text-center text-xs text-white font-semibold">${log.points}</td>
                            </tr>`;
                    }).join('');
                }
            })
            .catch(err => {
                console.error("Defect polling failed", err);
            });
    }, 400);
}

function unlockHmiControlButtons() {
    const startBtn = document.getElementById('btn-start');
    if (startBtn) {
        startBtn.removeAttribute('disabled');
        startBtn.className = "w-14 h-14 rounded-lg bg-green-600 hover:bg-green-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    }
    const resetBtn = document.getElementById('btn-reset');
    if (resetBtn) {
        resetBtn.removeAttribute('disabled');
        resetBtn.className = "w-14 h-14 rounded-lg bg-gray-600 hover:bg-gray-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    }
    const saveBtn = document.getElementById('btn-save');
    if (saveBtn) {
        saveBtn.removeAttribute('disabled');
        saveBtn.className = "w-14 h-14 rounded-lg bg-blue-600 hover:bg-blue-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    }
}

function lockHmiControlButtons() {
    const startBtn = document.getElementById('btn-start');
    if (startBtn) {
        startBtn.setAttribute('disabled', 'true');
        startBtn.className = "w-14 h-14 rounded-lg bg-green-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
    }
    const resetBtn = document.getElementById('btn-reset');
    if (resetBtn) {
        resetBtn.setAttribute('disabled', 'true');
        resetBtn.className = "w-14 h-14 rounded-lg bg-gray-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
    }
    const saveBtn = document.getElementById('btn-save');
    if (saveBtn) {
        saveBtn.setAttribute('disabled', 'true');
        saveBtn.className = "w-14 h-14 rounded-lg bg-blue-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
    }
}

function syncHmiWithBackendState(data) {
    if (data.isRunning && !data.isPaused) {
        document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg scale-95 border-2 border-white";
        document.getElementById('btn-stop').className = "w-14 h-14 rounded-lg bg-red-600 hover:bg-red-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
        document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 hover:bg-yellow-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
        document.getElementById('btn-capture').className = "w-14 h-14 rounded-lg bg-purple-600 hover:bg-purple-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
        
        document.getElementById('btn-stop').removeAttribute('disabled');
        document.getElementById('btn-pause').removeAttribute('disabled');
        document.getElementById('btn-capture').removeAttribute('disabled');
        document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-red-600 px-3 py-1 rounded-full animate-pulse";
    } else if (data.isPaused) {
        document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 hover:bg-green-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
        document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 hover:bg-yellow-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg scale-95 border-2 border-white";
        document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-gray-800 px-3 py-1 rounded-full";
    } else {
        document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 hover:bg-green-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
        document.getElementById('btn-stop').className = "w-14 h-14 rounded-lg bg-red-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
        document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
        document.getElementById('btn-capture').className = "w-14 h-14 rounded-lg bg-purple-600 hover:bg-purple-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
        
        document.getElementById('btn-stop').setAttribute('disabled', 'true');
        document.getElementById('btn-pause').setAttribute('disabled', 'true');
        document.getElementById('btn-capture').setAttribute('disabled', 'true');
        document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-gray-800 px-3 py-1 rounded-full";
    }
}

// ─── Login credentials (username → password) ───────────────────────────────
const KNITX_USERS = {
    "admin":    "admin123",
    "operator": "knitx2024",
    "manager":  "manage456"
};

window.submitLogin = function() {
    try {
        const usernameEl = document.getElementById('input-username');
        const passwordEl = document.getElementById('input-password');
        const errorEl   = document.getElementById('login-error');

        if (!usernameEl || !passwordEl) {
            alert('Login form elements not found. Please hard-refresh the page (Ctrl+Shift+R).');
            return;
        }

        const username = usernameEl.value.trim();
        const password = passwordEl.value.trim();

        if (!username || !password) {
            if (errorEl) {
                errorEl.classList.remove('hidden');
                errorEl.textContent = '⚠️ Please enter both username and password.';
            }
            return;
        }

        if (KNITX_USERS[username] && KNITX_USERS[username] === password) {
            if (errorEl) errorEl.classList.add('hidden');

            const operatorDisplay = username.charAt(0).toUpperCase() + username.slice(1);
            window._loggedInOperator = operatorDisplay;

            // Close login modal immediately
            const loginModal = document.getElementById('session-init-modal');
            if (loginModal) loginModal.classList.add('hidden');

            // Update operator name in header
            const headerOp = document.getElementById('operator-name');
            if (headerOp) headerOp.innerText = operatorDisplay;

            // Update operator name in inspection setup modal
            const dispOp = document.getElementById('display-operator');
            if (dispOp) dispOp.innerText = operatorDisplay;

            // Unlock Start button
            const btnStart = document.getElementById('btn-start');
            if (btnStart) {
                btnStart.removeAttribute('disabled');
                btnStart.classList.remove('opacity-40', 'cursor-not-allowed');
                btnStart.classList.add('hover:bg-green-500', 'hover:scale-105');
            }

            // Safe alert push
            try { pushAlert('LOGGED IN', `Welcome ${operatorDisplay}. Click ▶ Start to begin an inspection session.`, 'system'); } catch(e) {}

        } else {
            if (errorEl) {
                errorEl.classList.remove('hidden');
                errorEl.textContent = '❌ Invalid username or password.';
            }
            passwordEl.value = '';
            passwordEl.focus();
        }
    } catch(err) {
        alert('Login error: ' + err.message);
    }
};

window.openInspectionSetup = function() {
    if (isRunning || isPaused || RollId !== "") {
        onStartInspection();
        return;
    }
    const modal = document.getElementById('inspection-setup-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.style.display = 'flex';
    }
};

window.closeInspectionSetup = function() {
    const modal = document.getElementById('inspection-setup-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.style.display = 'none';
    }
};

window.submitSessionInit = function() {
    const inputOperator = window._loggedInOperator || 'Operator';
    const inputRollId = document.getElementById('input-roll-id').value.trim();
    const inputBatchId = document.getElementById('input-batch-id').value.trim();
    const inputGsm = parseFloat(document.getElementById('input-gsm').value);
    const inputRollWeight = parseFloat(document.getElementById('input-roll-weight').value);

    if (!inputOperator || !inputRollId || !inputBatchId) {
        alert("Please enter Operator Name, Roll ID, and Batch ID to configure system session!");
        return;
    }
    if (isNaN(inputGsm) || inputGsm <= 0) {
        alert("Please enter a valid Fabric GSM value (e.g. 202.0)!");
        return;
    }
    if (isNaN(inputRollWeight) || inputRollWeight <= 0) {
        alert("Please enter a valid Roll Weight in kg (e.g. 110.8)!");
        return;
    }

    if (useBackendBridge) {
        // Send config POST to Python server
        fetch(`${BACKEND_URL}/api/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                operator: inputOperator,
                roll_id: inputRollId,
                batch_id: inputBatchId,
                gsm: inputGsm,
                roll_weight_kg: inputRollWeight
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === "success") {
                // Update global state
                Operator = inputOperator;
                RollId = inputRollId;
                BatchId = inputBatchId;

                // Update header labels
                document.getElementById('active-roll-id').innerText = RollId;
                document.getElementById('active-batch-id').innerText = BatchId;
                document.getElementById('operator-name').innerText = Operator;

                // Update Report page labels
                const rRoll = document.getElementById('report-page-roll');
                const rBatch = document.getElementById('report-page-batch');
                if (rRoll) rRoll.innerText = RollId;
                if (rBatch) rBatch.innerText = BatchId;

                // Push system alert
                pushAlert("SESSION CONFIGURED", `Operator: ${Operator} | Roll: ${RollId} | Batch: ${BatchId} | GSM: ${inputGsm} | Weight: ${inputRollWeight}kg`, "system");

                // Log to cloud console
                logToCloudConsole(`[SYSTEM] Session configured — Operator: ${inputOperator}, Roll: ${inputRollId}, GSM: ${inputGsm}, Weight: ${inputRollWeight}kg.`);

                // Unlock HMI buttons
                unlockHmiControlButtons();
                updateBeaconsState();

                // Close the inspection setup modal after successful submit
                closeInspectionSetup();
                
                // Automatically start the inspection scroller/feed
                onStartInspection();
            } else {
                alert("Failed to configure edge session: " + data.message);
            }
        })
        .catch(err => {
            console.error("Config post failed", err);
            alert("Could not reach backend server. Please make sure the backend is running on port 5000.");
        });
    } else {
        // Set globals
        Operator = inputOperator;
        RollId = inputRollId;
        BatchId = inputBatchId;

        // Update Header labels
        document.getElementById('active-roll-id').innerText = RollId;
        document.getElementById('active-batch-id').innerText = BatchId;
        document.getElementById('operator-name').innerText = Operator;

        // Update Report page labels
        const rRoll = document.getElementById('report-page-roll');
        const rBatch = document.getElementById('report-page-batch');
        if (rRoll) rRoll.innerText = RollId;
        if (rBatch) rBatch.innerText = BatchId;

        // Push successful system session initialization alert log
        pushAlert("SESSION CONFIGURED", `Operator logged in: ${Operator}. Loaded Roll ${RollId} inside Batch ${BatchId}. System indicators activated.`, "system");

        // Unlock operation sidebar buttons
        unlockHmiControlButtons();

        // Update status indicators
        updateBeaconsState();

        // Close the inspection setup modal after successful submit
        closeInspectionSetup();

        // Automatically start the inspection scroller/feed
        onStartInspection();
    }
};

function initSystemClock() {
    setInterval(() => {
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const secs = String(now.getSeconds()).padStart(2, '0');
        
        const yr = now.getFullYear();
        const mo = String(now.getMonth() + 1).padStart(2, '0');
        const dy = String(now.getDate()).padStart(2, '0');

        document.getElementById('hmi-clock-date').innerText = `${hrs}:${mins}:${secs} • ${yr}-${mo}-${dy}`;
    }, 1000);
}

function resizeCanvas() {
    const parent = canvas.parentElement;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
}

// ==========================================================================
// 2. FIGMA SIMULATOR OPERATION TRIGGERS (Pe Sidebar Component)
// ==========================================================================
function onStartInspection() {
    if (useBackendBridge) {
        fetch(`${BACKEND_URL}/api/control`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "start" })
        });
        
        // Request device camera/webcam permission to feed frames to local backend AI
        startWebcamCapture();
        
        return;
    }
    if (isRunning && !isPaused) return;

    isRunning = true;
    isPaused = false;
    
    // Toggle active classes on left side controls (Pe)
    document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg scale-95 border-2 border-white";
    document.getElementById('btn-stop').className = "w-14 h-14 rounded-lg bg-red-600 hover:bg-red-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 hover:bg-yellow-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    document.getElementById('btn-capture').className = "w-14 h-14 rounded-lg bg-purple-600 hover:bg-purple-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    
    document.getElementById('btn-stop').removeAttribute('disabled');
    document.getElementById('btn-pause').removeAttribute('disabled');
    document.getElementById('btn-capture').removeAttribute('disabled');

    // Pulsing live badge indicator
    document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-red-600 px-3 py-1 rounded-full animate-pulse";

    // Start elapsed timer
    if (!elapsedTimerInterval) {
        elapsedTimerInterval = setInterval(() => {
            if (isRunning && !isPaused) {
                sessionTime++;
                updateTimerDisplay();
                
                // Conveyor distance accumulation (e.g. Speed 15 Y/M -> 0.25 Yards per second)
                const yds = (sessionTime * 0.25).toFixed(1);
                document.getElementById('conveyor-yardage').innerText = `${yds} YD`;

                // Update trend chart time scale intervals
                if (sessionTime % 60 === 0) {
                    const elapsedMin = Math.floor(sessionTime / 60);
                    trendData.push({
                        time: `${elapsedMin}m`,
                        holes: 0,
                        needleLines: 0,
                        id: `min-${elapsedMin}`
                    });
                    if (trendData.length > 10) trendData.shift();
                    renderSvgTrendChart();
                }


            }
        }, 1000);
    }
    
    logToCloudConsole("[PIPELINE] Edge fabric inspection loops online. Bounding pipeline active.");
    pushAlert("INSPECTION STARTED", "Fabric conveyor running at 15 Y/M. YOLOv8 object detection live.", "system");
    
    // Request device camera/webcam permission and capture feed
    startWebcamCapture();
    
    updateBeaconsState();
}

function startWebcamCapture() {
    if (webcamVideo) return; // already active
    navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } })
        .then(stream => {
            webcamVideo = document.createElement('video');
            webcamVideo.srcObject = stream;
            webcamVideo.autoplay = true;
            webcamVideo.playsInline = true;
            logToCloudConsole("[HARDWARE] Device webcam access granted. Live physical feed mapped to Canvas HMI.");
            pushAlert("CAMERA ONLINE", "Webcam feed connected. Realtime optical preprocessing active.", "success");
        })
        .catch(err => {
            console.warn("Webcam access denied or unavailable:", err);
            logToCloudConsole("[WARNING] Device webcam unavailable. Using simulated slate belt feed.");
        });
}

function stopWebcamCapture() {
    if (webcamVideo && webcamVideo.srcObject) {
        try {
            webcamVideo.srcObject.getTracks().forEach(track => track.stop());
        } catch(e) {}
        webcamVideo = null;
        logToCloudConsole("[HARDWARE] Webcam capture stream offline.");
    }
}

const tempCanvas = document.createElement('canvas');
const tempCtx = tempCanvas.getContext('2d');
let isUploadingFrame = false;

function postWebcamFrameToBackend() {
    if (!webcamVideo || webcamVideo.readyState < 2 || !isRunning || isPaused || !useBackendBridge) return;
    if (isUploadingFrame) return; // prevent parallel overlapping uploads
    isUploadingFrame = true;

    tempCanvas.width = 640;
    tempCanvas.height = 480;
    tempCtx.drawImage(webcamVideo, 0, 0, 640, 480);

    tempCanvas.toBlob(blob => {
        if (!blob) {
            isUploadingFrame = false;
            return;
        }

        fetch(`${BACKEND_URL}/api/process_frame`, {
            method: 'POST',
            headers: { 'Content-Type': 'image/jpeg' },
            body: blob
        })
        .then(res => {
            isUploadingFrame = false;
            if (res.status !== 200) {
                console.warn("Backend process_frame returned non-200");
            }
        })
        .catch(err => {
            isUploadingFrame = false;
            console.error("Failed to upload frame to backend:", err);
        });
    }, 'image/jpeg', 0.6); // 60% quality is very lightweight and perfect for Edge-AI YOLO re-scaling!
}

function onPauseInspection() {
    if (useBackendBridge) {
        fetch(`${BACKEND_URL}/api/control`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "pause" })
        });
        return;
    }
    if (!isRunning || isPaused) return;

    isPaused = true;
    
    // Toggle active visual states
    document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 hover:bg-green-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 hover:bg-yellow-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg scale-95 border-2 border-white";
    
    // De-pulse LIVE badge
    document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-gray-800 px-3 py-1 rounded-full";
    logToCloudConsole("[PIPELINE] Machine conveyor belt paused. OpenCV feeds passive.");
    pushAlert("INSPECTION PAUSED", "Operator John Doe paused the inspection. Conveyor halted.", "system");
    updateBeaconsState();
}

function onStopInspection() {
    if (useBackendBridge) {
        fetch(`${BACKEND_URL}/api/control`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "stop" })
        });
        return;
    }
    if (!isRunning) return;

    isRunning = false;
    isPaused = false;

    // Reset controls button disabled triggers
    document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 hover:bg-green-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
    document.getElementById('btn-stop').className = "w-14 h-14 rounded-lg bg-red-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
    document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
    document.getElementById('btn-capture').className = "w-14 h-14 rounded-lg bg-purple-600 hover:bg-purple-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";

    document.getElementById('btn-stop').setAttribute('disabled', 'true');
    document.getElementById('btn-pause').setAttribute('disabled', 'true');
    document.getElementById('btn-capture').setAttribute('disabled', 'true');

    document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-gray-800 px-3 py-1 rounded-full";

    // Pause time counters
    if (elapsedTimerInterval) {
        clearInterval(elapsedTimerInterval);
        elapsedTimerInterval = null;
    }

    logToCloudConsole(`[PIPELINE] Inspection completed for ${RollId}. Reports saved locally.`);
    pushAlert("INSPECTION COMPLETED", `Inspection stopped. Total Defects: ${totalDefects}, Penalty Points: ${totalPenaltyPoints}.`, "success");
    
    // Release device camera/webcam stream
    stopWebcamCapture();
    
    updateBeaconsState();
}

function onReset() {
    if (useBackendBridge) {
        if (confirm("Reset current fabric roll inspection data? Analytics history will be wiped.")) {
            fetch(`${BACKEND_URL}/api/control`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "reset" })
            });
        }
        return;
    }
    if (confirm("Reset current fabric roll inspection data? Analytics history will be wiped.")) {
        isRunning = false;
        isPaused = false;
        sessionTime = 0;
        
        if (elapsedTimerInterval) {
            clearInterval(elapsedTimerInterval);
            elapsedTimerInterval = null;
        }

        totalDefects = 0;
        totalPenaltyPoints = 0;
        holeCount = 0;
        needleLineCount = 0;
        qualityScore = 100.0;
        
        defectLogs = [];
        activeDefectsInFeed = [];
        trendData = [{ time: "0m", holes: 0, needleLines: 0, id: "0" }];
        lastAutoSpawnTime = 0;

        // Clear absolute DOM bounding boxes
        document.getElementById('live-bounding-boxes-container').innerHTML = '';

        // Reset sidebar button triggers
        document.getElementById('btn-start').className = "w-14 h-14 rounded-lg bg-green-600 hover:bg-green-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg hover:shadow-xl hover:scale-105";
        document.getElementById('btn-stop').className = "w-14 h-14 rounded-lg bg-red-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
        document.getElementById('btn-pause').className = "w-14 h-14 rounded-lg bg-yellow-600 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
        document.getElementById('btn-capture').className = "w-14 h-14 rounded-lg bg-purple-600 hover:bg-purple-500 flex flex-col items-center justify-center gap-1 transition-all shadow-lg opacity-40 cursor-not-allowed";
        document.getElementById('btn-stop').setAttribute('disabled', 'true');
        document.getElementById('btn-pause').setAttribute('disabled', 'true');
        document.getElementById('btn-capture').setAttribute('disabled', 'true');
        
        document.getElementById('live-indicator-beacon').className = "flex items-center gap-2 bg-gray-800 px-3 py-1 rounded-full";

        // Reset HTML texts
        updateTimerDisplay();
        document.getElementById('conveyor-yardage').innerText = "0.0 YD";
        refreshHmiMetrics();
        refreshDefectTableLogs();
        refreshActiveDefectsList();
        renderSvgTrendChart();
        updateQrReportCode();

        logToCloudConsole("[SYSTEM] active session metrics and log charts reset.");
        pushAlert("INSPECTION RESET", "All current fabric roll metrics and logs have been wiped.", "alarm");
        
        // Release device camera/webcam stream
        stopWebcamCapture();
        
        updateBeaconsState();
    }
}

function onCapture() {
    logToCloudConsole("[HARDWARE] Camera CSI-2 frame snap trigger capture command sent.");
    alert("Frame snapshot captured successfully!\nSaved to edge storage path: /KnitX/snapshots/");
}

function onSave() {
    if (useBackendBridge) {
        fetch(`${BACKEND_URL}/api/control`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "save" })
        });
    }
    // Generate JSON report Blob exactly mapping Figma specifications
    const reportPayload = {
        rollId: RollId,
        batchId: BatchId,
        operator: Operator,
        sessionTime: sessionTime,
        totalDefects: totalDefects,
        totalPoints: totalPenaltyPoints,
        holeCount: holeCount,
        needleLineCount: needleLineCount,
        qualityScore: qualityScore.toFixed(1),
        defectLogs: defectLogs,
        timestamp: new Date().toISOString()
    };

    const u = new Blob([JSON.stringify(reportPayload, null, 2)], { type: "application/json" });
    const S = URL.createObjectURL(u);
    const m = document.createElement("a");
    m.href = S;
    m.download = `knitx-inspection-report-${RollId}.json`;
    document.body.appendChild(m);
    m.click();
    document.body.removeChild(m);
    URL.revokeObjectURL(S);

    logToCloudConsole(`[SYSTEM] Defect logs packed. JSON summary report downloaded: knitx-inspection-report-${RollId}.json`);
    
    if (isGDriveConnected) {
        uploadQueue.push(reportPayload);
        processGoogleDriveUploadQueue();
    }
}

function downloadPdfReport() {
    if (useBackendBridge) {
        if (isRunning) {
            if (confirm("Inspection is currently running. Would you like to stop and finalize the inspection to generate the PDF report?")) {
                onStopInspection();
                setTimeout(() => {
                    window.location.href = `${BACKEND_URL}/api/report/pdf`;
                }, 1500);
            }
            return;
        }
        window.location.href = `${BACKEND_URL}/api/report/pdf`;
        logToCloudConsole("[SYSTEM] Requested PDF inspection report download from Edge gateway.");
    } else {
        alert("Standalone Mode: PDF Report generation requires the live python backend bridge.\nJSON format is downloaded instead.");
        onSave();
    }
}
window.downloadPdfReport = downloadPdfReport;

function updateTimerDisplay() {
    const hrs = Math.floor(sessionTime / 3600).toString().padStart(2, '0');
    const mins = Math.floor((sessionTime % 3600) / 60).toString().padStart(2, '0');
    const secs = (sessionTime % 60).toString().padStart(2, '0');
    document.getElementById('session-time').innerText = `${hrs}:${mins}:${secs}`;
}

// ==========================================================================
// 3. MECHANICAL FABRIC SCROLLER LOOP & DEFECT INJECTIONS (He Component)
// ==========================================================================
const INJECTABLE_TYPES = {
    'Hole': { color: '#ef4444', pWidth: 40, pHeight: 38, basePts: 4, baseSize: 250.0 },
    'Drop Stitch': { color: '#eab308', pWidth: 16, pHeight: 90, basePts: 3, baseSize: 180.0 },
    'Oil Stain': { color: '#fef08a', pWidth: 32, pHeight: 28, basePts: 1, baseSize: 20.0 },
    'Broken Yarn': { color: '#fb923c', pWidth: 50, pHeight: 10, basePts: 2, baseSize: 65.0 }
};

function injectDefect(type) {
    if (useBackendBridge) {
        fetch(`${BACKEND_URL}/api/inject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: type })
        });
        return;
    }
    if (!isRunning || isPaused) {
        logToCloudConsole("[WARNING] Camera is stopped/paused. Press Start to inject targets.");
        return;
    }

    const details = INJECTABLE_TYPES[type];
    const newDef = {
        id: Date.now().toString() + Math.floor(Math.random() * 100),
        type: type,
        x: Math.random() * (canvas.width - 120) + 40,
        y: -100, // Spawn just off canvas top
        width: details.pWidth,
        height: details.pHeight,
        color: details.color,
        detected: false,
        confidence: 98.4,
        size: details.baseSize,
        points: details.basePts
    };

    activeDefectsInFeed.push(newDef);
    refreshActiveDefectsList();
    logToCloudConsole(`[PIPELINE] AI target '${type}' injected with exactly ${newDef.points} points.`);
}
window.injectDefect = injectDefect;

function canvasConveyorLoop() {
    if (useBackendBridge) {
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        try {
            ctx.drawImage(bridgeImg, 0, 0, canvas.width, canvas.height);
        } catch(e) {}
        
        if (isRunning && !isPaused) {
            // Upload current webcam frame to local python AI server at throttled 10 FPS
            if (webcamVideo && webcamVideo.readyState >= 2) {
                const now = Date.now();
                if (now - lastUploadTime >= 100) {
                    lastUploadTime = now;
                    postWebcamFrameToBackend();
                }
            }

            scanlineY += scanlineDirection * 2.8;
            if (scanlineY >= canvas.height || scanlineY <= 0) {
                scanlineDirection = -scanlineDirection;
            }

            ctx.strokeStyle = 'rgba(74, 222, 128, 0.4)';
            ctx.shadowColor = 'rgba(74, 222, 128, 0.8)';
            ctx.shadowBlur = 8;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(0, scanlineY);
            ctx.lineTo(canvas.width, scanlineY);
            ctx.stroke();
            ctx.shadowBlur = 0;
            ctx.shadowColor = 'transparent';
        }
        
        requestAnimationFrame(canvasConveyorLoop);
        return;
    }
    
    // Canvas dimensions are responsive
    if (isRunning && !isPaused) {
        // Auto spawn simulated defects in standalone mode every 12 seconds
        const now = Date.now();
        if (now - lastAutoSpawnTime >= 12000) {
            // If it's the very first spawn, offset lastAutoSpawnTime to prevent immediate double spawn
            if (lastAutoSpawnTime === 0) {
                lastAutoSpawnTime = now - 4000; // spawn in 8s instead of immediately
            } else {
                lastAutoSpawnTime = now;
                const defectTypes = ['Hole', 'Drop Stitch', 'Oil Stain', 'Broken Yarn'];
                const randomType = defectTypes[Math.floor(Math.random() * defectTypes.length)];
                injectDefect(randomType);
            }
        }

        // Clear viewport and draw video feed or fallback pattern
        if (webcamVideo && webcamVideo.readyState >= 2) {
            ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);
            
            // Premium dark-slate semi-transparent optical preprocess lens tint matching HMI prototype
            ctx.fillStyle = 'rgba(15, 23, 42, 0.4)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        } else {
            ctx.fillStyle = '#0f172a'; // slate-900 background matches Figma
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            // 1. Draw mechanical knit scrolling pattern grid texture
            ctx.strokeStyle = '#1e293b'; // slate-800 grids
            ctx.lineWidth = 1;
            
            scrollOffset += 1.8; // scroll velocity
            if (scrollOffset >= 40) scrollOffset = 0;

            for (let x = 0; x < canvas.width; x += 20) {
                ctx.beginPath();
                for (let y = -40; y < canvas.height + 40; y += 20) {
                    const waveY = y + scrollOffset;
                    ctx.arc(x + 10, waveY, 6, 0, Math.PI, true);
                }
                ctx.stroke();
            }
        }

        // 2. Draw defects scrolling down conveyor
        const viewportOverlaysContainer = document.getElementById('live-bounding-boxes-container');
        
        // Loop active targets
        activeDefectsInFeed.forEach((defect) => {
            defect.y += 1.6; // Speed

            // Draw target raw physical pixel box on Canvas context
            ctx.fillStyle = defect.color;
            ctx.globalAlpha = 0.55;
            ctx.fillRect(defect.x, defect.y, defect.width, defect.height);
            ctx.globalAlpha = 1.0;

            // Focal line collision checker: when defect passes canvas center
            const focalCenterY = canvas.height / 2;
            if (defect.y + defect.height >= focalCenterY && !defect.detected) {
                defect.detected = true;
                processDefectEdgePipeline(defect);
            }

            // Draw absolute DOM Bounding Boxes overlaid exactly over Canvas coordinates
            updateAbsoluteDefectDOMBox(defect);
        });

        // Wipe defects that scrolled off-screen
        activeDefectsInFeed = activeDefectsInFeed.filter((def) => {
            if (def.y >= canvas.height) {
                // Remove bounding box DOM elements
                const el = document.getElementById(`overlay-box-${def.id}`);
                if (el) el.remove();
                return false;
            }
            return true;
        });

        // 3. Draw flashing green laser line scanner
        scanlineY += scanlineDirection * 2.8;
        if (scanlineY >= canvas.height || scanlineY <= 0) {
            scanlineDirection = -scanlineDirection;
        }

        ctx.strokeStyle = 'rgba(74, 222, 128, 0.4)'; // green-400 laser
        ctx.shadowColor = 'rgba(74, 222, 128, 0.8)';
        ctx.shadowBlur = 8;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(0, scanlineY);
        ctx.lineTo(canvas.width, scanlineY);
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.shadowColor = 'transparent';
    }

    requestAnimationFrame(canvasConveyorLoop);
}

// Draw/Update absolute overlay tags over the canvas
function updateAbsoluteDefectDOMBox(defect) {
    const parent = document.getElementById('live-bounding-boxes-container');
    if (!parent) return;

    let overlayBox = document.getElementById(`overlay-box-${defect.id}`);
    
    // Create new DOM overlay if not existing
    if (!overlayBox && defect.detected) {
        overlayBox = document.createElement('div');
        overlayBox.id = `overlay-box-${defect.id}`;
        overlayBox.className = "defect-bounding-box";
        
        // Match defect colors
        overlayBox.style.borderColor = defect.color;
        overlayBox.style.boxShadow = `0 0 15px ${defect.color}`;

        // Top labels
        const topBadge = document.createElement('div');
        topBadge.className = "defect-box-label";
        topBadge.style.backgroundColor = defect.color;
        topBadge.innerText = `${defect.type} • ${defect.confidence.toFixed(1)}%`;
        overlayBox.appendChild(topBadge);

        // Bottom specs
        const btmMetadata = document.createElement('div');
        btmMetadata.className = "defect-box-metadata";
        btmMetadata.style.color = defect.color;
        btmMetadata.innerText = `${defect.size.toFixed(1)}mm • (${defect.x.toFixed(0)}, ${defect.y.toFixed(0)})`;
        overlayBox.appendChild(btmMetadata);

        parent.appendChild(overlayBox);
    }

    // Move existing overlays matching canvas coordinate frames
    if (overlayBox) {
        overlayBox.style.left = `${defect.x - 4}px`;
        overlayBox.style.top = `${defect.y - 4}px`;
        overlayBox.style.width = `${defect.width + 8}px`;
        overlayBox.style.height = `${defect.height + 8}px`;
        
        // Update coordinates tag text
        const btm = overlayBox.querySelector('.defect-box-metadata');
        if (btm) {
            btm.innerText = `${defect.size.toFixed(1)}mm • (${defect.x.toFixed(0)}, ${defect.y.toFixed(0)})`;
        }
    }
}

// ==========================================================================
// 4. ASTM 4-POINT grading ARITHMETIC PIPELINE (Ee, Oe, Ve Components)
// ==========================================================================
function processDefectEdgePipeline(defect) {
    // Sound synthetic console alarm trigger
    playHarshAcousticAlarm(defect.points || 1);

    // Dynamic 4-Point ASTM evaluation (respecting precise non-random input points)
    let points = defect.points;
    if (points === undefined) {
        points = 1;
        if (defect.type === "Hole") {
            // Holes calculated by size
            const sizeInches = defect.size / 25.4;
            if (sizeInches <= 3.0) points = 1;
            else if (sizeInches <= 6.0) points = 2;
            else if (sizeInches <= 9.0) points = 3;
            else points = 4;
        } else {
            // Other defects
            points = defect.size > 5.0 ? 2 : 1;
        }
    }

    // Accumulate metrics
    totalDefects++;
    totalPenaltyPoints += points;
    
    if (defect.type === "Hole") holeCount++;
    else needleLineCount++;

    // Quality Score = Math.max(0, Math.min(100, 100 - (totalPenaltyPoints / 40 * 100)))
    qualityScore = Math.max(0, Math.min(100, 100 - (totalPenaltyPoints / 40 * 100)));

    // Sync state strings
    const syncStateStr = isGDriveConnected ? "SYNCED" : "LOCAL ONLY";

    const logRecord = {
        id: defect.id,
        type: defect.type,
        size: defect.size,
        x: defect.x,
        y: defect.y,
        time: new Date().toLocaleTimeString(),
        points: points,
        sync: syncStateStr
    };

    defectLogs.push(logRecord);
    localCacheCount++;
    document.getElementById('local-cache-count').innerText = `${localCacheCount} RECORDS`;
    pushAlert("DEFECT DETECTED", `AI target '${defect.type}' detected (${defect.size.toFixed(1)}mm) at position (${defect.x.toFixed(0)}, ${defect.y.toFixed(0)}) adding ${points} ASTM points. Score: ${qualityScore.toFixed(1)}%.`, "defect");

    // Map defect tallies to SVG line chart
    const activeMinId = `min-${Math.floor(sessionTime / 60)}`;
    const foundTrend = trendData.find(t => t.id === activeMinId);
    if (foundTrend) {
        if (defect.type === "Hole") foundTrend.holes++;
        else foundTrend.needleLines++;
    }

    // Apply values to layout grids
    refreshHmiMetrics();
    refreshDefectTableLogs();
    refreshActiveDefectsList();
    renderSvgTrendChart();
    updateQrReportCode();

    // Google sync backup triggers
    if (isGDriveConnected) {
        uploadQueue.push(logRecord);
        processGoogleDriveUploadQueue();
    } else {
        logToCloudConsole(`[SQLITE] Target DEF-${defect.id.slice(-4)} logged in edge database.`);
    }
}

function refreshHmiMetrics() {
    document.getElementById('metric-defects').innerText = totalDefects;
    document.getElementById('metric-points').innerText = totalPenaltyPoints;
    document.getElementById('metric-holes').innerText = holeCount;
    document.getElementById('metric-needles').innerText = needleLineCount;

    // Sync Analytics Tab text metrics
    const analyticDefects = document.getElementById('analytics-total-defects');
    const analyticPoints = document.getElementById('analytics-total-points');
    const analyticHoles = document.getElementById('analytics-holes');
    const analyticNeedles = document.getElementById('analytics-needles');

    if (analyticDefects) analyticDefects.innerText = totalDefects;
    if (analyticPoints) analyticPoints.innerText = totalPenaltyPoints;
    if (analyticHoles) analyticHoles.innerText = holeCount;
    if (analyticNeedles) analyticNeedles.innerText = needleLineCount;

    document.getElementById('report-points').innerText = `${totalPenaltyPoints} PTS`;
    document.getElementById('report-score').innerText = `${qualityScore.toFixed(1)}%`;

    const badge = document.getElementById('quality-result-badge');
    const isPass = qualityScore >= 80.0;
    
    if (isPass) {
        badge.className = "flex items-center gap-2 px-3 py-1 rounded-full bg-green-600 text-white font-bold font-heading text-xs shadow-lg";
        badge.innerHTML = "<span>✔</span><span>PASS</span>";
    } else {
        badge.className = "flex items-center gap-2 px-3 py-1 rounded-full bg-red-600 text-white font-bold font-heading text-xs shadow-lg animate-pulse";
        badge.innerHTML = "<span>✘</span><span>FAIL</span>";
    }
}

function refreshDefectTableLogs() {
    const tbody = document.getElementById('defect-log-body');
    if (tbody) {
        if (defectLogs.length === 0) {
            tbody.innerHTML = `
                <tr class="border-b border-gray-800">
                    <td colspan="7" class="text-center py-8 text-gray-600 font-bold uppercase font-heading">No defects logged yet</td>
                </tr>`;
        } else {
            tbody.innerHTML = defectLogs.slice(-10).reverse().map((log, idx) => {
                const isNewFlash = idx === 0 ? 'class="new-defect-flash border-b border-gray-800"' : 'class="border-b border-gray-800 hover:bg-gray-800/30 transition-colors"';
                const syncLblClass = log.sync === "SYNCED" ? "text-green-400 font-bold" : "text-yellow-500";
                return `
                    <tr ${isNewFlash}>
                        <td class="px-4 py-2.5 text-xs text-gray-400">#${log.id.slice(-5)}</td>
                        <td class="px-4 py-2.5"><span class="text-xs font-semibold ${log.type === 'Hole' ? 'text-red-400' : 'text-orange-400'}">${log.type.toUpperCase()}</span></td>
                        <td class="px-4 py-2.5 text-xs text-white font-bold">${log.size.toFixed(1)}</td>
                        <td class="px-4 py-2.5 text-xs text-gray-400">(${log.x.toFixed(0)}, ${log.y.toFixed(0)})</td>
                        <td class="px-4 py-2.5 text-xs text-gray-400">${log.time}</td>
                        <td class="px-4 py-2.5 text-xs text-orange-400 font-bold">${log.points}</td>
                        <td class="px-4 py-2.5 text-xs font-heading ${syncLblClass}">${log.sync}</td>
                    </tr>`;
            }).join('');
        }
    }

    const logsPageBody = document.getElementById('logs-page-table-body');
    if (logsPageBody) {
        if (defectLogs.length === 0) {
            logsPageBody.innerHTML = `
                <tr class="border-b border-gray-800">
                    <td colspan="7" class="text-center py-12 text-gray-600 font-bold uppercase font-heading">No database logs registered</td>
                </tr>`;
        } else {
            logsPageBody.innerHTML = defectLogs.slice().reverse().map((log) => {
                const syncLblClass = log.sync === "SYNCED" ? "text-green-400 font-bold" : "text-yellow-500";
                return `
                    <tr class="border-b border-gray-800 hover:bg-gray-800/30 transition-colors">
                        <td class="px-6 py-3 text-xs text-gray-400">${log.time}</td>
                        <td class="px-6 py-3 text-xs text-white font-bold">${RollId}</td>
                        <td class="px-6 py-3 text-xs text-gray-400">DEF-${log.id.slice(-4)}</td>
                        <td class="px-6 py-3"><span class="text-xs font-semibold ${log.type === 'Hole' ? 'text-red-400' : 'text-orange-400'}">${log.type.toUpperCase()}</span></td>
                        <td class="px-6 py-3 text-xs text-white font-bold">${log.size.toFixed(1)}</td>
                        <td class="px-6 py-3 text-xs text-orange-400 font-bold">${log.points}</td>
                        <td class="px-6 py-3 text-xs font-heading ${syncLblClass}">${log.sync}</td>
                    </tr>`;
            }).join('');
        }
    }
}

function refreshActiveDefectsList() {
    const box = document.getElementById('active-defects-list');
    
    if (activeDefectsInFeed.length === 0) {
        box.innerHTML = '<p class="text-gray-500 text-xs text-center py-4 font-heading font-semibold uppercase">No defects in feed</p>';
        return;
    }

    box.innerHTML = activeDefectsInFeed.map((def) => {
        return `
            <div class="bg-gray-800 border border-gray-700 rounded p-3 flex items-center justify-between transition-all">
                <div class="flex-1">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-bold ${def.type === 'Hole' ? 'text-red-400' : 'text-orange-400'}">${def.type}</span>
                        <span class="text-[9px] text-gray-500">Size: ${def.size.toFixed(1)}mm</span>
                    </div>
                    <div class="text-[9px] text-gray-400 mt-0.5">Position: (${def.x.toFixed(0)}, ${def.y.toFixed(0)})</div>
                </div>
                <div class="text-right">
                    <div class="text-xs font-bold text-white font-heading">${def.confidence.toFixed(1)}%</div>
                    <div class="text-[9px] text-gray-500">In feed</div>
                </div>
            </div>`;
    }).join('');

    // Also populate the tabular summary matrix (Ve)
    const tbody = document.getElementById('summary-matrix-body');
    tbody.innerHTML = defectLogs.map((log, idx) => {
        return `
            <tr class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td class="py-1 px-2 text-gray-300 text-xs">${idx + 1}</td>
                <td class="py-1 px-2 text-center text-xs">${log.type === 'Hole' ? '🔴' : '-'}</td>
                <td class="py-1 px-2 text-center text-xs">${log.type === 'Needle Line' ? '🟡' : '-'}</td>
                <td class="py-1 px-2 text-center text-xs text-white font-semibold">${log.points}</td>
            </tr>`;
    }).join('');
}

// ==========================================================================
// 5. SVG REAL-TIME LINE GRAPH DRAWING (ze Line-chart Component)
// ==========================================================================
function renderSvgTrendChart() {
    renderSvgTrendChartGeneric('trend-svg');
    renderSvgTrendChartGeneric('large-trend-svg');
}

function renderSvgTrendChartGeneric(svgId) {
    const svg = document.getElementById(svgId);
    if (!svg) return;

    // Clear svg coordinates
    svg.innerHTML = '';

    const width = svg.parentElement.clientWidth;
    const height = svg.parentElement.clientHeight || 200;
    if (width <= 0 || height <= 0) return;
    
    // SVG grid padding
    const padding = { top: 20, right: 20, bottom: 25, left: 30 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Get max y boundary limits
    const maxVal = Math.max(
        ...trendData.map(d => Math.max(d.holes, d.needleLines)),
        5
    );

    // Graph plotting formula calculations
    const getX = (idx) => padding.left + (idx / Math.max(trendData.length - 1, 1)) * chartW;
    const getY = (val) => padding.top + chartH - (val / maxVal) * chartH;

    // 1. Draw horizontal dotted grid lines
    const gridDivisions = [0, Math.ceil(maxVal / 2), maxVal];
    gridDivisions.forEach(val => {
        const y = getY(val);
        
        // Dotted grid path line
        const gridLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        gridLine.setAttribute('x1', padding.left);
        gridLine.setAttribute('y1', y);
        gridLine.setAttribute('x2', width - padding.right);
        gridLine.setAttribute('y2', y);
        gridLine.setAttribute('stroke', '#374151');
        gridLine.setAttribute('stroke-dasharray', '3,3');
        gridLine.setAttribute('stroke-width', '1');
        svg.appendChild(gridLine);

        // Y label tag
        const yLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        yLabel.setAttribute('x', padding.left - 8);
        yLabel.setAttribute('y', y + 3);
        yLabel.setAttribute('fill', '#6b7280');
        yLabel.setAttribute('font-size', '9');
        yLabel.setAttribute('text-anchor', 'end');
        yLabel.textContent = val;
        svg.appendChild(yLabel);
    });

    // 2. Plot X label tags
    trendData.forEach((d, idx) => {
        if (idx % Math.ceil(trendData.length / 5) === 0 || idx === trendData.length - 1) {
            const x = getX(idx);
            const xLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            xLabel.setAttribute('x', x);
            xLabel.setAttribute('y', height - 6);
            xLabel.setAttribute('fill', '#6b7280');
            xLabel.setAttribute('font-size', '9');
            xLabel.setAttribute('text-anchor', 'middle');
            xLabel.textContent = d.time;
            svg.appendChild(xLabel);
        }
    });

    // 3. Compile SVG Paths for Holes (Red line) and Needle Lines (Yellow line)
    let holesPathStr = '';
    let needlesPathStr = '';

    trendData.forEach((d, idx) => {
        const x = getX(idx);
        const yHoles = getY(d.holes);
        const yNeedles = getY(d.needleLines);

        if (idx === 0) {
            holesPathStr = `M ${x} ${yHoles}`;
            needlesPathStr = `M ${x} ${yNeedles}`;
        } else {
            holesPathStr += ` L ${x} ${yHoles}`;
            needlesPathStr += ` L ${x} ${yNeedles}`;
        }
    });

    // Draw Holes path
    const holesPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    holesPath.setAttribute('d', holesPathStr);
    holesPath.setAttribute('fill', 'none');
    holesPath.setAttribute('stroke', '#ef4444'); // red-500
    holesPath.setAttribute('stroke-width', '2');
    holesPath.setAttribute('stroke-linecap', 'round');
    holesPath.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(holesPath);

    // Draw Needle Lines path
    const needlesPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    needlesPath.setAttribute('d', needlesPathStr);
    needlesPath.setAttribute('fill', 'none');
    needlesPath.setAttribute('stroke', '#eab308'); // yellow-500
    needlesPath.setAttribute('stroke-width', '2');
    needlesPath.setAttribute('stroke-linecap', 'round');
    needlesPath.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(needlesPath);

    // 4. Draw SVG Legend tags
    const legendGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    legendGroup.setAttribute('transform', `translate(${width - 160}, 10)`);

    // Holes Dot and Label
    const hDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    hDot.setAttribute('cx', '0');
    hDot.setAttribute('cy', '0');
    hDot.setAttribute('r', '3');
    hDot.setAttribute('fill', '#ef4444');
    legendGroup.appendChild(hDot);

    const hLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    hLabel.setAttribute('x', '8');
    hLabel.setAttribute('y', '3');
    hLabel.setAttribute('fill', '#9ca3af');
    hLabel.setAttribute('font-size', '9');
    hLabel.textContent = "Holes";
    legendGroup.appendChild(hLabel);

    // Needles Dot and Label
    const nDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    nDot.setAttribute('cx', '60');
    nDot.setAttribute('cy', '0');
    nDot.setAttribute('r', '3');
    nDot.setAttribute('fill', '#eab308');
    legendGroup.appendChild(nDot);

    const nLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    nLabel.setAttribute('x', '68');
    nLabel.setAttribute('y', '3');
    nLabel.setAttribute('fill', '#9ca3af');
    nLabel.setAttribute('font-size', '9');
    nLabel.textContent = "Needles";
    legendGroup.appendChild(nLabel);

    svg.appendChild(legendGroup);
}

// ==========================================================================
// 6. BOTTOM NAVIGATION TABS ROUTING HANDLER (qe Component)
// ==========================================================================
function switchTab(tabId) {
    const tabs = ['home', 'analytics', 'report', 'logs', 'alerts'];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-${t}`);
        if (btn) {
            if (t === tabId) {
                btn.className = "flex flex-col items-center justify-center gap-1 px-8 py-1 rounded-lg transition-all bg-gray-800 text-green-400 active-tab-highlight";
            } else {
                btn.className = "flex flex-col items-center justify-center gap-1 px-8 py-1 rounded-lg transition-all text-gray-500 hover:text-gray-300 hover:bg-gray-800/30";
            }
        }

        // Swap the visibility of the five panels
        const panel = document.getElementById(`tab-panel-${t}`);
        if (panel) {
            if (t === tabId) {
                panel.classList.remove('hidden');
            } else {
                panel.classList.add('hidden');
            }
        }
    });

    activeTab = tabId;
    logToCloudConsole(`[SYSTEM] Navigated tab workspace frame to: ${tabId.toUpperCase()}`);

    // Trigger page-specific refreshes
    if (tabId === 'home') {
        resizeCanvas();
        renderSvgTrendChart();
    } else if (tabId === 'analytics') {
        renderSvgTrendChart();
        drawHardwareSparkline();
    } else if (tabId === 'report') {
        updateQrReportCode();
    } else if (tabId === 'logs') {
        refreshDefectTableLogs();
    } else if (tabId === 'alerts') {
        alertsUnacknowledgedCount = 0;
        const badge = document.getElementById('alerts-badge-count');
        if (badge) {
            badge.innerText = '0';
            badge.className = "absolute -top-1.5 -right-2.5 bg-red-600 text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center font-heading";
        }
        refreshAlertsConsoleDisplay();
    }
}
window.switchTab = switchTab;

function toggleSettingsModal(forceState = null) {
    const modal = document.getElementById('settings-overlay-modal');
    if (!modal) return;

    if (forceState !== null) {
        if (forceState) modal.classList.remove('hidden');
        else modal.classList.add('hidden');
        return;
    }

    modal.classList.toggle('hidden');
}
window.toggleSettingsModal = toggleSettingsModal;

function updateBeaconsState() {
    const cameraBeacon = document.getElementById('beacon-camera');
    const yoloBeacon = document.getElementById('beacon-yolo');
    const lightBeacon = document.getElementById('beacon-light');
    const dbBeacon = document.getElementById('beacon-db');
    const gdriveBeacon = document.getElementById('beacon-gdrive');
    const gdriveText = document.getElementById('gdrive-status-badge');

    // Dynamically light up core hardware beacons when the scroller is actively running
    const isInspectionRunning = isRunning && !isPaused;

    if (isInspectionRunning) {
        if (cameraBeacon) cameraBeacon.className = "w-2 h-2 rounded-full bg-green-400 blinking-dot";
        if (yoloBeacon) yoloBeacon.className = "w-2 h-2 rounded-full bg-green-400 blinking-dot";
        if (lightBeacon) lightBeacon.className = "w-2 h-2 rounded-full bg-green-400 blinking-dot";
        if (dbBeacon) dbBeacon.className = "w-2 h-2 rounded-full bg-green-400 blinking-dot";
    } else {
        if (cameraBeacon) cameraBeacon.className = "w-2 h-2 rounded-full bg-red-400";
        if (yoloBeacon) yoloBeacon.className = "w-2 h-2 rounded-full bg-red-400";
        if (lightBeacon) lightBeacon.className = "w-2 h-2 rounded-full bg-red-400";
        if (dbBeacon) dbBeacon.className = "w-2 h-2 rounded-full bg-red-400";
    }

    // Google Drive cloud beacon responds to OAuth link connection state
    if (isGDriveConnected) {
        if (gdriveBeacon) gdriveBeacon.className = "w-2 h-2 rounded-full bg-green-400 blinking-dot";
        if (gdriveText) gdriveText.innerText = "DRIVE: ON";
    } else {
        if (gdriveBeacon) gdriveBeacon.className = "w-2 h-2 rounded-full bg-red-400";
        if (gdriveText) gdriveText.innerText = "DRIVE: OFF";
    }
}
window.updateBeaconsState = updateBeaconsState;

// ==========================================================================
// 7. GOOGLE CLOUD SYNC & OAUTH HANDSHAKE SIMULATION (Figma Integration)
// ==========================================================================
function handleGoogleDriveAuth() {
    const btn = document.getElementById('btn-gdrive-login');
    const userBox = document.getElementById('gdrive-user-display');
    const badge = document.getElementById('beacon-gdrive');
    const statusText = document.getElementById('gdrive-status-badge');

    if (!isGDriveConnected) {
        // Switch Settings Overlay Modal off to prevent overlap clutter
        toggleSettingsModal(false);

        // Reset and trigger Mock Google OAuth popup overlay
        const oauthModal = document.getElementById('google-oauth-modal');
        if (oauthModal) {
            oauthModal.classList.remove('hidden');
            
            // Show accounts selection screen first
            document.getElementById('oauth-screen-accounts').classList.remove('hidden');
            document.getElementById('oauth-screen-consent').classList.add('hidden');
            document.getElementById('oauth-screen-loader').classList.add('hidden');
            
            document.getElementById('oauth-title').innerText = "Sign in with Google";
            document.getElementById('oauth-subtitle').innerText = "to continue to KnitX-ultra Cloud Sync";
        }
    } else {
        // Perform clean cloud storage logout and clear active credentials fully
        isGDriveConnected = false;
        gdriveUserEmail = ""; // Flush the saved operator email!
        btn.innerText = "LOGIN TO GOOGLE DRIVE";
        btn.className = "px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold font-heading text-xs rounded shadow-lg transition-all hover:scale-105 flex items-center gap-2";
        
        userBox.innerText = "LOCAL MODE (UNLINKED)";
        userBox.className = "text-xs font-bold text-yellow-400 font-heading";
        
        updateBeaconsState();
        
        logToCloudConsole("[OAUTH 2.0] Google account credentials successfully cleared. Switched back to Edge-Only buffering.");
    }
}

// Global functions linked to HTML click triggers for Google OAuth workflow
window.selectGoogleAccount = function(email) {
    if (email === 'new') {
        const inputEmail = prompt("Enter your operator Google Account email address:", "inspector.charlie@knitx-ultra.com");
        if (!inputEmail || !inputEmail.trim()) return;
        gdriveUserEmail = inputEmail.trim();
    } else {
        gdriveUserEmail = email;
    }

    logToCloudConsole(`[OAUTH 2.0] Account selected: ${gdriveUserEmail}. Requesting permissions...`);

    // Transition to permissions consent screen
    document.getElementById('oauth-screen-accounts').classList.add('hidden');
    document.getElementById('oauth-screen-consent').classList.remove('hidden');

    document.getElementById('oauth-title').innerText = "Grant Account Access";
    document.getElementById('oauth-subtitle').innerText = `App 'KnitX-ultra' wants to access ${gdriveUserEmail}`;
};

window.grantGooglePermissions = function() {
    // Transition to loading progress spinner screen
    document.getElementById('oauth-screen-consent').classList.add('hidden');
    document.getElementById('oauth-screen-loader').classList.remove('hidden');

    const loaderText = document.getElementById('oauth-loader-text');
    
    // Animate HMI oauth handshakes dynamically
    loaderText.innerText = "Requesting secure OAuth token...";
    
    setTimeout(() => {
        loaderText.innerText = "Directing SSH handshake to Google API Gateway...";
        
        setTimeout(() => {
            loaderText.innerText = "Mapping target cloud folder '/KnitX-ultra/Reports/'...";
            
            setTimeout(() => {
                loaderText.innerText = "Securing data tunnel. Syncing SQLite buffers...";
                
                setTimeout(() => {
                    // Close OAuth popup
                    window.closeOauthModal();
                    
                    // Activate HMI Cloud variables
                    isGDriveConnected = true;
                    
                    const btn = document.getElementById('btn-gdrive-login');
                    const userBox = document.getElementById('gdrive-user-display');
                    const badge = document.getElementById('beacon-gdrive');
                    const statusText = document.getElementById('gdrive-status-badge');
                    
                    btn.innerText = "DISCONNECT GOOGLE DRIVE";
                    btn.className = "px-4 py-2 bg-red-900/50 hover:bg-red-800/50 border border-red-700 text-red-400 font-bold font-heading text-xs rounded transition-all flex items-center gap-2";
                    
                    userBox.innerText = `CONNECTED: ${gdriveUserEmail}`;
                    userBox.className = "text-xs font-bold text-green-400 font-heading";
                    
                    updateBeaconsState();
                    
                    logToCloudConsole("[OAUTH 2.0] Handshake complete: supervisor cloud token verified.");
                    logToCloudConsole(`[CLOUD] Connected Google Drive target workspace: /Google Drive/KnitX-ultra/Reports/`);

                    // Re-open settings modal dashboard
                    toggleSettingsModal(true);
                    
                    // Upload cached SQLite logs
                    if (defectLogs.length > 0) {
                        logToCloudConsole(`[CLOUD] Syncing ${defectLogs.length} queued SQLite records to folder...`);
                        defectLogs.forEach(log => {
                            if (log.sync === "LOCAL ONLY") {
                                log.sync = "SYNCED";
                                uploadQueue.push(log);
                            }
                        });
                        refreshDefectTableLogs();
                        processGoogleDriveUploadQueue();
                    }
                }, 800);
            }, 800);
        }, 800);
    }, 800);
};

window.closeOauthModal = function() {
    const oauthModal = document.getElementById('google-oauth-modal');
    if (oauthModal) {
        oauthModal.classList.add('hidden');
    }
};

function processGoogleDriveUploadQueue() {
    if (!isGDriveConnected || uploadQueue.length === 0) return;
    
    document.getElementById('upload-queue-count').innerText = `${uploadQueue.length} PENDING`;
    
    const activeUpload = uploadQueue.shift();
    
    setTimeout(() => {
        logToCloudConsole(`[CLOUD SUCCESS] Upload complete: DEF-${activeUpload.id.slice(-4)} -> Google Drive/KnitX-ultra/Reports/`);
        
        // Update Table logs sync badge
        const found = defectLogs.find(r => r.id === activeUpload.id);
        if (found) found.sync = "SYNCED";
        refreshDefectTableLogs();
        
        document.getElementById('upload-queue-count').innerText = `${uploadQueue.length} PENDING`;
        
        // Loop recursively
        if (uploadQueue.length > 0) {
            processGoogleDriveUploadQueue();
        }
    }, 600);
}

function logToCloudConsole(message) {
    const term = document.getElementById('gdrive-log');
    if (!term) return;
    const now = new Date();
    const timeStr = `[${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}]`;
    term.innerHTML += `<br>${timeStr} ${message}`;
    term.scrollTop = term.scrollHeight; // Autoscrolls
}

// ==========================================================================
// 8. PHYSICAL RETRO CONSOLE ACOUSTIC ALARMS (Web Audio Direct synthesis)
// ==========================================================================
function toggleAcousticAlarm() {
    soundAlarmEnabled = !soundAlarmEnabled;
    const btn1 = document.getElementById('btn-sound-alarm');
    const btn2 = document.getElementById('btn-sound-alarm-alerts');
    
    [btn1, btn2].forEach(btn => {
        if (btn) {
            if (soundAlarmEnabled) {
                btn.innerText = "ALARM BUZZER ENABLED";
                btn.className = "w-full py-2 bg-green-900/40 hover:bg-green-900/60 text-green-400 border border-green-700 font-bold font-heading text-xs rounded transition-all";
            } else {
                btn.innerText = "ALARM BUZZER MUTED";
                btn.className = "w-full py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 border border-red-700 font-bold font-heading text-xs rounded transition-all";
            }
        }
    });
}
window.toggleAcousticAlarm = toggleAcousticAlarm;

function playHarshAcousticAlarm(points) {
    if (!soundAlarmEnabled) return;

    try {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }

        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }

        const duration = 0.15 + (points * 0.04);
        const pitch = 980 - (points * 120); // Low harsh frequency beep for severe errors

        const osc = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();

        osc.connect(gainNode);
        gainNode.connect(audioCtx.destination);

        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(pitch, audioCtx.currentTime);

        gainNode.gain.setValueAtTime(0.2, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);

        osc.start(audioCtx.currentTime);
        osc.stop(audioCtx.currentTime + duration);
    } catch (e) {
        console.warn("Web Audio API was blocked.", e);
    }
}

// ==========================================================================
// 9. OFFLINE STANDALONE QR GENERATION & AUDIT MAINTENANCE
// ==========================================================================
function updateQrReportCode() {
    // 1. Sync Report Tab text fields
    const rollEl = document.getElementById('report-page-roll');
    const batchEl = document.getElementById('report-page-batch');
    const yardageEl = document.getElementById('report-page-yardage');
    
    if (rollEl) rollEl.innerText = RollId;
    if (batchEl) batchEl.innerText = BatchId;
    if (yardageEl) {
        const yds = (sessionTime * 0.25).toFixed(1);
        yardageEl.innerText = `${yds} YD`;
    }

    // 2. Set QC badge
    const badge = document.getElementById('report-page-badge');
    if (badge) {
        const isPass = qualityScore >= 80.0;
        if (isPass) {
            badge.className = "px-6 py-2 bg-green-600 text-white font-bold font-heading text-sm rounded-full shadow-lg flex items-center gap-2";
            badge.innerHTML = "<span>✔</span><span>ACCEPT</span>";
        } else {
            badge.className = "px-6 py-2 bg-red-600 text-white font-bold font-heading text-sm rounded-full shadow-lg flex items-center gap-2 animate-pulse";
            badge.innerHTML = "<span>✘</span><span>REJECT</span>";
        }
    }

    // 3. Generate QR Payload and Render Canvas
    const canvas = document.getElementById('report-page-qr-canvas');
    if (canvas && window.KnitXQR) {
        const payload = `RollId:${RollId}|Batch:${BatchId}|Defects:${totalDefects}|Points:${totalPenaltyPoints}|Score:${qualityScore.toFixed(1)}%|QC:${qualityScore >= 80 ? 'ACCEPT' : 'REJECT'}`;
        try {
            window.KnitXQR.render(canvas, payload, 3);
        } catch (e) {
            console.error("QR Code rendering failed", e);
        }
    }
}

window.exportCSV = function() {
    if (defectLogs.length === 0) {
        alert("No SQLite database logs to export!");
        return;
    }

    const headers = ["Timestamp", "Roll ID", "Defect ID", "Defect Class", "Size (mm)", "Points", "Cloud Sync State"];
    const rows = defectLogs.map(log => [
        log.time,
        RollId,
        `DEF-${log.id.slice(-4)}`,
        log.type,
        log.size.toFixed(1),
        log.points,
        log.sync
    ]);

    const csvContent = "data:text/csv;charset=utf-8," 
        + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `knitx-sqlite-audit-${RollId}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    pushAlert("DATABASE EXPORTED", `SQLite defect logs register exported to knitx-sqlite-audit-${RollId}.csv.`, "success");
};

function clearSQLiteHistory() {
    if (confirm("CRITICAL WARNING: Are you sure you want to flush all SQLite database registers for this roll?")) {
        defectLogs = [];
        localCacheCount = 0;
        document.getElementById('local-cache-count').innerText = "0 RECORDS";
        refreshDefectTableLogs();
        refreshActiveDefectsList();
        logToCloudConsole("[SYSTEM] SQLite cache cleared by operator.");
        pushAlert("DATABASE PURGED", "SQLite defect tables cleared completely by supervisor.", "alarm");
    }
}
window.clearSQLiteHistory = clearSQLiteHistory;

// ==========================================================================
// 10. DIAGNOSTICS & SYSTEM FLUCTUATIONS
// ==========================================================================
let isHighTempAlertActive = false;

function updateHardwareFluctuations() {
    // If connected to python server, status polling updates these, so we do nothing here
    if (useBackendBridge) return;

    let cpuLoad = 12;
    let cpuTemp = 41.2;
    currentInferenceLatency = 0.0;

    if (isRunning && !isPaused) {
        // High fidelity simulated edge diagnostics matching RPi5 + YOLO ONNX
        cpuLoad = Math.floor(Math.random() * 12) + 24; // 24% to 35% CPU Load
        cpuTemp = 52.0 + Math.random() * 6.5; // 52.0°C to 58.5°C
        currentInferenceLatency = 14.5 + Math.random() * 4.1; // 14.5ms to 18.6ms
    }

    const latencyEl = document.getElementById('inf-latency');
    if (latencyEl) {
        latencyEl.innerText = currentInferenceLatency > 0 ? `${currentInferenceLatency.toFixed(1)} ms` : `0.0 ms`;
    }

    // Update UI elements in Analytics tab
    const cpuValEl = document.getElementById('pb-cpu-val');
    const cpuBarEl = document.getElementById('pb-cpu-bar');
    const tempValEl = document.getElementById('pb-temp-val');
    const tempBarEl = document.getElementById('pb-temp-bar');

    if (cpuValEl) cpuValEl.innerText = `${cpuLoad}%`;
    if (cpuBarEl) cpuBarEl.style.width = `${cpuLoad}%`;
    if (tempValEl) tempValEl.innerText = `${cpuTemp.toFixed(1)} °C`;
    if (tempBarEl) {
        tempBarEl.style.width = `${cpuTemp}%`;
        
        // Dynamically style temperature bar color based on thresholds
        if (cpuTemp > 65) {
            tempBarEl.className = "h-full bg-red-500 transition-all duration-300";
        } else if (cpuTemp > 50) {
            tempBarEl.className = "h-full bg-yellow-500 transition-all duration-300";
        } else {
            tempBarEl.className = "h-full bg-green-500 transition-all duration-300";
        }
    }

    // Maintain stable flat temperature history for sparkline
    tempHistory.push(cpuTemp);
    if (tempHistory.length > 15) tempHistory.shift();

    // Redraw sparkline if Analytics tab is open
    if (activeTab === 'analytics') {
        drawHardwareSparkline();
    }
}

// ==========================================================================
// 10.5. SYSTEM ALERTS, WARN CONSOLE & SOUND BUZZER BEACONS
// ==========================================================================
function drawHardwareSparkline() {
    const canvas = document.getElementById('large-temp-sparkline');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.parentElement.clientWidth;
    const height = canvas.parentElement.clientHeight || 56;
    canvas.width = width;
    canvas.height = height;

    if (width <= 0 || height <= 0) return;

    ctx.clearRect(0, 0, width, height);

    // Grid lines for high-quality dark industrial look
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < width; x += width / 6) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
    }
    for (let y = 0; y < height; y += height / 3) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
    }

    if (tempHistory.length < 2) return;

    const minTemp = 50;
    const maxTemp = 75;

    const getX = (idx) => (idx / (tempHistory.length - 1)) * width;
    const getY = (temp) => height - 4 - ((temp - minTemp) / (maxTemp - minTemp)) * (height - 8);

    // Draw the area fill gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, 'rgba(34, 197, 94, 0.2)'); // green-500 fading out
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(0, height);
    tempHistory.forEach((temp, idx) => {
        ctx.lineTo(getX(idx), getY(temp));
    });
    ctx.lineTo(width, height);
    ctx.closePath();
    ctx.fill();

    // Draw the sparkline stroke
    ctx.strokeStyle = '#22c55e'; // green-500
    ctx.lineWidth = 2.0;
    ctx.shadowBlur = 4;
    ctx.shadowColor = '#22c55e';
    ctx.beginPath();
    tempHistory.forEach((temp, idx) => {
        if (idx === 0) ctx.moveTo(getX(idx), getY(temp));
        else ctx.lineTo(getX(idx), getY(temp));
    });
    ctx.stroke();
    
    // Reset shadow
    ctx.shadowBlur = 0;
    ctx.shadowColor = 'transparent';

    // Draw active point
    const lastIdx = tempHistory.length - 1;
    const lastTemp = tempHistory[lastIdx];
    ctx.fillStyle = '#22c55e';
    ctx.beginPath();
    ctx.arc(getX(lastIdx), getY(lastTemp), 3, 0, 2 * Math.PI);
    ctx.fill();
}

function pushAlert(title, desc, type = 'info') {
    const alertObj = {
        time: new Date().toLocaleTimeString(),
        title: title,
        desc: desc,
        type: type
    };
    alertsHistory.push(alertObj);
    if (alertsHistory.length > 50) alertsHistory.shift(); // Keep console size reasonable

    if (activeTab !== 'alerts') {
        alertsUnacknowledgedCount++;
        const badge = document.getElementById('alerts-badge-count');
        if (badge) {
            badge.innerText = alertsUnacknowledgedCount;
            badge.className = "absolute -top-1.5 -right-2.5 bg-red-600 text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center font-heading animate-pulse";
        }
    } else {
        refreshAlertsConsoleDisplay();
    }
}
window.pushAlert = pushAlert;

function refreshAlertsConsoleDisplay() {
    const list = document.getElementById('alerts-console-logs-list');
    if (!list) return;

    if (alertsHistory.length === 0) {
        list.innerHTML = `<div class="text-center py-8 text-gray-500 text-xs font-heading font-semibold uppercase">No alerts logged</div>`;
        return;
    }

    list.innerHTML = alertsHistory.slice().reverse().map(alert => {
        let icon = "ℹ️";
        let titleColor = "text-white";
        let bgClass = "bg-gray-900/40 border-gray-800";
        if (alert.type === 'system') {
            icon = "⚙️";
            titleColor = "text-blue-400";
        } else if (alert.type === 'defect') {
            icon = "⚠️";
            titleColor = "text-yellow-500";
            bgClass = "bg-yellow-950/20 border-yellow-900/40";
        } else if (alert.type === 'alarm') {
            icon = "🚨";
            titleColor = "text-red-500";
            bgClass = "bg-red-950/20 border-red-900/40";
        } else if (alert.type === 'success') {
            icon = "✔";
            titleColor = "text-green-400";
        }

        return `
            <div class="flex items-start gap-3 p-3 border rounded-lg ${bgClass}">
                <span class="text-base mt-0.5">${icon}</span>
                <div class="flex flex-col text-xs leading-relaxed">
                    <span class="font-bold ${titleColor} font-heading">[${alert.time}] ${alert.title.toUpperCase()}</span>
                    <span class="text-gray-400">${alert.desc}</span>
                </div>
            </div>`;
    }).join('');
}

window.clearActiveAlertsCount = function() {
    alertsUnacknowledgedCount = 0;
    const badge = document.getElementById('alerts-badge-count');
    if (badge) {
        badge.innerText = '0';
        badge.className = "absolute -top-1.5 -right-2.5 bg-red-600 text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center font-heading";
    }
    pushAlert("SYSTEM STATS", "Operator John Doe acknowledged all console warnings.", "success");
};

// ==========================================================================
// 11. HMI MULTI-PANEL DRAGGABLE RESIZER SYSTEM
// ==========================================================================
function initResizers() {
    const paneCenter = document.getElementById('pane-center');
    const paneFeed = document.getElementById('pane-feed');
    const paneAnalytics = document.getElementById('pane-analytics');
    const paneLogs = document.getElementById('pane-logs');
    const paneSummary = document.getElementById('pane-summary');
    const topHalf = document.getElementById('pane-top-half');

    const resizerFeedAnalytics = document.getElementById('resizer-feed-analytics');
    const resizerTopBottom = document.getElementById('resizer-top-bottom');
    const resizerCenterSummary = document.getElementById('resizer-center-summary');

    // 1. Vertical Drag Resizer: Center Area <-> Far-Right Summary column
    if (resizerCenterSummary && paneSummary) {
        resizerCenterSummary.addEventListener('mousedown', startColDrag);
        resizerCenterSummary.addEventListener('touchstart', startColDrag);

        function startColDrag(e) {
            e.preventDefault();
            document.addEventListener('mousemove', doColDrag);
            document.addEventListener('mouseup', stopColDrag);
            document.addEventListener('touchmove', doColDrag);
            document.addEventListener('touchend', stopColDrag);

            const startX = e.clientX || e.touches[0].clientX;
            const startWidth = paneSummary.offsetWidth;

            function doColDrag(e) {
                const currentX = e.clientX || (e.touches && e.touches[0].clientX);
                if (currentX === undefined) return;
                const dx = currentX - startX;
                let newWidth = startWidth - dx;

                // Glove touchscreen industrial boundaries
                if (newWidth < 150) newWidth = 150;
                if (newWidth > 450) newWidth = 450;

                paneSummary.style.width = newWidth + 'px';
                
                // Trigger real-time canvas and graph resize hooks
                resizeCanvas();
                renderSvgTrendChart();
            }

            function stopColDrag() {
                document.removeEventListener('mousemove', doColDrag);
                document.removeEventListener('mouseup', stopColDrag);
                document.removeEventListener('touchmove', doColDrag);
                document.removeEventListener('touchend', stopColDrag);
                logToCloudConsole(`[HMI] Pane layout resized: Far-Right Panel width adjusted to ${paneSummary.offsetWidth}px`);
            }
        }
    }

    // 2. Vertical Drag Resizer: Live Feed Conveyor <-> Right Analytics Panel
    if (resizerFeedAnalytics && paneAnalytics) {
        resizerFeedAnalytics.addEventListener('mousedown', startColDrag);
        resizerFeedAnalytics.addEventListener('touchstart', startColDrag);

        function startColDrag(e) {
            e.preventDefault();
            document.addEventListener('mousemove', doColDrag);
            document.addEventListener('mouseup', stopColDrag);
            document.addEventListener('touchmove', doColDrag);
            document.addEventListener('touchend', stopColDrag);

            const startX = e.clientX || e.touches[0].clientX;
            const startWidth = paneAnalytics.offsetWidth;

            function doColDrag(e) {
                const currentX = e.clientX || (e.touches && e.touches[0].clientX);
                if (currentX === undefined) return;
                const dx = currentX - startX;
                let newWidth = startWidth - dx;

                if (newWidth < 180) newWidth = 180;
                if (newWidth > 500) newWidth = 500;

                paneAnalytics.style.width = newWidth + 'px';
                
                resizeCanvas();
                renderSvgTrendChart();
            }

            function stopColDrag() {
                document.removeEventListener('mousemove', doColDrag);
                document.removeEventListener('mouseup', stopColDrag);
                document.removeEventListener('touchmove', doColDrag);
                document.removeEventListener('touchend', stopColDrag);
                logToCloudConsole(`[HMI] Pane layout resized: Right Analytics width adjusted to ${paneAnalytics.offsetWidth}px`);
            }
        }
    }

    // 3. Horizontal Drag Resizer: Top Conveyor viewport <-> Bottom Logs table database
    if (resizerTopBottom && paneLogs) {
        resizerTopBottom.addEventListener('mousedown', startRowDrag);
        resizerTopBottom.addEventListener('touchstart', startRowDrag);

        function startRowDrag(e) {
            e.preventDefault();
            document.addEventListener('mousemove', doRowDrag);
            document.addEventListener('mouseup', stopRowDrag);
            document.addEventListener('touchmove', doRowDrag);
            document.addEventListener('touchend', stopRowDrag);

            const startY = e.clientY || e.touches[0].clientY;
            const startHeight = paneLogs.offsetHeight;

            function doRowDrag(e) {
                const currentY = e.clientY || (e.touches && e.touches[0].clientY);
                if (currentY === undefined) return;
                const dy = currentY - startY;
                let newHeight = startHeight - dy;

                if (newHeight < 100) newHeight = 100;
                const maxHeight = paneCenter.offsetHeight - 180;
                if (newHeight > maxHeight) newHeight = maxHeight;

                paneLogs.style.height = newHeight + 'px';
                
                resizeCanvas();
                renderSvgTrendChart();
            }

            function stopRowDrag() {
                document.removeEventListener('mousemove', doRowDrag);
                document.removeEventListener('mouseup', stopRowDrag);
                document.removeEventListener('touchmove', doRowDrag);
                document.removeEventListener('touchend', stopRowDrag);
                logToCloudConsole(`[HMI] Pane layout resized: Bottom Logs height adjusted to ${paneLogs.offsetHeight}px`);
            }
        }
    }
}

