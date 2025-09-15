import os, io, mimetypes
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Use broader scope to allow listing + updates in the shared folder.
SCOPES = ["https://www.googleapis.com/auth/drive"]

def _credentials():
    sa_info = dict(st.secrets["gdrive_service_account"])
    return service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)

def _service():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def _escape_drive_literal(s: str) -> str:
    # IMPORTANT: escape backslashes first, then single quotes
    return s.replace("\\", "\\\\").replace("'", "\\'")

def upload_file(local_path: str, folder_id: str, overwrite: bool = True) -> str:
    """Upload file to Drive folder. If overwrite=True and name exists, update it."""
    svc = _service()  # assumed defined elsewhere
    name = os.path.basename(local_path)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    # Find existing by name within folder (non-trashed, non-folder)
    safe_name = _escape_drive_literal(name)
    q = (
        f"name = '{safe_name}' "
        f"and '{folder_id}' in parents "
        f"and mimeType != 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    existing = (
        svc.files()
           .list(q=q, fields="files(id, name)", pageSize=10)
           .execute()
           .get("files", [])
    )

    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)

    # If an existing file is found and overwrite=True, update the first match
    if existing and overwrite:
        file_id = existing[0]["id"]
        svc.files().update(fileId=file_id, media_body=media).execute()
        return file_id

    # Otherwise, create a new file in the folder
    meta = {"name": name, "parents": [folder_id]}
    created = svc.files().create(body=meta, media_body=media, fields="id").execute()
    return created["id"]


def list_files(folder_id: str):
    svc = _service()
    q = f"'{folder_id}' in parents and trashed = false"
    files = []
    page_token = None
    while True:
        resp = svc.files().list(
            q=q,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            orderBy="modifiedTime desc",
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files

def download_file(file_id: str, local_path: str):
    svc = _service()
    req = svc.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    with open(local_path, "wb") as f:
        f.write(fh.getvalue())
    return local_path

def find_file_by_name(name: str, folder_id: str):
    """Return the most recently modified file with exact name in the folder, or None."""
    svc = _service()

    safe_name = _escape_drive_literal(name)
    q = (
        f"name = '{safe_name}' "
        f"and '{folder_id}' in parents "
        f"and mimeType != 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
