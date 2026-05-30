from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen


DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


@dataclass(frozen=True)
class CloudUploadResult:
    report_url: str
    qr_url: str
    json_url: str
    folder_url: str
    folder_id: str
    qr_text: str
    storage_provider: str


@dataclass(frozen=True)
class UploadedFile:
    file_id: str
    name: str
    web_view_link: str


class LocalStorageProvider:
    provider_name = "local"

    def upload_report_bundle(
        self,
        *,
        report_path: str,
        qr_path: str,
        json_path: str,
        proof_paths: list[str],
        started_at: str,
    ) -> CloudUploadResult | None:
        return None


class GoogleDriveStorageProvider:
    provider_name = "google_drive"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.storage_config = config.get("storage", {})
        self.drive_config = self.storage_config.get("google_drive", {})
        self.service = self._build_service()

    def upload_report_bundle(
        self,
        *,
        report_path: str,
        qr_path: str,
        json_path: str,
        proof_paths: list[str],
        started_at: str,
    ) -> CloudUploadResult:
        folder_id = self._prepare_destination_folder(started_at)
        report = self._upload_file(report_path, folder_id, "application/pdf")
        self._share_anyone_reader(report.file_id)
        report_url = self._shorten_url(report.web_view_link)

        qr = self._upload_file(qr_path, folder_id, "image/png")
        json_file = self._upload_file(json_path, folder_id, "application/json")
        for proof_path in proof_paths:
            path = Path(proof_path)
            if path.exists():
                self._upload_file(str(path), folder_id, "image/jpeg")

        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
        return CloudUploadResult(
            report_url=report_url,
            qr_url=qr.web_view_link,
            json_url=json_file.web_view_link,
            folder_url=folder_url,
            folder_id=folder_id,
            qr_text=report_url,
            storage_provider=self.provider_name,
        )

    def update_report_links(
        self,
        *,
        result: CloudUploadResult,
        report_path: str,
        qr_path: str,
        json_path: str,
    ) -> CloudUploadResult:
        report = self._find_child_file(Path(report_path).name, result.folder_id)
        qr = self._find_child_file(Path(qr_path).name, result.folder_id)
        json_file = self._find_child_file(Path(json_path).name, result.folder_id)

        if report:
            self._update_file(report.file_id, report_path, "application/pdf")
        if qr:
            qr = self._update_file(qr.file_id, qr_path, "image/png")
        if json_file:
            json_file = self._update_file(json_file.file_id, json_path, "application/json")

        return CloudUploadResult(
            report_url=result.report_url,
            qr_url=(qr.web_view_link if qr else result.qr_url),
            json_url=(json_file.web_view_link if json_file else result.json_url),
            folder_url=result.folder_url,
            folder_id=result.folder_id,
            qr_text=result.qr_text,
            storage_provider=result.storage_provider,
        )

    def _build_service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Drive storage requires google-api-python-client, "
                "google-auth-oauthlib, and google-auth-httplib2."
            ) from exc

        credentials_path = Path(str(self.drive_config.get("credentials_path", "config/google_drive_credentials.json")))
        token_path = Path(str(self.drive_config.get("token_path", "data/google_drive_token.json")))
        credentials = None

        if token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google Drive credentials file not found: {credentials_path}. "
                    "Create an OAuth desktop client in Google Cloud and save it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), DRIVE_SCOPES)
            credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return build("drive", "v3", credentials=credentials)

    def _prepare_destination_folder(self, started_at: str) -> str:
        parent_id = self._resolve_parent_folder()
        folder_mode = str(self.storage_config.get("folder_mode", "auto_date_order"))
        if folder_mode == "custom":
            custom_name = str(self.storage_config.get("custom_folder_name", "KnitX Reports")).strip() or "KnitX Reports"
            base_id = self._ensure_folder(custom_name, parent_id)
        else:
            date_name = _date_folder_name(started_at, str(self.storage_config.get("date_folder_format", "%d-%m-%Y")))
            base_id = self._ensure_folder(date_name, parent_id)
        order_name = self._next_order_folder_name(base_id)
        return self._ensure_folder(order_name, base_id)

    def _resolve_parent_folder(self) -> str:
        folder_id = str(self.drive_config.get("parent_folder_id", "")).strip()
        if folder_id:
            return folder_id
        folder_name = str(self.drive_config.get("parent_folder_name", "KnitX Reports")).strip()
        if not folder_name:
            return "root"
        existing = self._find_folder(folder_name, "root")
        if existing:
            return existing
        if bool(self.drive_config.get("create_parent_folder", True)):
            return self._create_folder(folder_name, "root")
        raise FileNotFoundError(f"Google Drive parent folder not found: {folder_name}")

    def _ensure_folder(self, name: str, parent_id: str) -> str:
        existing = self._find_folder(name, parent_id)
        if existing:
            return existing
        return self._create_folder(name, parent_id)

    def _next_order_folder_name(self, parent_id: str) -> str:
        query = (
            f"mimeType='{DRIVE_FOLDER_MIME_TYPE}' and "
            f"'{_escape_query_value(parent_id)}' in parents and trashed=false"
        )
        response = self.service.files().list(q=query, fields="files(name)", pageSize=1000).execute()
        numbers = []
        for item in response.get("files", []):
            name = str(item.get("name", ""))
            if name.isdigit():
                numbers.append(int(name))
        return str((max(numbers) if numbers else 0) + 1)

    def _find_folder(self, name: str, parent_id: str) -> str | None:
        query = (
            f"name='{_escape_query_value(name)}' and mimeType='{DRIVE_FOLDER_MIME_TYPE}' and "
            f"'{_escape_query_value(parent_id)}' in parents and trashed=false"
        )
        response = self.service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
        files = response.get("files", [])
        return str(files[0]["id"]) if files else None

    def _create_folder(self, name: str, parent_id: str) -> str:
        metadata = {"name": name, "mimeType": DRIVE_FOLDER_MIME_TYPE, "parents": [parent_id]}
        folder = self.service.files().create(body=metadata, fields="id").execute()
        return str(folder["id"])

    def _find_child_file(self, name: str, parent_id: str) -> UploadedFile | None:
        query = f"name='{_escape_query_value(name)}' and '{_escape_query_value(parent_id)}' in parents and trashed=false"
        response = self.service.files().list(q=query, fields="files(id, name, webViewLink)", pageSize=1).execute()
        files = response.get("files", [])
        if not files:
            return None
        item = files[0]
        return UploadedFile(str(item["id"]), str(item["name"]), str(item.get("webViewLink", "")))

    def _upload_file(self, path: str, parent_id: str, mimetype: str) -> UploadedFile:
        from googleapiclient.http import MediaFileUpload

        file_path = Path(path)
        metadata = {"name": file_path.name, "parents": [parent_id]}
        media = MediaFileUpload(str(file_path), mimetype=mimetype, resumable=True)
        item = self.service.files().create(
            body=metadata,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
        return UploadedFile(str(item["id"]), str(item["name"]), str(item.get("webViewLink", "")))

    def _update_file(self, file_id: str, path: str, mimetype: str) -> UploadedFile:
        from googleapiclient.http import MediaFileUpload

        file_path = Path(path)
        media = MediaFileUpload(str(file_path), mimetype=mimetype, resumable=True)
        item = self.service.files().update(
            fileId=file_id,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
        return UploadedFile(str(item["id"]), str(item.get("name", file_path.name)), str(item.get("webViewLink", "")))

    def _share_anyone_reader(self, file_id: str) -> None:
        permission = {"type": "anyone", "role": "reader"}
        self.service.permissions().create(fileId=file_id, body=permission, fields="id").execute()

    def _shorten_url(self, url: str) -> str:
        shortener = str(self.storage_config.get("shortener", "tinyurl_legacy"))
        if shortener in ("", "none", "disabled"):
            return url
        if shortener != "tinyurl_legacy":
            return url
        try:
            endpoint = f"https://tinyurl.com/api-create.php?url={quote(url, safe='')}"
            with urlopen(endpoint, timeout=6) as response:
                shortened = response.read().decode("utf-8").strip()
            if shortened.startswith("http"):
                return shortened
        except Exception:
            return url
        return url


def build_storage_provider(config: dict[str, Any]):
    provider = str(config.get("storage", {}).get("provider", "local")).strip().lower()
    if provider == "google_drive":
        return GoogleDriveStorageProvider(config)
    return LocalStorageProvider()


def _date_folder_name(started_at: str, date_format: str) -> str:
    candidates = (
        (started_at[:19], "%Y-%m-%d %H:%M:%S"),
        (started_at[:10], "%Y-%m-%d"),
    )
    for value, fmt in candidates:
        try:
            return datetime.strptime(value, fmt).strftime(date_format)
        except ValueError:
            continue
    return datetime.now().strftime(date_format)


def _escape_query_value(value: str) -> str:
    return str(value).replace("'", "\\'")
