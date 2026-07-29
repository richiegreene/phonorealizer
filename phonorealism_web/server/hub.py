"""
hub.py — the conductor's hub.

Responsibilities, in order of how much they matter:

1. Answer clock probes. Everything else is convenience; this is the part the
   performance depends on. A probe is answered on the receiving thread with no
   queuing and no work in between, because any delay we add lands directly in
   the client's round-trip estimate and therefore in its downbeat.
2. Hold session state — who is connected, which part each has claimed, whether
   their microphone is live — and broadcast it so the conductor can see the
   ensemble's readiness before starting.
3. Serve the score and the static app.

The hub does not stream audio and does not drive playback. It hands out a
single timestamp for the downbeat; every device plays from its own clock after
that. See net.js for the client half of the clock synchronisation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DATA = ROOT / "data"

# Refuse absurd uploads; a dense 10-minute score is a few MB.
MAX_SCORE_BYTES = 64 * 1024 * 1024


def now_ms() -> float:
    """Monotonic hub clock. Never walks backwards, unlike wall time."""
    return time.perf_counter() * 1000.0


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #


@dataclass
class Client:
    id: str
    role: str = "performer"
    name: str = ""
    part_id: str | None = None
    mic: bool = False
    ready: bool = False
    spread: float | None = None  # client-reported sync half-RTT, ms
    cents: float | None = None
    amp: float | None = None
    conf: float = 0.0
    joined_at: float = field(default_factory=now_ms)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("joined_at", None)
        return d


class Session:
    def __init__(self) -> None:
        self.clients: dict[str, Client] = {}
        self.sockets: dict[str, WebSocket] = {}
        self.parts: list[dict] = []
        self.score_meta: dict | None = None
        self.transport: dict = {"state": "idle", "startAt": None}
        self._dirty = False

    # -- membership ------------------------------------------------------- #

    def add(self, ws: WebSocket) -> Client:
        cid = uuid.uuid4().hex[:8]
        c = Client(id=cid)
        self.clients[cid] = c
        self.sockets[cid] = ws
        return c

    def remove(self, cid: str) -> None:
        self.clients.pop(cid, None)
        self.sockets.pop(cid, None)

    # -- snapshot --------------------------------------------------------- #

    def snapshot(self) -> dict[str, Any]:
        return {
            "parts": self.parts,
            "scoreMeta": self.score_meta,
            "transport": self.transport,
            "serverTime": now_ms(),
            "clients": [c.public() for c in self.clients.values()],
        }

    async def broadcast(self, msg: dict, *, roles: tuple[str, ...] | None = None) -> None:
        payload = json.dumps(msg)
        dead: list[str] = []
        for cid, ws in list(self.sockets.items()):
            client = self.clients.get(cid)
            if roles and (client is None or client.role not in roles):
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.remove(cid)

    async def push_state(self) -> None:
        await self.broadcast({"type": "state", "session": self.snapshot()})


session = Session()

# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

app = FastAPI(title="Phonorealism Perform")
# The score is the only large payload and compresses to roughly a third.
app.add_middleware(GZipMiddleware, minimum_size=2048)

_score_cache: dict | None = None


def _score_path() -> Path:
    return DATA / "score.json"


def _load_score_from_disk() -> None:
    """Survive a hub restart mid-rehearsal without re-uploading the score."""
    global _score_cache
    p = _score_path()
    if p.exists():
        try:
            _score_cache = json.loads(p.read_text())
            session.score_meta = _meta_for(_score_cache)
            if not session.parts:
                session.parts = _score_cache.get("parts") or []
        except Exception as exc:  # pragma: no cover - corrupt cache is not fatal
            print(f"[hub] ignoring unreadable cached score: {exc}", file=sys.stderr)


def _meta_for(score: dict) -> dict:
    return {
        "name": score.get("name"),
        "source": score.get("source"),
        "duration": score.get("duration"),
        "partials": len(score.get("partials") or []),
        "bpm": score.get("bpm"),
        "ampCurve": score.get("ampCurve"),
        "simplified": score.get("simplified", False),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/conductor")
async def conductor_page() -> FileResponse:
    return FileResponse(STATIC / "conductor.html")


@app.get("/performer")
async def performer_page() -> FileResponse:
    return FileResponse(STATIC / "performer.html")


@app.get("/api/score")
async def get_score() -> Response:
    if _score_cache is None:
        return JSONResponse({"error": "no score loaded"}, status_code=404)
    return JSONResponse(_score_cache)


@app.post("/api/score")
async def post_score(request: Request) -> JSONResponse:
    global _score_cache
    raw = await request.body()
    if len(raw) > MAX_SCORE_BYTES:
        return JSONResponse({"error": "score too large"}, status_code=413)
    try:
        score = json.loads(raw)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"bad JSON: {exc}"}, status_code=400)
    if not isinstance(score, dict) or not score.get("partials"):
        return JSONResponse({"error": "score has no partials"}, status_code=400)

    _score_cache = score
    session.score_meta = _meta_for(score)
    session.parts = score.get("parts") or []
    # A new score invalidates every claim: part ids refer to the old one.
    for c in session.clients.values():
        c.part_id = None
        c.ready = False
    session.transport = {"state": "idle", "startAt": None}

    DATA.mkdir(exist_ok=True)
    try:
        _score_path().write_text(json.dumps(score))
    except OSError as exc:  # pragma: no cover
        print(f"[hub] could not cache score to disk: {exc}", file=sys.stderr)

    await session.broadcast({"type": "scoreChanged", "meta": session.score_meta})
    await session.push_state()
    return JSONResponse({"ok": True, "meta": session.score_meta})


@app.get("/api/qr")
async def qr(url: str) -> Response:
    """QR for the join URL. Optional: falls back to plain text if segno is absent."""
    try:
        import segno
    except ImportError:
        return JSONResponse({"error": "segno not installed", "url": url}, status_code=501)
    import io

    buf = io.BytesIO()  # segno's SVG writer emits bytes, not text
    segno.make(url, error="m").save(
        buf, kind="svg", scale=5, dark="#e6edf5", light=None, xmldecl=False
    )
    return Response(buf.getvalue().decode("utf-8"), media_type="image/svg+xml")


@app.get("/api/info")
async def info(request: Request) -> JSONResponse:
    host = request.headers.get("host", "")
    # Behind a tunnel the client-visible scheme is https even though the hub
    # itself is serving plain http, so trust the forwarded header first.
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    # The LAN URL is what the hub is really bound to, which is not necessarily
    # what the tunnel presents.
    lan_scheme = request.url.scheme
    return JSONResponse(
        {
            "joinUrl": f"{scheme}://{host}/performer",
            "lanUrl": f"{lan_scheme}://{lan_ip()}:{request.url.port or 8000}/performer",
            "secure": scheme == "https",
            "serverTime": now_ms(),
        }
    )


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    client = session.add(ws)
    await ws.send_text(
        json.dumps({"type": "welcome", "id": client.id, "serverTime": now_ms()})
    )
    await session.push_state()

    try:
        while True:
            raw = await ws.receive_text()

            # Answer the clock probe before parsing anything else. Every
            # microsecond spent here is added to this client's measured RTT and
            # halved into its offset estimate, so this path stays as short as
            # it can possibly be.
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")

            if kind == "ping":
                await ws.send_text(
                    json.dumps({"type": "pong", "t0": msg.get("t0"), "ts": now_ms()})
                )
                continue

            changed = await handle(client, msg, kind)
            if changed:
                await session.push_state()

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        print(f"[hub] socket error for {client.id}: {exc}", file=sys.stderr)
    finally:
        session.remove(client.id)
        await session.push_state()


async def handle(client: Client, msg: dict, kind: str | None) -> bool:
    """Process one client message. Returns True if state should be rebroadcast."""

    if kind == "hello":
        client.role = "conductor" if msg.get("role") == "conductor" else "performer"
        client.name = str(msg.get("name") or "")[:40]
        return True

    if kind == "rename":
        client.name = str(msg.get("name") or "")[:40]
        return True

    if kind == "claim":
        part_id = msg.get("partId")
        client.part_id = str(part_id)[:64] if part_id else None
        return True

    if kind == "release":
        client.part_id = None
        client.ready = False
        return True

    if kind == "status":
        if "mic" in msg:
            client.mic = bool(msg["mic"])
        if "ready" in msg:
            client.ready = bool(msg["ready"])
        if "spread" in msg:
            spread = msg["spread"]
            client.spread = float(spread) if isinstance(spread, (int, float)) else None
        return True

    if kind == "meter":
        # High rate and only interesting to the conductor's readiness display.
        # Deliberately does not trigger a full state broadcast.
        client.cents = _num(msg.get("cents"))
        client.amp = _num(msg.get("amp"))
        client.conf = _num(msg.get("conf")) or 0.0
        await session.broadcast(
            {
                "type": "meter",
                "id": client.id,
                "cents": client.cents,
                "amp": client.amp,
                "conf": client.conf,
            },
            roles=("conductor",),
        )
        return False

    # ---- conductor-only ---------------------------------------------- #

    if client.role != "conductor":
        return False

    if kind == "parts":
        parts = msg.get("parts")
        if isinstance(parts, list):
            session.parts = parts[:512]
            return True
        return False

    if kind == "start":
        lead_in = _num(msg.get("leadIn")) or 2500.0
        lead_in = min(max(lead_in, 250.0), 30000.0)
        start_at = now_ms() + lead_in
        session.transport = {
            "state": "running",
            "startAt": start_at,
            "at": now_ms(),
        }
        await session.broadcast(
            {"type": "transport", "action": "start", "startAt": start_at}
        )
        return True

    if kind == "stop":
        session.transport = {"state": "idle", "startAt": None}
        await session.broadcast({"type": "transport", "action": "stop"})
        return True

    return False


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# --------------------------------------------------------------------------- #
# Launcher
# --------------------------------------------------------------------------- #


def lan_ip() -> str:
    """Best-guess LAN address. No packet is actually sent by connect() on UDP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cert(cert_dir: Path) -> tuple[Path, Path]:
    """
    Self-signed certificate for offline LAN mode.

    This exists only because getUserMedia refuses to run on a plain-http LAN
    origin. Performers will still have to accept a browser warning once per
    device; the hosted path via Cloudflare avoids that entirely.
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert, key = cert_dir / "cert.pem", cert_dir / "key.pem"
    if cert.exists() and key.exists():
        return cert, key

    ip = lan_ip()
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "825",
            "-subj", "/CN=phonorealism.local",
            "-addext", f"subjectAltName=DNS:localhost,DNS:phonorealism.local,IP:{ip},IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    print(f"[hub] generated self-signed certificate for {ip} in {cert_dir}")
    return cert, key


def main() -> None:
    ap = argparse.ArgumentParser(description="Phonorealism Perform hub")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument(
        "--tls",
        action="store_true",
        help="serve HTTPS with a self-signed cert (offline LAN mode)",
    )
    ap.add_argument("--cert-dir", default=str(ROOT / "certs"))
    args = ap.parse_args()

    import uvicorn

    _load_score_from_disk()

    kwargs: dict[str, Any] = {"host": args.host, "port": args.port, "log_level": "info"}
    scheme = "http"
    if args.tls:
        cert, key = ensure_cert(Path(args.cert_dir))
        kwargs["ssl_certfile"] = str(cert)
        kwargs["ssl_keyfile"] = str(key)
        scheme = "https"

    ip = lan_ip()
    print()
    print("  Phonorealism Perform")
    print(f"    conductor   {scheme}://localhost:{args.port}/conductor")
    print(f"    performers  {scheme}://{ip}:{args.port}/performer")
    if not args.tls:
        print()
        print("    NOTE  Microphone access needs a secure origin. Over a LAN address")
        print("          this URL will not be granted a microphone. Either run with")
        print("          --tls, or expose this hub over your domain:")
        print(f"              cloudflared tunnel --url http://localhost:{args.port}")
    print()

    uvicorn.run(app, **kwargs)


if __name__ == "__main__":
    main()
