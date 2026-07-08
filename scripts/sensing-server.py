"""
Lightweight Python sensing server for room-map.html.

Receives ESP32 CSI data via UDP (port 5005), computes per-node features,
and broadcasts JSON over WebSocket in the format room-map.html expects.

Usage:
    pip install websockets numpy
    python scripts/sensing-server.py

Then open v2/examples/room-map.html in your browser.
"""

import asyncio
import json
import math
import socket
import struct
import sys
import time
from collections import deque
from typing import Dict, Optional, Set

import numpy as np

try:
    import websockets
except ImportError:
    print("ERROR: instala websockets con:  pip install websockets")
    sys.exit(1)

# ─── Config ───────────────────────────────────────────────────────────────────
WS_HOST = "0.0.0.0"
WS_PORT = 8765
UDP_PORT = 5005
TICK_HZ = 2  # broadcasts per second
WINDOW_FRAMES = 100  # frames to keep per node for stats

# ADR-018 binary header
MAGIC = 0xC5110001
HEADER_SIZE = 20
HEADER_FMT = '<IBBHIIBB2x'

# ─── Per-node ring buffer ─────────────────────────────────────────────────────

class NodeBuffer:
    def __init__(self, maxlen=WINDOW_FRAMES):
        self.amplitudes = deque(maxlen=maxlen)
        self.times = deque(maxlen=maxlen)
        self.rssi_history = deque(maxlen=maxlen)
        self.last_seen = 0.0
        self.last_seq = 0
        self.n_sc = 0
        self.freq = 0
        self.rssi = -80
        self.source_addr = ""
        # Adaptive resting baseline of the activity metric. Tracks the quiet
        # floor: drops quickly when things calm down, rises very slowly so a
        # moving person stays "above baseline" (= detected) for a long time.
        self.baseline = None

    def push(self, mean_amp: float, rssi: int, seq: int, n_sc: int, freq: int, addr: str):
        self.amplitudes.append(mean_amp)
        self.times.append(time.time())
        self.rssi_history.append(rssi)
        self.last_seen = time.time()
        self.last_seq = seq
        self.n_sc = n_sc
        self.freq = freq
        self.rssi = rssi
        self.source_addr = addr

    def features(self) -> Dict:
        if len(self.amplitudes) < 3:
            return {"variance": 0, "motion_band_power": 0, "spectral_power": 0}
        arr = np.array(self.amplitudes, dtype=np.float64)
        variance = float(np.var(arr))
        diff = np.diff(arr)
        motion = float(np.mean(np.abs(diff))) if len(diff) > 0 else 0.0
        spectral = float(np.sum(arr ** 2) / len(arr))
        return {
            "variance": variance,
            "motion_band_power": motion,
            "spectral_power": spectral,
        }

    @property
    def age_ms(self) -> float:
        return (time.time() - self.last_seen) * 1000 if self.last_seen > 0 else 99999

    @property
    def is_fresh(self) -> bool:
        return self.age_ms < 5000


# ─── Global state ─────────────────────────────────────────────────────────────
nodes: Dict[int, NodeBuffer] = {}
clients: Set = set()


# ─── UDP receiver ─────────────────────────────────────────────────────────────

class UdpProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr):
        if len(data) < HEADER_SIZE:
            return
        magic, node_id, n_ant, n_sc, freq_mhz, seq, rssi_u8, noise_u8 = \
            struct.unpack_from(HEADER_FMT, data, 0)
        if magic != MAGIC:
            return

        rssi = rssi_u8 if rssi_u8 < 128 else rssi_u8 - 256

        iq_count = n_ant * n_sc
        iq_bytes_needed = HEADER_SIZE + iq_count * 2
        if len(data) >= iq_bytes_needed and iq_count > 0:
            iq_raw = struct.unpack_from(f'<{iq_count * 2}b', data, HEADER_SIZE)
            i_vals = np.array(iq_raw[0::2], dtype=np.float64)
            q_vals = np.array(iq_raw[1::2], dtype=np.float64)
            mean_amp = float(np.mean(np.sqrt(i_vals**2 + q_vals**2)))
        else:
            mean_amp = 0.0

        if node_id not in nodes:
            nodes[node_id] = NodeBuffer()
        nodes[node_id].push(mean_amp, rssi, seq, n_sc, freq_mhz, f"{addr[0]}:{addr[1]}")


# ─── Real vital signs from CSI amplitude (FFT) ────────────────────────────────

