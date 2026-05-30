from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps
import qrcode


PAGE_SIZE = (1240, 1754)
MARGIN = 70


def generate_qr_report(
    report_dir: str,
    session_id: str,
    roll_id: str,
    gsm: float,
    roll_weight_kg: float,
    total_defects: int,
    total_points: int,
    points_per_100_sq_yards: float,
    final_grade: str,
    timestamp: str,
    defects: list[dict[str, Any]],
    qr_text: str | None = None,
    report_url: str | None = None,
    json_url: str | None = None,
    storage_provider: str = "local",
    cloud_folder_url: str | None = None,
) -> tuple[str, str, str]:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / f"{session_id}_inspection_report.pdf"
    json_path = output_dir / f"{session_id}_report.json"
    qr_path = output_dir / f"{session_id}_qr.png"

    effective_report_url = report_url or str(pdf_path)
    effective_json_url = json_url or str(json_path)
    effective_qr_text = qr_text or effective_report_url

    report_payload = {
        "system": "KnitX",
        "session_id": session_id,
        "roll_id": roll_id,
        "gsm": gsm,
        "roll_weight_kg": roll_weight_kg,
        "total_defects": total_defects,
        "total_points": total_points,
        "points_per_100_sq_yards": points_per_100_sq_yards,
        "final_grade": final_grade,
        "timestamp": timestamp,
        "storage_provider": storage_provider,
        "cloud_folder_url": cloud_folder_url,
        "pdf_report": effective_report_url,
        "json_report": effective_json_url,
        "qr_text": effective_qr_text,
        "defects": [
            {
                "type": row["defect_type"],
                "confidence": round(float(row["confidence"]), 3),
                "size_inch": round(float(row["size_inch"]), 2),
                "points": int(row["points"]),
                "image_path": row["image_path"],
                "proof_paths": _parse_proof_paths(row.get("proof_paths")),
            }
            for row in defects[-20:]
        ],
    }

    json_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    generate_url_qr(effective_qr_text, qr_path)
    _generate_pdf(
        pdf_path=pdf_path,
        qr_path=qr_path,
        session_id=session_id,
        roll_id=roll_id,
        gsm=gsm,
        roll_weight_kg=roll_weight_kg,
        total_defects=total_defects,
        total_points=total_points,
        points_per_100_sq_yards=points_per_100_sq_yards,
        final_grade=final_grade,
        timestamp=timestamp,
        defects=defects,
        json_path=json_path,
        report_url=effective_report_url,
        json_url=effective_json_url,
        cloud_folder_url=cloud_folder_url,
        storage_provider=storage_provider,
    )
    return str(pdf_path), str(qr_path), str(json_path)


def generate_url_qr(text: str, qr_path: str | Path) -> None:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(qr_path)


def _generate_pdf(
    pdf_path: Path,
    qr_path: Path,
    session_id: str,
    roll_id: str,
    gsm: float,
    roll_weight_kg: float,
    total_defects: int,
    total_points: int,
    points_per_100_sq_yards: float,
    final_grade: str,
    timestamp: str,
    defects: list[dict[str, Any]],
    json_path: Path,
    report_url: str,
    json_url: str,
    cloud_folder_url: str | None,
    storage_provider: str,
) -> None:
    pages: list[Image.Image] = []
    pages.append(
        _cover_page(
            qr_path=qr_path,
            session_id=session_id,
            roll_id=roll_id,
            gsm=gsm,
            roll_weight_kg=roll_weight_kg,
            total_defects=total_defects,
            total_points=total_points,
            points_per_100_sq_yards=points_per_100_sq_yards,
            final_grade=final_grade,
            timestamp=timestamp,
            json_path=json_path,
            pdf_path=pdf_path,
            report_url=report_url,
            json_url=json_url,
            cloud_folder_url=cloud_folder_url,
            storage_provider=storage_provider,
        )
    )

    if not defects:
        pages.append(_blank_message_page("No defects were confirmed in this inspection session."))
    else:
        for index, defect in enumerate(defects, start=1):
            pages.append(_defect_page(index, defect))

    first, rest = pages[0], pages[1:]
    first.save(pdf_path, save_all=True, append_images=rest, resolution=150)


