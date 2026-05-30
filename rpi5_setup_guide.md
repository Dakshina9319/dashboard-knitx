# Raspberry Pi 5 Deploy & Optimization Guide (4GB RAM)

This guide provides step-by-step instructions to set up, optimize, and run the complete **KnitX-Ultra Edge-AI Inspection Bridge** (backend) and **HMI Dashboard** (frontend) on a **Raspberry Pi 5 (4GB RAM)**.

---

## 📋 System Requirements & Recommendations

*   **Hardware**: Raspberry Pi 5 (4GB or 8GB RAM).
*   **Cooling**: Official Raspberry Pi Active Cooler or Case with Fan (**highly recommended**, as YOLOv8 inference will heat up the SoC and cause thermal throttling).
*   **OS**: Raspberry Pi OS (64-bit) Bookworm (recommended for optimal 64-bit ARM CPU optimizations).
*   **Camera**: 
    *   *Option A*: Raspberry Pi Camera Module 3 (connected via CSI-2 flex cable).
    *   *Option B*: Standard USB Web Camera (UVC-compliant) plugged into a USB 3.0 port.

---

## 🛠️ Step 1: Clone the Project to Raspberry Pi

Open a terminal on your Raspberry Pi and clone your unified repository:

```bash
cd ~
git clone https://github.com/Dakshina9319/dashboard-knitx.git
cd dashboard-knitx
```

---

## 📦 Step 2: Install System Dependencies

RPi OS is Debian-based. OpenCV and other libraries require specific system dependencies. Run the following command to install them:

```bash
sudo apt update && sudo apt install -y \
    python3-pip \
    python3-venv \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    sqlite3
```

---

## 🐍 Step 3: Setup Python Virtual Environment

Since RPi OS Bookworm enforces **PEP 668** (externally managed environments), you **must** use a virtual environment:

1.  Create the virtual environment inside the `backend` directory:
    ```bash
    cd ~/dashboard-knitx/backend
    python3 -m venv .venv
    ```
2.  Activate the virtual environment:
    ```bash
    source .venv/bin/activate
    ```
3.  Upgrade package installers:
    ```bash
    pip install --upgrade pip setuptools wheel
    ```
4.  Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```

> [!NOTE]
> For optimal Edge-AI inference on RPi 5's ARM Cortex-A76 CPU, we recommend installing **ONNX Runtime** instead of heavy PyTorch. ONNX Runtime is extremely lightweight and achieves **15–20 FPS** on RPi 5 CPU:
> ```bash
> pip install onnxruntime
> ```

---

## ⚙️ Step 4: Run the Backend Bridge Server

1.  Make sure you are inside `~/dashboard-knitx/backend` and your virtual environment is active (`source .venv/bin/activate`).
2.  Start the bridge server:
    ```bash
    python3 main_server.py --port 5000 --camera 0
    ```
    *   `--port 5000`: Runs the HTTP status and process API on port 5000.
    *   `--camera 0`: Camera index (0 is usually the first CSI or USB camera). Change it if your camera is registered on another index (e.g. `1` or `/dev/video0`).

---

## 🖥️ Step 5: Run/Host the HMI Dashboard

You have two ways to load the HMI Dashboard on the RPi 5:

### Option A: Use the GitHub Pages Hosted Dashboard (Recommended)
You do **not** need to run any frontend server on the Pi. Simply open the built-in Chromium browser on the Raspberry Pi and navigate to your public GitHub URL:
👉 **[https://dakshina9319.github.io/dashboard-knitx/](https://dakshina9319.github.io/dashboard-knitx/)**

*The hosted page running in your Pi's browser will auto-detect the local Python backend running on `http://localhost:5000` and stream the camera immediately.*

### Option B: Host the Frontend Locally on the Pi
If you want to run the frontend completely offline without internet access:
1.  Open a new terminal tab.
2.  Navigate to the `frontend/` directory:
    ```bash
    cd ~/dashboard-knitx/frontend
    ```
3.  Launch a local server on port `3000`:
    ```bash
    python3 -m http.server 3000
    ```
4.  Open Chromium on your Pi and visit:
    👉 **`http://localhost:3000`**

---

## ⚡ Step 6: Edge Optimization Tips for RPi 5 (4GB)

To get the absolute highest frame rates and lowest latency on your 4GB RPi 5:

1.  **Use ONNX format models (`.onnx`)**: Avoid PyTorch (`.pt`) model files on the RPi. ONNX models are highly optimized for CPU math. Export your YOLO model to ONNX:
    ```bash
    # Run on your development PC to export:
    yolo export model=knitx_best.pt format=onnx imgsz=640
    ```
    Copy the `knitx_best.onnx` file to the Pi under `backend/models/` and update your config in `config/knitx_config.yaml` to point to it.
2.  **Enable Active Cooling**: The RPi 5 Cortex-A76 CPU runs YOLO inference very fast, but will thermal-throttle (slow down) if it exceeds 80°C. Using the active cooler keeps it under 60°C, maintaining a solid **15+ FPS** indefinitely.
3.  **Optimize Camera Input Size**: Set the preprocessed resolution in `config/knitx_config.yaml` to `640x480` or `320x240`. Downscaling the input frame before feeding it into the YOLO model drastically cuts down the inference latency.
