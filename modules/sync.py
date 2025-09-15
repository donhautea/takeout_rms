# modules/sync.py
import os, time, stat, shutil, pathlib
from typing import Dict, Optional
from . import gdrive  # your existing Drive helper module

def _cleanup_sqlite_sidecars(db_path: str):
    for suf in ("-journal", "-wal", "-shm"):
        try:
            os.remove(db_path + suf)
        except FileNotFoundError:
            pass
        except PermissionError:
            pass

def _ensure_writable(path: str):
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IWRITE)
    except FileNotFoundError:
        pass
    except PermissionError:
        pass

def _safe_replace(src: str, dst: str, retries: int = 8, base_delay: float = 0.25):
    # Extra guard: fail fast with a helpful message if src is missing
    if not os.path.exists(src):
        raise FileNotFoundError(
            f"Download temp not found: {src}. "
            "Check gdrive.download_file() writes to the exact path and the app has write permission."
        )

    last_err = None
    for attempt in range(retries):
        try:
            _cleanup_sqlite_sidecars(dst)
            _ensure_writable(dst)
            os.replace(src, dst)  # atomic when it works
            return
        except PermissionError as e:
            last_err = e
            time.sleep(base_delay * (2 ** attempt))

    # Shadow-copy fallback
    tmp_shadow = dst + ".shadow_copy"
    try:
        _cleanup_sqlite_sidecars(dst)
        _ensure_writable(dst)
        shutil.copyfile(src, tmp_shadow)
        os.replace(tmp_shadow, dst)
        os.remove(src)
        return
    except Exception as e:
        raise last_err or e

def _local_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0.0

def _pick_remote_db(files: list, expected_name: Optional[str]) -> Optional[dict]:
    # Only consider .db files
    dbs = [f for f in files if str(f.get("name","")).lower().endswith(".db")]
    if not dbs:
        return None
    # Prefer exact filename match (same as local)
    if expected_name:
        for f in dbs:
            if f.get("name") == expected_name:
                return f
    # Else pick the newest by modifiedTimeEpoch (caller must populate this in list_files)
    return max(dbs, key=lambda f: float(f.get("modifiedTimeEpoch", 0) or 0))

def newest_wins_sync(local_db: str, folder_id: str) -> Dict[str, str]:
    """
    Returns: {"status":"ok","action":"download|upload|noop","why": "...", "path": local_db}
    """
    dst = os.path.abspath(local_db)
    tmp_dir = os.path.dirname(dst) or "."
    pathlib.Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    # 1) enumerate remote
    files = gdrive.list_files(folder_id)
    remote = _pick_remote_db(files, expected_name=os.path.basename(dst))

    if not remote:
        if os.path.exists(dst):
            gdrive.upload_file(dst, folder_id)
            return {"status": "ok", "action": "upload", "why": "remote missing; uploaded local", "path": dst}
        return {"status": "ok", "action": "noop", "why": "no local or remote DB", "path": dst}

    # 2) compare times/sizes
    remote_epoch = float(remote.get("modifiedTimeEpoch", 0) or 0)
    local_epoch = _local_mtime(dst)
    remote_size = int(remote.get("size", 0) or 0)
    local_size = int(os.path.getsize(dst)) if os.path.exists(dst) else 0

    # 3) decide direction
    if (remote_epoch > local_epoch) or (remote_epoch == 0 and remote_size > 0 and remote_size != local_size):
        # Remote -> Local
        tmp_path = os.path.join(tmp_dir, "takeout.db.download.tmp")
        # Ensure stale temp is gone
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

        gdrive.download_file(remote["id"], tmp_path)

        # Verify temp exists and has bytes before replacing
        if not os.path.exists(tmp_path):
            raise FileNotFoundError(
                f"Expected downloaded temp not found at {tmp_path}. "
                "Verify gdrive.download_file() implementation and folder/file permissions."
            )
        if os.path.getsize(tmp_path) <= 0:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            raise IOError("Downloaded temp file is empty; aborting replace.")

        try:
            _safe_replace(tmp_path, dst)
        finally:
            # best-effort cleanup if temp still remains
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        return {"status": "ok", "action": "download", "why": "remote newer", "path": dst}

    if local_epoch > remote_epoch or (remote_epoch == 0 and local_size > 0 and local_size != remote_size):
        # Local -> Remote
        gdrive.upload_file(dst, folder_id)
        return {"status": "ok", "action": "upload", "why": "local newer", "path": dst}

    return {"status": "ok", "action": "noop", "why": "same timestamp/size", "path": dst}