def _cover_page(
    qr_path: Path,
    session_id: str,
    roll_id: str,
    gsm: float,
    roll_weight_kg: float,
    total_defects: int,
    total_points: int,
    points_per_100_sq_yards: float,
    final_grade: str,
    timestamp: str,
    json_path: Path,
    pdf_path: Path,
    report_url: str,
    json_url: str,
    cloud_folder_url: str | None,
    storage_provider: str,
) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    heading_font = _font(28, bold=True)
    body_font = _font(23)
    small_font = _font(18)

    _header(draw, "KnitX Industrial Fabric Inspection Report")
    draw.text((MARGIN, 170), "Inspection Summary", fill=(20, 20, 20), font=heading_font)

    rows = [
        ("Session ID", session_id),
        ("Roll ID", roll_id),
        ("Inspection Time", timestamp),
        ("Fabric GSM", str(gsm)),
        ("Roll Weight", f"{roll_weight_kg} kg"),
        ("Total Defects", str(total_defects)),
        ("Total Points", str(total_points)),
        ("Points / 100 sq yards", str(points_per_100_sq_yards)),
        ("Final Result", final_grade),
        ("Storage", storage_provider),
    ]
    y = 235
    for label, value in rows:
        draw.text((MARGIN, y), f"{label}:", fill=(70, 70, 70), font=body_font)
        draw.text((390, y), value, fill=_grade_color(final_grade) if label == "Final Result" else (20, 20, 20), font=body_font)
        y += 48

    draw.text((MARGIN, y + 35), "4-Point Rule", fill=(20, 20, 20), font=heading_font)
    rules = [
        "0-3 inch defect = 1 point",
        "3-6 inch defect = 2 points",
        "6-9 inch defect = 3 points",
        ">9 inch defect = 4 points",
        "Grade formula = (total points x GSM x 0.083) / roll weight",
    ]
    for rule in rules:
        y += 45
        draw.text((MARGIN, y + 35), rule, fill=(45, 45, 45), font=body_font)

    if qr_path.exists():
        qr = Image.open(qr_path).convert("RGB")
        qr = ImageOps.contain(qr, (260, 260))
        page.paste(qr, (PAGE_SIZE[0] - MARGIN - 260, 190))
        draw.text((PAGE_SIZE[0] - MARGIN - 280, 470), "Scan QR to open report", fill=(50, 50, 50), font=small_font)

    link_y = PAGE_SIZE[1] - 230
    draw.text((MARGIN, link_y), "PDF Report:", fill=(70, 70, 70), font=small_font)
    _draw_wrapped_text(draw, report_url or str(pdf_path), MARGIN, link_y + 30, small_font)
    draw.text((MARGIN, link_y + 82), "JSON Data:", fill=(70, 70, 70), font=small_font)
    _draw_wrapped_text(draw, json_url or str(json_path), MARGIN, link_y + 112, small_font)
    if cloud_folder_url:
        draw.text((MARGIN, link_y + 164), "Cloud Folder:", fill=(70, 70, 70), font=small_font)
        _draw_wrapped_text(draw, cloud_folder_url, MARGIN, link_y + 194, small_font)
    return page


def _defect_page(index: int, defect: dict[str, Any]) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    heading_font = _font(30, bold=True)
    body_font = _font(21)
    small_font = _font(17)

    _header(draw, f"Defect Evidence #{index}")

    summary = [
        ("Type", defect.get("defect_type", "")),
        ("Confidence", f"{float(defect.get('confidence', 0)):.3f}"),
        ("Size", f"{float(defect.get('size_inch', 0)):.2f} inch"),
        ("Width x Height", f"{float(defect.get('width_mm', 0)):.1f} mm x {float(defect.get('height_mm', 0)):.1f} mm"),
        ("Points", str(defect.get("points", ""))),
        ("Timestamp", defect.get("timestamp", "")),
    ]
    y = 145
    for label, value in summary:
        draw.text((MARGIN, y), f"{label}:", fill=(75, 75, 75), font=body_font)
        draw.text((270, y), str(value), fill=(20, 20, 20), font=body_font)
        y += 38

    proof_paths = _parse_proof_paths(defect.get("proof_paths"))
    image_slots = [
        ("Detected defect crop", proof_paths.get("defect_crop") or defect.get("image_path")),
        ("Original frame proof", proof_paths.get("original_frame")),
        ("YOLO annotated proof", proof_paths.get("yolo_annotated")),
        ("OpenCV threshold proof", proof_paths.get("opencv_threshold")),
        ("Mask overlay proof", proof_paths.get("mask_overlay")),
    ]

    draw.text((MARGIN, 410), "Visual Proof Images", fill=(20, 20, 20), font=heading_font)
    positions = [
        (MARGIN, 470, 510, 330),
        (660, 470, 510, 330),
        (MARGIN, 885, 510, 330),
        (660, 885, 510, 330),
        (MARGIN, 1300, 510, 330),
    ]
    for (title, path), (x, y, w, h) in zip(image_slots, positions):
        _draw_image_box(page, draw, title, path, x, y, w, h, small_font)

    return page


def _blank_message_page(message: str) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    _header(draw, "Defect Evidence")
    draw.text((MARGIN, 220), message, fill=(40, 40, 40), font=_font(28))
    return page


def _draw_image_box(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    title: str,
    path: str | None,
    x: int,
    y: int,
    w: int,
    h: int,
    font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, outline=(80, 80, 80), width=2, fill=(245, 245, 245))
    draw.text((x, y - 28), title, fill=(35, 35, 35), font=font)
    if not path or not Path(path).exists():
        draw.text((x + 18, y + 28), "Image not available", fill=(110, 110, 110), font=font)
        return
    try:
        image = Image.open(path).convert("RGB")
        image = ImageOps.contain(image, (w - 24, h - 24))
        page.paste(image, (x + (w - image.width) // 2, y + (h - image.height) // 2))
    except Exception as exc:
        draw.text((x + 18, y + 28), f"Could not load image: {exc}", fill=(150, 40, 40), font=font)


def _new_page() -> Image.Image:
    return Image.new("RGB", PAGE_SIZE, (255, 255, 255))


def _header(draw: ImageDraw.ImageDraw, title: str) -> None:
    draw.rectangle((0, 0, PAGE_SIZE[0], 100), fill=(26, 28, 30))
    draw.text((MARGIN, 30), title, fill=(245, 245, 245), font=_font(34, bold=True))
    draw.line((0, 100, PAGE_SIZE[0], 100), fill=(170, 170, 170), width=2)


def _draw_wrapped_text(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font: ImageFont.ImageFont) -> None:
    for line in textwrap.wrap(str(text), width=118)[:2]:
        draw.text((x, y), line, fill=(20, 20, 20), font=font)
        y += 24


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = ["arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _grade_color(grade: str) -> tuple[int, int, int]:
    if grade == "ACCEPT":
        return (35, 130, 60)
    if grade == "SECOND QUALITY":
        return (190, 125, 0)
    return (190, 30, 30)


def _parse_proof_paths(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return {str(k): str(v) for k, v in parsed.items()}
    return {}
