# KnitX-Ultra HMI & Edge-AI Inspection Project

This repository contains the complete unified codebase for **KnitX-Ultra**, an advanced, Figma-aligned Edge-AI Knitted Fabric Quality Inspection platform.

## 📂 Project Structure

This is structured as a monorepo containing both the frontend and backend systems:

*   **`frontend/`**: The modern, high-fidelity Figma-aligned HMI Console dashboard (HTML/CSS/JS).
*   **`backend/`**: The Edge-AI Python processing bridge server, integrating ONNX model inference (YOLOv8) with conveyor simulations, camera captures, and SQLite/Google Drive storage syncing.

---

## 🚀 How to Run the Project Locally

To run the complete system locally on your computer, follow these simple setup steps:

### 1. Start the Edge-AI Backend Bridge Server
1.  Navigate into the `backend/` directory:
    ```bash
    cd backend
    ```
2.  Activate the local virtual environment (if not already active):
    *   **Windows (PowerShell):**
        ```powershell
        .venv\Scripts\Activate.ps1
        ```
    *   **Windows (CMD):**
        ```cmd
        .venv\Scripts\activate.bat
        ```
    *   **Linux/macOS:**
        ```bash
        source .venv/bin/activate
        ```
3.  Start the bridge integration server on port `5000`:
    ```bash
    python main_server.py --port 5000
    ```
    *You should see output indicating that the Bridge HMI integration server is listening at `http://localhost:5000`.*

### 2. Start the Frontend HMI Dashboard
1.  Open a new terminal window or tab.
2.  Navigate into the `frontend/` directory:
    ```bash
    cd frontend
    ```
3.  Start a local HTTP server on port `3000`:
    *   **Using Python:**
        ```bash
        python -m http.server 3000
        ```
    *   **Using Node/npm:**
        ```bash
        npx http-server -p 3000
        ```

---

## 🖥️ Viewing the Dashboard

1.  Open your web browser and go to:
    👉 **[http://localhost:3000](http://localhost:3000)**
2.  If this is your first time loading or if you recently made updates, perform a **hard refresh** (`Ctrl + Shift + R` or `Cmd + Shift + R`) to ensure all assets are freshly loaded.
3.  Login with the default administrator credentials:
    *   **Username:** `admin`
    *   **Password:** `admin123`
4.  Configure the **Inspection Setup** parameters when prompted and click **Start Inspection** to launch the realtime HMI analysis streams.

---

## 🛠️ Key Platform Features

*   **Figma-Matched HMI Console Layout**: Premium, professional dark HMI layout with responsive panels, tactile control bars, and real-time statuses.
*   **YOLO Edge-AI Fabric Defect Pipeline**: Real-time bounding box overrides, latency tracking, defect counts, penalty metrics, and grading scores.
*   **Tactile Workspace Dividers**: Built-in resizers for customizable center views, log feeds, and diagnostics displays.
*   **Google Drive Cloud Syncing & OAUTH 2.0**: Cloud sync simulation, document export, and SQLite integration.
