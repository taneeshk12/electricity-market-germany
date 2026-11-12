"""Load a small synthetic dataset into the configured database through the real load step.

For CI only: lets `dbt build` run against a real star schema without downloading SMARD data.
Refuses to run unless ALLOW_SYNTHETIC_LOAD=1, so it cannot overwrite a real warehouse by accident
(load.main() syncs tables, i.e. it would delete rows that are not in the synthetic data).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, load  # noqa: E402
from tests.conftest import AUTUMN, make_processed  # noqa: E402


def main() -> None:
    if os.getenv("ALLOW_SYNTHETIC_LOAD") != "1":
        raise SystemExit("Refusing to run: set ALLOW_SYNTHETIC_LOAD=1 (CI databases only).")
    config.setup_logging()
    config.START_DATE, config.END_DATE = AUTUMN
    gen, pl = make_processed(*AUTUMN)
    with tempfile.TemporaryDirectory() as tmp:
        load.GENERATION_FILE, load.PRICE_LOAD_FILE = Path(tmp) / "gen.parquet", Path(tmp) / "pl.parquet"
        gen.to_parquet(load.GENERATION_FILE, index=False)
        pl.to_parquet(load.PRICE_LOAD_FILE, index=False)
        load.main()


if __name__ == "__main__":
    main()
