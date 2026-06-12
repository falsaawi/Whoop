#!/usr/bin/env python3
"""Collect continuous heart rate from a WHOOP strap's Bluetooth broadcast and
ship it to the Whoop Data API (/ingest/heart-rate).

The official Whoop cloud API does not expose the continuous heart-rate stream,
but the strap can broadcast it over standard Bluetooth LE (Heart Rate Profile).
Enable it in the WHOOP app:  More > Device Settings > Broadcast Heart Rate.

Run this on a computer with Bluetooth near you:

    pip install bleak httpx
    export INGEST_URL="https://whoop-iota.vercel.app/ingest/heart-rate"
    export INGEST_TOKEN="<your CRON_SECRET from Vercel env settings>"
    python whoop_ble_collector.py

It scans for the WHOOP device, subscribes to heart-rate notifications
(~1 sample/second), and posts a batch to your API every 30 seconds.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

try:
    import httpx
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("Missing dependencies. Run:  pip install bleak httpx")

HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"

INGEST_URL = os.environ.get("INGEST_URL", "").strip()
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "").strip()
BATCH_SECONDS = int(os.environ.get("BATCH_SECONDS", "30"))

buffer: list[dict] = []


def parse_hr(data: bytearray) -> int | None:
    """Parse a standard BLE Heart Rate Measurement characteristic value."""
    if not data:
        return None
    flags = data[0]
    if flags & 0x01:  # 16-bit heart rate value
        if len(data) < 3:
            return None
        return int.from_bytes(data[1:3], "little")
    if len(data) < 2:
        return None
    return data[1]


def on_notify(_sender, data: bytearray) -> None:
    bpm = parse_hr(data)
    if bpm and 20 <= bpm <= 250:
        buffer.append(
            {"ts": datetime.now(timezone.utc).isoformat(), "bpm": bpm}
        )
        print(f"\r{datetime.now():%H:%M:%S}  ❤ {bpm} bpm   (buffered: {len(buffer)})",
              end="", flush=True)


async def flush_loop() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            await asyncio.sleep(BATCH_SECONDS)
            if not buffer:
                continue
            batch, buffer[:] = buffer[:], []
            try:
                resp = await client.post(
                    INGEST_URL,
                    json={"samples": batch, "source": "ble"},
                    headers={"Authorization": f"Bearer {INGEST_TOKEN}"},
                )
                resp.raise_for_status()
                print(f"\n  ↥ shipped {resp.json().get('stored', 0)} samples")
            except Exception as exc:  # keep collecting; retry with next batch
                print(f"\n  ! upload failed ({exc}); keeping {len(batch)} samples")
                buffer[:0] = batch


async def main() -> None:
    if not INGEST_URL or not INGEST_TOKEN:
        sys.exit("Set INGEST_URL and INGEST_TOKEN environment variables first.")

    print("Scanning for your WHOOP (make sure 'Broadcast Heart Rate' is ON "
          "in the WHOOP app)...")
    device = None
    for _ in range(6):
        devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
        for d, adv in devices.values():
            name = (d.name or "").lower()
            if "whoop" in name or HR_SERVICE in (adv.service_uuids or []):
                device = d
                break
        if device:
            break
        print("  ...still scanning")
    if device is None:
        sys.exit("No WHOOP / heart-rate broadcast found. Is broadcasting on?")

    print(f"Connecting to {device.name or device.address}...")
    async with BleakClient(device) as client:
        await client.start_notify(HR_MEASUREMENT, on_notify)
        print("Connected. Streaming heart rate — leave this running. Ctrl+C to stop.")
        await flush_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
