"""Download raw SMARD time series via the smard.de chart-data JSON API.

Layout of the API (one index per series and resolution, then weekly chunks):
    {base}/{filter}/{region}/index_{resolution}.json
        -> {"timestamps": [chunk_start_ms, ...]}
    {base}/{filter}/{region}/{filter}_{region}_{resolution}_{chunk_start_ms}.json
        -> {"series": [[timestamp_ms, value_or_null], ...]}

Timestamps are Unix epoch milliseconds (UTC), so there is no ambiguity around
daylight-saving changes. Chunks are stored unchanged under data/raw/smard/ so
the transform step is fully reproducible offline. Already downloaded chunks
are skipped, which makes re-runs cheap.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from src import config

logger = logging.getLogger(__name__)

RAW_SMARD_DIR: Path = config.RAW_DIR / "smard"
CHUNK_LENGTH = timedelta(days=7)
MAX_WORKERS = 4          # be polite to a public government API
MAX_RETRIES = 4
TIMEOUT_S = 30


def _get_json(session: requests.Session, url: str) -> dict[str, Any]:
    """GET a JSON document with retries and exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT_S)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Giving up on {url}: {exc}") from exc
            wait = 2**attempt
            logger.warning("Attempt %d for %s failed (%s), retrying in %ds", attempt, url, exc, wait)
            time.sleep(wait)
    raise AssertionError("unreachable")


def chunk_dir(series: config.SmardSeries, resolution: str) -> Path:
    """Directory holding the raw weekly chunks of one series/resolution."""
    return RAW_SMARD_DIR / f"{series.filter_id}_{series.name}" / resolution


def _relevant_chunks(timestamps: list[int]) -> list[int]:
    """Keep only weekly chunks that overlap the analysis period."""
    start, end = config.period_bounds_utc()
    start_ms, end_ms = start.timestamp() * 1000, end.timestamp() * 1000
    chunk_ms = CHUNK_LENGTH.total_seconds() * 1000
    return [t for t in timestamps if t < end_ms and t + chunk_ms > start_ms]


def _download_chunk(session: requests.Session, url: str, target: Path) -> bool:
    """Download one chunk unless it already exists. Returns True if downloaded."""
    if target.exists():
        return False
    payload = _get_json(session, url)
    if "series" not in payload:
        raise RuntimeError(f"Unexpected payload (no 'series') from {url}")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(target)  # atomic rename: no half-written files on interruption
    return True


def extract_series(session: requests.Session, series: config.SmardSeries, resolution: str) -> int:
    """Download all relevant chunks of one series. Returns the number of newly downloaded chunks."""
    base = f"{config.SMARD_BASE_URL}/{series.filter_id}/{config.SMARD_REGION}"
    index = _get_json(session, f"{base}/index_{resolution}.json")
    chunks = _relevant_chunks(index["timestamps"])
    if not chunks:
        raise RuntimeError(f"No chunks for {series.name}/{resolution} in the analysis period")

    target_dir = chunk_dir(series, resolution)
    target_dir.mkdir(parents=True, exist_ok=True)
    jobs = {
        t: (f"{base}/{series.filter_id}_{config.SMARD_REGION}_{resolution}_{t}.json",
            target_dir / f"{t}.json")
        for t in chunks
    }
    downloaded = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_download_chunk, session, url, path) for url, path in jobs.values()]
        for future in as_completed(futures):
            downloaded += future.result()
    logger.info("%-20s %-11s %3d chunks (%d new)", series.name, resolution, len(chunks), downloaded)
    return downloaded


def write_manifest() -> None:
    """Record what was downloaded and when (provenance for the data quality report)."""
    manifest = {
        "source": "SMARD.de – Bundesnetzagentur | Strommarktdaten (chart-data API)",
        "base_url": config.SMARD_BASE_URL,
        "region": config.SMARD_REGION,
        "period": [config.START_DATE.isoformat(), config.END_DATE.isoformat()],
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": [
            {"filter_id": s.filter_id, "name": s.name, "kind": s.kind, "unit": s.unit}
            for s in config.SMARD_SERIES
        ],
        "resolutions": list(config.SMARD_RESOLUTIONS),
    }
    (RAW_SMARD_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


def main() -> None:
    """Download every configured series in every configured resolution."""
    RAW_SMARD_DIR.mkdir(parents=True, exist_ok=True)
    new_chunks = 0
    with requests.Session() as session:
        session.headers["User-Agent"] = "electricity-market-germany portfolio project"
        for series in config.SMARD_SERIES:
            for resolution in config.SMARD_RESOLUTIONS:
                new_chunks += extract_series(session, series, resolution)
    # Only refresh the provenance timestamp when data actually changed on disk.
    if new_chunks or not (RAW_SMARD_DIR / "manifest.json").exists():
        write_manifest()
    logger.info("Raw data stored in %s", RAW_SMARD_DIR)


if __name__ == "__main__":
    config.setup_logging()
    main()