def estimate_vitals(buf: NodeBuffer) -> Dict:
    """Estimate breathing/heart rate from the amplitude time series via FFT.

    Real signal — no fabrication. Only reports a rate when a clear spectral
    peak stands out above the mean spectrum (so it stays empty when the person
    is moving a lot or absent). Requires the person to be fairly still.
    """
    if len(buf.amplitudes) < 48 or len(buf.times) < 48:
        return {}
    amps = np.array(buf.amplitudes, dtype=np.float64)
    times = np.array(buf.times, dtype=np.float64)
    amps = amps - np.mean(amps)
    dur = times[-1] - times[0]
    if dur <= 0:
        return {}
    fs = (len(times) - 1) / dur
    if fs < 2.0:  # need >= 2 Hz to see heart band
        return {}

    n = len(amps)
    spec = np.abs(np.fft.rfft(amps * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    mean_spec = float(np.mean(spec)) + 1e-9

    def band_peak(lo, hi):
        m = (freqs >= lo) & (freqs <= hi)
        if not np.any(m):
            return 0.0, 0.0
        sub = spec[m]
        idx = int(np.argmax(sub))
        return float(freqs[m][idx]), float(sub[idx])

    out = {}
    bf, bp = band_peak(0.15, 0.50)   # breathing: 9–30 rpm
    if bp > mean_spec * 3.0:
        out["breathing_rate_bpm"] = round(bf * 60.0, 1)
    hf, hp = band_peak(0.83, 2.0)    # heart: 50–120 bpm
    if hp > mean_spec * 3.5:
        out["heart_rate_bpm"] = round(hf * 60.0, 1)
    return out


# ─── Build broadcast message ─────────────────────────────────────────────────

# Activity = motion_band_power + 0.5*variance. A node is "active" (detecting
# real motion) when its activity rises clearly above its own resting baseline,
# or when absolute motion is unambiguously high.
EXCESS_THRESH = 0.12
ABS_MOTION_THRESH = 0.45


def build_message() -> Optional[str]:
    if not nodes:
        return None

    node_features = []
    fresh_count = 0
    any_active = False
    dominant = None      # (excess, buf) of the most-active fresh node

    for nid, buf in sorted(nodes.items()):
        feat = buf.features()
        activity = feat["motion_band_power"] + 0.5 * feat["variance"]

        # Adaptive baseline: fast down to the floor, very slow up.
        if buf.baseline is None:
            buf.baseline = activity
        elif activity < buf.baseline:
            buf.baseline += (activity - buf.baseline) * 0.25
        else:
            buf.baseline += (activity - buf.baseline) * 0.01

        excess = max(0.0, activity - buf.baseline)
        fresh = buf.is_fresh
        active = fresh and (excess > EXCESS_THRESH or feat["motion_band_power"] > ABS_MOTION_THRESH)

        if fresh:
            fresh_count += 1
        if active:
            any_active = True
            if dominant is None or excess > dominant[0]:
                dominant = (excess, buf)

        node_features.append({
            "node_id": nid,
            "last_seen_ms": buf.age_ms,
            "stale": not fresh,
            "excess": round(excess, 3),
            "active": bool(active),
            "features": feat,
        })

    # Honest person count: with 2 scalar links we can localize ONE moving
    # target, not separate multiple people. Report presence, not a fake count.
    persons = 1 if any_active else 0

    vitals = estimate_vitals(dominant[1]) if dominant else {}

    avg_motion = (
        sum(b.features()["motion_band_power"] for b in nodes.values() if b.is_fresh)
        / max(fresh_count, 1)
    )

    msg = {
        "type": "sensing_update",
        "timestamp": time.time(),
        "source": "esp32",
        "node_features": node_features,
        "features": {
            "motion_band_power": avg_motion,
            "variance": max((n.features()["variance"] for n in nodes.values() if n.is_fresh), default=0),
        },
        "classification": {
            "presence": any_active,
            "motion_level": "moving" if avg_motion > 0.5 else ("micro" if any_active else "still"),
            "confidence": min(1.0, avg_motion * 2) if any_active else 0.2,
        },
        "estimated_persons": persons,
        "vital_signs": vitals,
        "signal_quality_score": 0.8 if fresh_count >= 2 else (0.4 if fresh_count == 1 else 0.0),
        "signal_field": {"grid_size": [20, 1, 20], "values": []},
    }
    return json.dumps(msg)


# ─── WebSocket handler ────────────────────────────────────────────────────────

async def ws_handler(websocket):
    if websocket.request and hasattr(websocket.request, 'path'):
        path = websocket.request.path
    else:
        path = getattr(websocket, 'path', '/ws/sensing')

    clients.add(websocket)
    print(f"  [WS] Cliente conectado ({len(clients)} total)")
    try:
        async for _ in websocket:
            pass
    finally:
        clients.discard(websocket)
        print(f"  [WS] Cliente desconectado ({len(clients)} total)")


async def broadcast_loop():
    global clients
    while True:
        if clients:
            msg = build_message()
            if msg:
                dead = set()
                for ws in clients:
                    try:
                        await ws.send(msg)
                    except Exception:
                        dead.add(ws)
                clients -= dead
        await asyncio.sleep(1.0 / TICK_HZ)


def print_status():
    fresh = [nid for nid, b in nodes.items() if b.is_fresh]
    stale = [nid for nid, b in nodes.items() if not b.is_fresh]
    status = f"  Nodos frescos: {fresh}" if fresh else "  Sin nodos activos"
    if stale:
        status += f" | Stale: {stale}"
    return status


async def status_loop():
    while True:
        await asyncio.sleep(5)
        print(print_status())
        for nid, buf in sorted(nodes.items()):
            if buf.is_fresh:
                f = buf.features()
                print(f"    ESP#{nid} [{buf.source_addr}] var:{f['variance']:.1f} "
                      f"mot:{f['motion_band_power']:.2f} age:{buf.age_ms:.0f}ms")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    print("\n╔══════════════════════════════════════════════╗")
    print("║   WiFi-DensePose Sensing Server (Python)    ║")
    print("╠══════════════════════════════════════════════╣")
    print(f"║  UDP escucha en     : 0.0.0.0:{UDP_PORT}          ║")
    print(f"║  WebSocket en       : ws://0.0.0.0:{WS_PORT}/ws/sensing ║")
    print("║  Abre room-map.html en el navegador         ║")
    print("╚══════════════════════════════════════════════╝\n")

    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        UdpProtocol, local_addr=("0.0.0.0", UDP_PORT)
    )
    print(f"  [UDP] Escuchando en puerto {UDP_PORT}...")

    async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
        print(f"  [WS]  Servidor en ws://0.0.0.0:{WS_PORT}/ws/sensing")
        print("  Esperando datos de los ESP32...\n")
        await asyncio.gather(broadcast_loop(), status_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Servidor detenido.")
