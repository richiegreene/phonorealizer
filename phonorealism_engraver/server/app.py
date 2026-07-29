"""
app.py — the engraver's local server.

Deliberately thin. The score readers and the notation geometry live in
phonorealism_shared and run in the browser, so this process only does the two
things a browser cannot: keep project files on disk, and (later) drive LilyPond.

Nothing here parses a score. There is exactly one justidraw reader in this
repository and it is JavaScript; a second implementation in Python would be a
second thing to keep correct, and the canonical partial numbering has to agree
between the engraver and the performer app or part maps silently break.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PROJECTS = ROOT / "projects"
SHARED = ROOT.parent / "phonorealism_shared" / "js"

MAX_PROJECT_BYTES = 32 * 1024 * 1024

app = FastAPI(title="Phonorealism Engraver")
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """
    Force revalidation of everything this server hands out.

    Browsers cache ES modules hard, and this is a tool under active development
    served from disk: an edited main.js that the tab refuses to re-fetch looks
    exactly like a broken feature, and the usual fix — a hard reload — is not
    obvious when the symptom is "the button stopped working". Local traffic
    makes the bandwidth cost irrelevant.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


def safe_name(name: str) -> str:
    """
    Reduce a user-supplied project name to a bare filename.

    Project names come from a text field and are used to build a path, so this
    strips directory separators and traversal outright rather than trying to
    sanitise them — there is no legitimate project called "../../.ssh/id_rsa".
    """
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "_", name).strip(" .")
    cleaned = cleaned.replace("..", "_")
    return cleaned[:80] or "untitled"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/projects")
async def list_projects() -> JSONResponse:
    PROJECTS.mkdir(exist_ok=True)
    out = []
    for p in sorted(PROJECTS.glob("*.json")):
        try:
            doc = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "name": p.stem,
                "score": (doc.get("score") or {}).get("name"),
                "parts": len(doc.get("parts") or []),
                "annotations": len(doc.get("annotations") or []),
                "modified": p.stat().st_mtime,
            }
        )
    return JSONResponse(out)


@app.get("/api/projects/{name}")
async def get_project(name: str) -> JSONResponse:
    path = PROJECTS / f"{safe_name(name)}.json"
    if not path.exists():
        return JSONResponse({"error": "no such project"}, status_code=404)
    try:
        return JSONResponse(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError) as exc:
        return JSONResponse({"error": f"unreadable: {exc}"}, status_code=500)


@app.put("/api/projects/{name}")
async def put_project(name: str, request: Request) -> JSONResponse:
    raw = await request.body()
    if len(raw) > MAX_PROJECT_BYTES:
        return JSONResponse({"error": "project too large"}, status_code=413)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"bad JSON: {exc}"}, status_code=400)
    if not isinstance(doc, dict) or doc.get("kind") != "phonorealism-engraving":
        return JSONResponse({"error": "not an engraving document"}, status_code=400)

    PROJECTS.mkdir(exist_ok=True)
    stem = safe_name(name)
    path = PROJECTS / f"{stem}.json"

    # Write via a temporary file and replace, so an interrupted save cannot
    # leave a half-written project where a good one used to be.
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(doc, indent=1))
        tmp.replace(path)
    except OSError as exc:
        return JSONResponse({"error": f"could not save: {exc}"}, status_code=500)
    return JSONResponse({"ok": True, "name": stem})


@app.delete("/api/projects/{name}")
async def delete_project(name: str) -> JSONResponse:
    path = PROJECTS / f"{safe_name(name)}.json"
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse({"ok": True})


@app.get("/api/lilypond")
async def lilypond_status() -> JSONResponse:
    """
    Report whether LilyPond is available.

    The staff-notation phase will shell out to it; surfacing availability now
    means the UI can show the feature as pending rather than broken, and tells
    you whether the toolchain is in place before that work lands.
    """
    import shutil
    import subprocess

    exe = shutil.which("lilypond")
    if not exe:
        return JSONResponse({"available": False})
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=10
        ).stdout.splitlines()
        return JSONResponse({"available": True, "path": exe, "version": out[0] if out else ""})
    except (subprocess.SubprocessError, OSError):
        return JSONResponse({"available": False, "path": exe})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/shared", StaticFiles(directory=SHARED), name="shared")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phonorealism Engraver")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8200)
    args = ap.parse_args()

    import uvicorn

    if not SHARED.exists():
        print(f"[engraver] missing shared modules at {SHARED}", file=sys.stderr)
        raise SystemExit(1)

    print()
    print("  Phonorealism Engraver")
    print(f"    http://{args.host}:{args.port}/")
    print()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
