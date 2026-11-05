from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .sources import snapshot


app = FastAPI(title="CatchmentWatch", version="0.1.0", description="Open-data situational awareness prototype")
STATIC = Path(__file__).parent / "static"
_cache: dict[str, object] = {"expires": 0.0, "data": None}
_lock = Lock()


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/assets/{asset}", include_in_schema=False)
def assets(asset: str) -> FileResponse:
    if asset not in {"app.js", "styles.css"}:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC / asset)


@app.get("/api/snapshot")
def get_snapshot(refresh: bool = False) -> dict:
    now = time.time()
    with _lock:
        if not refresh and _cache["data"] is not None and now < float(_cache["expires"]):
            return _cache["data"]  # type: ignore[return-value]
    result = snapshot()
    with _lock:
        _cache["data"] = result
        _cache["expires"] = time.time() + 600
    return result


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "utc": datetime.now(timezone.utc).isoformat()}
