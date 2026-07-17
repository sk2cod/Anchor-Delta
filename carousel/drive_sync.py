"""
Google Drive upload for the Approve & Sync export path (Stage 3 —
INFRA_DECISIONS.md #02).

User-delegated OAuth2 via a long-lived refresh token, not a service
account: personal Gmail accounts give service accounts 0GB of Drive
storage quota, so a service-account upload would fail outright regardless
of code correctness. Scope is drive.file — this app can only ever see or
manage files/folders it created itself, never the pre-existing local
"Outbox" folder used by CAROUSEL_SYNC_DIR, which is why a new
"Anchor & Delta - Railway" folder is created rather than reusing that one.

Only carousel/assembler.py calls into this module, and only when all
three GOOGLE_OAUTH_* env vars are present — see export_carousel()'s
_drive_configured() check. Never imported at module load time by anything
else, so a missing google-auth/google-api-python-client install can't
break the app for users who aren't using Drive sync.
"""

import logging
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_FOLDER_NAME = "Anchor & Delta - Railway"


class DriveSyncError(Exception):
    pass


def _get_credentials() -> Credentials:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise DriveSyncError(
            "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and "
            "GOOGLE_OAUTH_REFRESH_TOKEN must all be set to use Drive sync."
        )

    # token=None, no expiry set — Credentials.valid is False until the
    # first request, at which point google-api-python-client's transport
    # calls credentials.refresh() automatically using refresh_token. No
    # browser/consent interaction happens here or ever again after the
    # one-time scripts/get_drive_refresh_token.py run.
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )


def _get_service():
    credentials = _get_credentials()
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def get_or_create_folder() -> str:
    """
    Return the Drive folder ID to upload into.

    Reads GOOGLE_DRIVE_FOLDER_ID if set. Otherwise creates a new folder
    named DRIVE_FOLDER_NAME via the Drive API and logs the new ID clearly
    so it can be saved as GOOGLE_DRIVE_FOLDER_ID for future runs — without
    that, every run with the env var still unset creates another new
    folder rather than reusing the last one.
    """
    existing_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if existing_id:
        return existing_id

    service = _get_service()
    file_metadata = {
        "name": DRIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=file_metadata, fields="id").execute()
    folder_id = folder["id"]

    message = (
        f"Created new Google Drive folder '{DRIVE_FOLDER_NAME}' "
        f"(id={folder_id}). Add this to your .env / Railway env vars as "
        f"GOOGLE_DRIVE_FOLDER_ID={folder_id} so future runs reuse it "
        f"instead of creating a new folder every time."
    )
    logger.warning(message)
    print(f"\n{message}\n")

    return folder_id


def upload_bundle(bundle_dir: Path, folder_id: str) -> list[str]:
    """
    Upload every file in bundle_dir into the given Drive folder ID,
    preserving filenames. Returns the uploaded Drive file IDs, in the
    same order as bundle_dir's sorted directory listing.
    """
    service = _get_service()
    uploaded_ids = []

    for path in sorted(Path(bundle_dir).iterdir()):
        if not path.is_file():
            continue
        file_metadata = {"name": path.name, "parents": [folder_id]}
        media = MediaFileUpload(str(path), resumable=False)
        uploaded = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        uploaded_ids.append(uploaded["id"])

    return uploaded_ids
