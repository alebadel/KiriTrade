"""Live path of update.py against a fake Comtrade (no network, no real key)."""
import datetime as dt
import json, shutil, sys
from pathlib import Path
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests"))
import update as U                       # noqa: E402
from mock_comtrade import FakeComtrade   # noqa: E402


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch):
    """The tests pass --today 2026-10-13; pin update.utc_now() to the same day so the
    manifest.generated_at-is-today validation does not depend on when the tests run."""
    monkeypatch.setattr(U, "utc_now", lambda: dt.datetime(2026, 10, 13, 9, 0, 0, tzinfo=dt.timezone.utc))
    import build_site_data as B, build_products as P     # noqa: E402  (the builders stamp generated_at themselves)
    monkeypatch.setattr(B, "_now_iso", lambda: "2026-10-13T09:00:00Z")
    for name in ("_now_iso", "_utc_now_iso", "now_iso"):
        if hasattr(P, name):
            monkeypatch.setattr(P, name, lambda: "2026-10-13T09:00:00Z")


def _args(tmp, *extra):
    return U.build_args(["--data-dir", str(tmp / "data"), "--out", str(tmp / "out"),
                         "--today", "2026-10-13", *extra])


def test_offline_writes_all_site_json(tmp_path):
    shutil.copytree(HERE / "data", tmp_path / "data")
    assert U.run_update(_args(tmp_path, "--offline")) == 0
    for f in ["coverage", "series", "manifest", "national_accounts", "peers", "products"]:
        d = json.loads((tmp_path / "out" / f"{f}.json").read_text())
        assert "meta" in d
    man = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert man["last_update_mode"] == "offline_rebuild"


def test_live_requires_key(tmp_path, monkeypatch):
    shutil.copytree(HERE / "data", tmp_path / "data")
    for k in ("COMTRADE_API_KEY", "COMTRADE_TIER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("comtrade_mirror.config._find_key", lambda: None, raising=False)
    rc = U.run_update(_args(tmp_path))
    assert rc == 3


def test_live_with_fake_api_keeps_history(tmp_path, monkeypatch):
    shutil.copytree(HERE / "data", tmp_path / "data")
    monkeypatch.setenv("COMTRADE_API_KEY", "TEST-NOT-A-REAL-KEY")
    monkeypatch.setenv("COMTRADE_TIER", "premium")
    raw = pd.read_parquet(HERE / "data/raw/kiribati/raw_observations.parquet")
    before = len(raw)
    fake = FakeComtrade(raw)
    rc = U.run_update(_args(tmp_path), session=fake)
    assert rc in (0, 1), rc            # 0 = ok, 1 = partial
    after = pd.read_parquet(tmp_path / "data/data/raw/kiribati/raw_observations.parquet") \
        if (tmp_path / "data/data/raw/kiribati/raw_observations.parquet").exists() \
        else pd.read_parquet(tmp_path / "data/raw/kiribati/raw_observations.parquet")
    assert len(after) >= before        # history never shrinks
    man = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert man["last_update_mode"] == "live_comtrade"
    assert man["coverage_method"] == "comtrade_getDa"
    assert fake.calls                  # it really called the (fake) API
