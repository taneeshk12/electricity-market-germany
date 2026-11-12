"""Extract: chunk selection, retries, caching and atomic writes – with a fake HTTP session."""

from __future__ import annotations

import json
from datetime import date

import pytest
import requests

from src import config, extract
from tests.conftest import SOLAR, set_period

WEEK_MS = 7 * 24 * 3600 * 1000


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload, self.status_code = payload, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    """Maps URL -> list of responses (consumed in order); records every call."""

    def __init__(self, routes: dict[str, list[FakeResponse]]) -> None:
        self.routes, self.calls = routes, []

    def get(self, url: str, timeout: int) -> FakeResponse:
        self.calls.append(url)
        return self.routes[url].pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract.time, "sleep", lambda s: None)


def _period_ms() -> tuple[int, int]:
    start, end = config.period_bounds_utc()
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def test_relevant_chunks_keeps_only_overlapping_weeks(monkeypatch: pytest.MonkeyPatch) -> None:
    set_period(monkeypatch, date(2024, 1, 10), date(2024, 1, 20))
    start, end = _period_ms()
    before = start - WEEK_MS  # ends exactly at period start -> no overlap
    overlapping_start = start - WEEK_MS + 1
    inside = start + 3600_000
    at_end = end  # starts exactly at (exclusive) end -> no overlap
    assert extract._relevant_chunks([before, overlapping_start, inside, at_end]) == [overlapping_start, inside]


def test_get_json_retries_then_succeeds() -> None:
    session = FakeSession({"u": [FakeResponse({}, 503), FakeResponse(ValueError("bad json")), FakeResponse({"ok": 1})]})
    assert extract._get_json(session, "u") == {"ok": 1}
    assert len(session.calls) == 3


def test_get_json_gives_up_after_max_retries() -> None:
    session = FakeSession({"u": [FakeResponse({}, 500) for _ in range(extract.MAX_RETRIES)]})
    with pytest.raises(RuntimeError, match="Giving up on u"):
        extract._get_json(session, "u")
    assert len(session.calls) == extract.MAX_RETRIES


def test_download_chunk_writes_atomically_and_skips_existing(tmp_path) -> None:
    target = tmp_path / "123.json"
    session = FakeSession({"u": [FakeResponse({"series": [[1, 2.0]]})]})
    assert extract._download_chunk(session, "u", target) is True
    assert json.loads(target.read_text()) == {"series": [[1, 2.0]]}
    assert not target.with_suffix(".tmp").exists()
    # Second call must not hit the network at all (re-runs are cheap / idempotent).
    assert extract._download_chunk(session, "u", target) is False
    assert session.calls == ["u"]


def test_download_chunk_rejects_payload_without_series(tmp_path) -> None:
    session = FakeSession({"u": [FakeResponse({"unexpected": []})]})
    with pytest.raises(RuntimeError, match="no 'series'"):
        extract._download_chunk(session, "u", tmp_path / "x.json")
    assert not (tmp_path / "x.json").exists()


def test_extract_series_downloads_only_relevant_chunks(raw_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    set_period(monkeypatch, date(2024, 1, 10), date(2024, 1, 20))
    start, _ = _period_ms()
    keep, drop = start - 3600_000, start - 3 * WEEK_MS
    base = f"{config.SMARD_BASE_URL}/{SOLAR.filter_id}/{config.SMARD_REGION}"
    chunk_url = f"{base}/{SOLAR.filter_id}_{config.SMARD_REGION}_quarterhour_{keep}.json"
    session = FakeSession(
        {
            f"{base}/index_quarterhour.json": [FakeResponse({"timestamps": [drop, keep]})],
            chunk_url: [FakeResponse({"series": [[keep, 5.0]]})],
        }
    )
    assert extract.extract_series(session, SOLAR, "quarterhour") == 1
    files = list(extract.chunk_dir(SOLAR, "quarterhour").glob("*.json"))
    assert [f.name for f in files] == [f"{keep}.json"]


def test_extract_series_fails_loudly_without_chunks(raw_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    set_period(monkeypatch, date(2024, 1, 10), date(2024, 1, 20))
    base = f"{config.SMARD_BASE_URL}/{SOLAR.filter_id}/{config.SMARD_REGION}"
    session = FakeSession({f"{base}/index_hour.json": [FakeResponse({"timestamps": [0]})]})
    with pytest.raises(RuntimeError, match="No chunks"):
        extract.extract_series(session, SOLAR, "hour")


def test_write_manifest_records_provenance(raw_dir) -> None:
    raw_dir.mkdir(parents=True)
    extract.write_manifest()
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    assert manifest["region"] == "DE-LU"
    assert {s["name"] for s in manifest["series"]} == {s.name for s in config.SMARD_SERIES}
    assert manifest["retrieved_at_utc"].endswith("+00:00")
