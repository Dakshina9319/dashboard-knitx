from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cloud_storage.providers import GoogleDriveStorageProvider, LocalStorageProvider, _date_folder_name
from reports.qr_generator import generate_qr_report


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeFiles:
    def __init__(self, names):
        self.names = names

    def list(self, **_kwargs):
        return _FakeExecute({"files": [{"name": name} for name in self.names]})


class _FakeService:
    def __init__(self, names):
        self._files = _FakeFiles(names)

    def files(self):
        return self._files


class CloudStorageTests(unittest.TestCase):
    def test_date_folder_name_uses_configured_industrial_format(self):
        self.assertEqual(_date_folder_name("2026-05-27 09:15:00", "%d-%m-%Y"), "27-05-2026")

    def test_local_storage_provider_keeps_existing_local_flow(self):
        provider = LocalStorageProvider()
        result = provider.upload_report_bundle(
            report_path="report.pdf",
            qr_path="qr.png",
            json_path="report.json",
            proof_paths=[],
            started_at="2026-05-27 09:15:00",
        )
        self.assertIsNone(result)

    def test_google_drive_order_folder_uses_next_number(self):
        provider = object.__new__(GoogleDriveStorageProvider)
        provider.service = _FakeService(["1", "2", "notes", "4"])
        self.assertEqual(provider._next_order_folder_name("date-folder-id"), "5")

    def test_qr_report_json_contains_url_only_qr_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_url = "https://tinyurl.com/knitx-poc"
            _pdf_path, _qr_path, json_path = generate_qr_report(
                report_dir=tmpdir,
                session_id="KNITX_TEST",
                roll_id="ROLL_001",
                gsm=202,
                roll_weight_kg=110.8,
                total_defects=0,
                total_points=0,
                points_per_100_sq_yards=0,
                final_grade="ACCEPT",
                timestamp="2026-05-27 09:15:00",
                defects=[],
                qr_text=report_url,
                report_url=report_url,
                storage_provider="google_drive",
                cloud_folder_url="https://drive.google.com/drive/folders/folder-id",
            )
            payload = json.loads(Path(json_path).read_text(encoding="utf-8"))

        self.assertEqual(payload["qr_text"], report_url)
        self.assertEqual(payload["pdf_report"], report_url)
        self.assertEqual(payload["storage_provider"], "google_drive")
        self.assertEqual(payload["gsm"], 202)
        self.assertEqual(payload["roll_weight_kg"], 110.8)


if __name__ == "__main__":
    unittest.main()
