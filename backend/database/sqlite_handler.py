from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Any

from measurement.calculator import DefectMeasurement
from utils.tracker import TrackedDefect


class InspectionDatabase:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.database_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS inspection_sessions (
                session_id TEXT PRIMARY KEY,
                roll_id TEXT NOT NULL,
                gsm REAL NOT NULL,
                roll_weight_kg REAL NOT NULL,
                operator TEXT,
                machine_id TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                total_defects INTEGER DEFAULT 0,
                total_points INTEGER DEFAULT 0,
                points_per_100_sq_yards REAL DEFAULT 0,
                final_grade TEXT DEFAULT 'RUNNING'
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS defects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                roll_id TEXT NOT NULL,
                frame_number INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                defect_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                bbox_x1 INTEGER NOT NULL,
                bbox_y1 INTEGER NOT NULL,
                bbox_x2 INTEGER NOT NULL,
                bbox_y2 INTEGER NOT NULL,
                width_px INTEGER NOT NULL,
                height_px INTEGER NOT NULL,
                width_mm REAL NOT NULL,
                height_mm REAL NOT NULL,
                area_mm2 REAL NOT NULL,
                size_inch REAL NOT NULL,
                points INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                image_path TEXT NOT NULL,
                proof_paths TEXT,
                FOREIGN KEY(session_id) REFERENCES inspection_sessions(session_id)
            )
            """
        )
        self._ensure_column("defects", "proof_paths", "TEXT")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS roll_summary (
                session_id TEXT PRIMARY KEY,
                roll_id TEXT NOT NULL,
                total_defects INTEGER NOT NULL,
                total_points INTEGER NOT NULL,
                points_per_100_sq_yards REAL NOT NULL,
                final_grade TEXT NOT NULL,
                report_path TEXT,
                qr_path TEXT,
                storage_provider TEXT,
                cloud_folder_url TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES inspection_sessions(session_id)
            )
            """
        )
        self._ensure_column("roll_summary", "storage_provider", "TEXT")
        self._ensure_column("roll_summary", "cloud_folder_url", "TEXT")
        self.conn.commit()

    def start_session(self, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO inspection_sessions
            (session_id, roll_id, gsm, roll_weight_kg, operator, machine_id, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["session_id"],
                payload["roll_id"],
                payload["gsm"],
                payload["roll_weight_kg"],
                payload.get("operator"),
                payload.get("machine_id"),
                payload["started_at"],
            ),
        )
        self.conn.commit()

    def insert_defect(
        self,
        session_id: str,
        roll_id: str,
        frame_number: int,
        track: TrackedDefect,
        measurement: DefectMeasurement,
        timestamp: str,
        image_path: str,
        proof_paths: dict[str, str] | None = None,
    ) -> None:
        x1, y1, x2, y2 = track.bbox
        self.conn.execute(
            """
            INSERT INTO defects
            (session_id, roll_id, frame_number, track_id, defect_type, confidence,
             bbox_x1, bbox_y1, bbox_x2, bbox_y2,
             width_px, height_px, width_mm, height_mm, area_mm2, size_inch,
             points, timestamp, image_path, proof_paths)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                roll_id,
                frame_number,
                track.track_id,
                track.class_name,
                track.confidence,
                x1,
                y1,
                x2,
                y2,
                measurement.width_px,
                measurement.height_px,
                measurement.width_mm,
                measurement.height_mm,
                measurement.area_mm2,
                measurement.size_inch,
                measurement.points,
                timestamp,
                image_path,
                json.dumps(proof_paths or {}),
            ),
        )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def update_summary(
        self,
        session_id: str,
        roll_id: str,
        total_defects: int,
        total_points: int,
        points_per_100_sq_yards: float,
        final_grade: str,
        updated_at: str,
        report_path: str | None = None,
        qr_path: str | None = None,
        ended_at: str | None = None,
        storage_provider: str | None = None,
        cloud_folder_url: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE inspection_sessions
            SET ended_at = COALESCE(?, ended_at),
                total_defects = ?,
                total_points = ?,
                points_per_100_sq_yards = ?,
                final_grade = ?
            WHERE session_id = ?
            """,
            (ended_at, total_defects, total_points, points_per_100_sq_yards, final_grade, session_id),
        )
        self.conn.execute(
            """
            INSERT INTO roll_summary
            (session_id, roll_id, total_defects, total_points, points_per_100_sq_yards,
             final_grade, report_path, qr_path, storage_provider, cloud_folder_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                total_defects = excluded.total_defects,
                total_points = excluded.total_points,
                points_per_100_sq_yards = excluded.points_per_100_sq_yards,
                final_grade = excluded.final_grade,
                report_path = excluded.report_path,
                qr_path = excluded.qr_path,
                storage_provider = COALESCE(excluded.storage_provider, roll_summary.storage_provider),
                cloud_folder_url = COALESCE(excluded.cloud_folder_url, roll_summary.cloud_folder_url),
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                roll_id,
                total_defects,
                total_points,
                points_per_100_sq_yards,
                final_grade,
                report_path,
                qr_path,
                storage_provider,
                cloud_folder_url,
                updated_at,
            ),
        )
        self.conn.commit()

    def fetch_defects(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM defects WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.conn.close()
