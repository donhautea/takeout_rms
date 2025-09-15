# ----------------------------------
#   Google Drive helper utilities
# ----------------------------------
# ⚠️ Make sure you have the following in requirements.txt:
#   google-api-python-client
#   google-auth
#   google-auth-httplib2
# ----------------------------------

import io
import os
import mimetypes
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
# Drive API: we only need read/write access to the user’s files.
SCOPES: List[str] = [
    "https://www.googleapis.com/auth/drive"
]


# -------------------------------------------------------------------
# Internals – imports that require optional packages.
# The helper is kept local so that the module still loads even if
# the Google packages aren’t installed (e.g. during unit‑testing).
# -------------------------------------------------------------------
def _google_deps() -> Tuple[
    Any,
    Any,
    Any,
    Any,
]:
    """
    Lazily import the Google APIs. Raises RuntimeError if the
    dependencies are missing, with a helpful message.

    Returns:
        service_account:  google.oauth2.service_account
        build:            googleapiclient.discovery.build
        MediaFileUpload:  googleapiclient.http.MediaFileUpload
        MediaIoBaseDownload: googleapiclient.http.MediaIoBaseDownload
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

        return service_account, build, MediaFileUpload, MediaIoBaseDownload

    except ImportError as exc:
        raise RuntimeError(
            "Google Drive features unavailable. "
            "Add the following to your requirements.txt: "
            "google-api-python-client, google-auth, google-auth-httplib2"
        ) from exc


# -------------------------------------------------------------------
# Credentials & Service
# -------------------------------------------------------------------
def _credentials() -> Any:
    """
    Build the service‑account credentials from Streamlit secrets.

    ``st.secrets["gdrive_service_account"]`` must contain a JSON object
    (the same you download from Google Cloud IAM / Service Accounts).
    """
    service_account, *_ = _google_deps()
    sa_info = dict(st.secrets["gdrive_service_account"])
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return credentials


def _service() -> Any:
    """
    Return the Drive v3 service object.
    """
    _, build, *_ = _google_deps()
    creds = _credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# -------------------------------------------------------------------
# Core helpers
# -------------------------------------------------------------------
def probe_folder(folder_id: str) -> Tuple[bool, Any]:
    """
    Quick existence check for a folder.
    Returns (True, metadata) on success or (False, exception) on failure.
    """
    svc = _service()
    try:
        meta = svc.files().get(
            fileId=folder_id,
            fields="id,name,mimeType,driveId",
            supportsAllDrives=True,
        ).execute()
        return True, meta
    except Exception as err:
        return False, err


def list_files(folder_id: str) -> List[Dict[str, Any]]:
    """
    Return a list of all non‑trashed files in *folder_id*, sorted by
    modified time descending.
    """
    svc = _service()
    all_files: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        resp = svc.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, md5Checksum)",
            orderBy="modifiedTime desc",
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        all_files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return all_files


def get_file_meta(file_id: str) -> Dict[str, Any]:
    """
    Return the full metadata of a file.
    """
    svc = _service()
    return svc.files().get(
        fileId=file_id,
        fields="id, name, mimeType, size, modifiedTime, md5Checksum, parents, driveId",
        supportsAllDrives=True,
    ).execute()


def find_file_by_name(name: str, folder_id: str) -> Optional[Dict[str, Any]]:
    """
    Return the first file that matches *name* in the given folder,
    or None if no match is found.
    """
    svc = _service()

    # Escape single quotes in the name for the Drive query string.
    escaped_name = name.replace("'", "\\'")
    query = (
        f"name = '{escaped_name}' "
        f"and '{folder_id}' in parents "
        "and trashed = false"
    )

    res = svc.files().list(
        q=query,
        fields="files(id, name, mimeType, size, modifiedTime, md5Checksum)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = res.get("files", [])
    return files[0] if files else None


# -------------------------------------------------------------------
# Upload & Download helpers
# -------------------------------------------------------------------
def upload_file(local_path: str, folder_id: str, overwrite: bool = True) -> str:
    """
    Upload *local_path* to Drive under *folder_id*.
    If a file with the same name already exists and *overwrite* is True,
    it will be updated.
    Returns the Drive file ID.
    """
    _, _, MediaFileUpload, _ = _google_deps()
    svc = _service()

    file_name = os.path.basename(local_path)
    mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    # Check for an existing file first
    existing = find_file_by_name(file_name, folder_id)
    media_body = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

    if existing and overwrite:
        svc.files().update(
            fileId=existing["id"],
            media_body=media_body,
            supportsAllDrives=True,
        ).execute()
        return existing["id"]

    # Create a new file
    meta = {"name": file_name, "parents": [folder_id]}
    created = svc.files().create(
        body=meta, media_body=media_body, fields="id", supportsAllDrives=True
    ).execute()
    return created["id"]


def download_file(file_id: str, local_path: str) -> str:
    """
    Download a Drive file into *local_path*.
    Returns the path that was written.
    """
    svc = _service()
    _, _, _, MediaIoBaseDownload = _google_deps()

    request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)

    with io.BytesIO() as file_buffer:
        downloader = MediaIoBaseDownload(file_buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(local_path, "wb") as fh:
            fh.write(file_buffer.getvalue())

    return local_path
