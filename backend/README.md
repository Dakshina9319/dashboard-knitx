<<<<<<< HEAD
# KnitX-ultra
=======
﻿# KnitX Industrial Fabric Inspection Runtime

KnitX is a modular edge-AI runtime for knitted fabric inspection with YOLO, OpenCV,
SQLite, QR reports, and 4-point textile grading.

This project is designed for two stages:

1. Develop and test in VS Code on Windows using image/video sources.
2. Deploy the same runtime on Raspberry Pi 5 with webcam/Pi camera input.

## Project Layout

```text
camera/                 Frame capture for image, video, and camera modes
opencv/                 Preprocessing, contour filtering, visualization
yolo/                   Replaceable YOLO model wrapper
measurement/            Pixel-to-mm/inch and 4-point rule calculation
database/               SQLite session, defect, and roll summary storage
reports/                QR and JSON report generation
cloud_storage/          Local and Google Drive report storage providers
utils/                  Config loading and multi-frame defect tracking
config/knitx_config.yaml
main.py
```

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Model Replacement

Default model path:

```text
models/knitx_best.pt
```

To replace the model, copy a new `.pt` file into `models/` and update:

```yaml
model:
  path: models/my_model.pt
```

The detector loads the model with:

```python
model = YOLO(config.model_path)
```

## Class Mapping

The GitHub reference repo uses:

```yaml
0: stain_or_spots
1: needle_line
2: holes
```

Because the old `test.py` swapped class `0` and `2`, this runtime keeps class remapping configurable:

```yaml
class_remap:
  enabled: true
  map:
    0: 2
    2: 0
```

Keep it on for the current model so `holes` and `stain_or_spots` are mapped correctly.

## Run Commands

Image:

```powershell
python main.py --mode image --source "C:\path\to\fabric.jpg" --no-display
```

Image folder:

```powershell
python main.py --mode image --source "C:\path\to\image_folder" --no-display
```

Video:

```powershell
python main.py --mode video --source "C:\path\to\inspection_video.mp4"
```

Webcam or Raspberry Pi camera through OpenCV:

```powershell
python main.py --mode camera --camera-index 0
```

GSM and roll weight are required for the 4-point formula. If you do not pass them, KnitX asks for them in the terminal before inspection starts.

Useful production overrides:

```powershell
python main.py --mode video --source "roll.mp4" --roll ROLL_57688 --gsm 202 --roll-weight 110.8 --mm-per-pixel 0.20
```

## Google Drive Reports

Local report output remains the default. To save reports to Google Drive, create a Google OAuth desktop client and save its downloaded JSON as:

```text
config/google_drive_credentials.json
```

Then run with Google Drive enabled. The first run opens a browser sign-in and stores the token in `data/google_drive_token.json`.

```powershell
python main.py --mode image --source "fabric.jpg" --no-display --storage-provider google_drive --drive-parent-folder-name "Factory Reports"
```

If the OAuth JSON is saved somewhere else, point KnitX to it:

```powershell
python main.py --mode image --source "fabric.jpg" --no-display --storage-provider google_drive --drive-credentials-path "C:\path\to\client_secret.json"
```

The operator can choose the Drive destination in two ways:

```powershell
python main.py --storage-provider google_drive --drive-parent-folder-id "DRIVE_FOLDER_ID"
python main.py --storage-provider google_drive --drive-parent-folder-name "Factory Reports"
```

By default, KnitX creates folders like:

```text
Factory Reports/27-05-2026/1/
Factory Reports/27-05-2026/2/
```

For a custom folder name:

```powershell
python main.py --storage-provider google_drive --folder-mode custom --cloud-folder-name "Trial Batch A"
```

The final QR stores only the shared report URL, so it opens the report directly with no TinyURL hop. Use `--disable-url-shortener` if you later turn shortening back on for your own domain.

## Outputs

```text
data/database/knitx_inspection.db
data/defect_images/
data/reports/
```

SQLite stores metadata only. Defect proof images, PDF reports, JSON data, and QR reports are saved as local files by default. In Google Drive mode, KnitX also uploads the report bundle to the selected Drive folder, shares the PDF as anyone-with-link can view, and stores the cloud report links in `roll_summary`.

Each confirmed defect saves a proof bundle:

```text
01_defect_crop.jpg
02_original_frame.jpg
03_yolo_annotated.jpg
04_opencv_threshold.jpg
05_mask_overlay.jpg
```

The final QR image points to the report URL only, so the QR stays compact enough for small industrial stickers. The PDF contains the inspection summary plus these proof images.

## 4-Point Calculation

The measurement workflow is intentionally direct:

1. YOLO detects defect.
2. Runtime reads bounding box width and height.
3. Pixels convert to mm and inch using `mm_per_pixel`.
4. Largest defect dimension receives 4-point score.
5. Defect record is stored in SQLite.
6. Visualization is rendered.
7. QR report is generated.

Rules:

```text
0-3 inch  = 1 point
3-6 inch  = 2 points
6-9 inch  = 3 points
>9 inch   = 4 points
```

Roll grading:

```text
points / 100 sq yards = (total_points * GSM * 0.083) / roll_weight
<= 20  ACCEPT
<= 40  SECOND QUALITY
> 40   REJECT
```

## Raspberry Pi Notes

- Use the same project folder and config file.
- Set `model.device: cpu` unless you add an accelerator.
- Keep `model.image_size` at `640` for low latency.
- Calibrate `mm_per_pixel` with a physical ruler under the mounted camera.
- Keep lighting fixed and shielded to reduce false positives.
>>>>>>> 0d05c02 (Initial commit: project files)
