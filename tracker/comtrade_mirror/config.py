"""Configuration: country registry, paths, API tier, environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Country registry. Keyed by a short slug; extend freely for other small states.
# Codes are UN M49 as used by Comtrade `reporterCode` / `partnerCode`.
# --------------------------------------------------------------------------
COUNTRIES: dict[str, dict] = {
    "kiribati":       {"m49": 296, "iso3": "KIR", "name": "Kiribati"},
    "tuvalu":         {"m49": 798, "iso3": "TUV", "name": "Tuvalu"},
    "nauru":          {"m49": 520, "iso3": "NRU", "name": "Nauru"},
    "marshall_is":    {"m49": 584, "iso3": "MHL", "name": "Marshall Islands"},
    "micronesia":     {"m49": 583, "iso3": "FSM", "name": "Micronesia (FS)"},
    "palau":          {"m49": 585, "iso3": "PLW", "name": "Palau"},
    "samoa":          {"m49": 882, "iso3": "WSM", "name": "Samoa"},
    "tonga":          {"m49": 776, "iso3": "TON", "name": "Tonga"},
    "vanuatu":        {"m49": 548, "iso3": "VUT", "name": "Vanuatu"},
    "solomon_is":     {"m49": 90,  "iso3": "SLB", "name": "Solomon Islands"},
    "png":            {"m49": 598, "iso3": "PNG", "name": "Papua New Guinea"},
    "fiji":           {"m49": 242, "iso3": "FJI", "name": "Fiji"},
    "timor_leste":    {"m49": 626, "iso3": "TLS", "name": "Timor-Leste"},
    "maldives":       {"m49": 462, "iso3": "MDV", "name": "Maldives"},
    "sao_tome":       {"m49": 678, "iso3": "STP", "name": "Sao Tome and Principe"},
    "comoros":        {"m49": 174, "iso3": "COM", "name": "Comoros"},
}

WORLD_CODE = 0          # partnerCode 0 == World aggregate; never mix with bilateral sums
# Comtrade rejects partnerCode="all" with 400 "The field partnerCode is invalid".
# Omitting the parameter is how you ask for every partner.
ALL_PARTNERS = None

# Reciprocal flow map: what the *mirror* reporter calls the same shipment.
MIRROR_FLOW = {"X": "M", "M": "X"}
FLOW_LABEL = {"X": "export", "M": "import"}


def _settings_file() -> dict[str, str]:
    """KEY=VALUE lines from `.env`, then `COMTRADE_API.txt`, next to the package.

    COMTRADE_API.txt is the file that holds the subscription keys. It may also
    carry TIER=premium and CALLS_PER_DAY=<n>, so that switching from the free
    product to the institutional premium product (APICOMTRADEPREMINST) is a
    change to that one file and nothing else. Both files are git-ignored;
    nothing here prints or logs a key.

    Tracker (vendored copy) note: the two files are listed in the repository's
    .gitignore and must never be committed. In GitHub Actions
    (GITHUB_ACTIONS=true), or when COMTRADE_NO_SETTINGS_FILES is set, the files
    are not read at all: the key and tier come only from the environment
    variables COMTRADE_API_KEY and COMTRADE_TIER (repository secrets).
    """
    if os.getenv("GITHUB_ACTIONS") or os.getenv("COMTRADE_NO_SETTINGS_FILES"):
        return {}
    root = Path(__file__).resolve().parents[1]
    out: dict[str, str] = {}
    for fname in ("COMTRADE_API.txt", ".env"):      # .env wins if both set a key
        f = root / fname
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v and "paste_your" not in v:
                out[k.strip().upper()] = v
    return out


_FILE = _settings_file()


def _find_key() -> str | None:
    """COMTRADE_API_KEY from the environment, else PRIMARY_KEY / COMTRADE_API_KEY
    from the settings files."""
    return (os.getenv("COMTRADE_API_KEY") or _FILE.get("COMTRADE_API_KEY")
            or _FILE.get("PRIMARY_KEY"))


def _find_tier() -> str:
    """COMTRADE_TIER from the environment, else TIER in the settings files, else free."""
    return (os.getenv("COMTRADE_TIER") or _FILE.get("COMTRADE_TIER")
            or _FILE.get("TIER") or "free").lower()


def _find_calls_per_day(tier: str) -> int:
    v = (os.getenv("COMTRADE_CALLS_PER_DAY") or _FILE.get("COMTRADE_CALLS_PER_DAY")
         or _FILE.get("CALLS_PER_DAY"))
    if v:
        return int(v)
    # Local guard only; Comtrade enforces its own allowance and the client
    # stops cleanly on the 403 it returns when that is spent.
    return 5000 if tier == "premium" else 480


@dataclass
class Config:
    """Everything the pipeline needs. Instantiate once, pass down."""

    country: str = "kiribati"
    # 2025-2026 is the working span: it is the best-covered recent period for
    # Kiribati (17 of 19 months reported) and its self-side pull fits inside a
    # single day of the free-tier call budget. See docs on availability.
    years: tuple[int, ...] = (2025, 2026)
    # "free" -> public/v1/preview (500-record cap); "premium" -> data/v1/get
    tier: str = field(default_factory=_find_tier)
    subscription_key: str | None = field(default_factory=lambda: _find_key())
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])

    # Politeness / quota management. Free keys are limited to a few hundred
    # calls per day, so caching and batching matter more than speed.
    calls_per_day: int = 0          # resolved in __post_init__ from tier
    # Comtrade throttles hard at roughly one call per second. Pacing below that
    # just trades wall-clock time for a storm of 429s.
    min_seconds_between_calls: float = 2.0
    max_retries: int = 4
    max_throttle_waits: int = 20
    timeout: int = 120

    # HS detail to request. "AG6" = 6-digit; "TOTAL" only for reconciliation checks.
    cmd_code: str = "AG6"

    def __post_init__(self) -> None:
        self.tier = (self.tier or "free").lower()
        if self.tier not in ("free", "premium"):
            raise ValueError(f"tier must be 'free' or 'premium', not {self.tier!r}")
        if not self.calls_per_day:
            self.calls_per_day = _find_calls_per_day(self.tier)
        if self.country not in COUNTRIES:
            raise KeyError(
                f"Unknown country slug {self.country!r}. "
                f"Add it to COUNTRIES in config.py. Known: {sorted(COUNTRIES)}"
            )
        for d in (self.raw_dir, self.interim_dir, self.out_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)

    # -- identity ----------------------------------------------------------
    @property
    def meta(self) -> dict:
        return COUNTRIES[self.country]

    @property
    def code(self) -> int:
        return self.meta["m49"]

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def periods(self) -> list[str]:
        """All YYYYMM strings implied by `years`."""
        return [f"{y}{m:02d}" for y in self.years for m in range(1, 13)]

    # -- paths -------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        """Data root. Tracker (vendored copy): the environment variable
        TRACKER_DATA_DIR overrides the default `<root>/data`, which for the
        site repository is `site/tracker/data`. The API cache lives under
        `<data_dir>/cache` so GitHub Actions can restore it with actions/cache
        while committing only raw/ and out/."""
        env = os.getenv("TRACKER_DATA_DIR")
        if env:
            return Path(env).expanduser().resolve()
        return self.root / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw" / self.country

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim" / self.country

    @property
    def out_dir(self) -> Path:
        return self.data_dir / "out" / self.country

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    # -- endpoints ---------------------------------------------------------
    @property
    def base_data_url(self) -> str:
        if self.tier == "premium":
            return "https://comtradeapi.un.org/data/v1/get"
        return "https://comtradeapi.un.org/public/v1/preview"

    @property
    def availability_url(self) -> str:
        if self.tier == "premium":
            return "https://comtradeapi.un.org/data/v1/getDa"
        return "https://comtradeapi.un.org/public/v1/getDa"

    @property
    def max_records(self) -> int:
        """Hard per-call record ceiling. Exceeding it means silent truncation."""
        return 250_000 if self.tier == "premium" else 500


REFERENCE_URLS = {
    "reporters": "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json",
    "partners": "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json",
    "flows": "https://comtradeapi.un.org/files/v1/app/reference/tradeRegimes.json",
    "units": "https://comtradeapi.un.org/files/v1/app/reference/QuantityUnits.json",
    "items": "https://comtradeapi.un.org/files/v1/app/reference/TradeDataItems.json",
    "list": "https://comtradeapi.un.org/files/v1/app/reference/ListofReferences.json",
    "hs": "https://comtradeapi.un.org/files/v1/app/reference/HS.json",
}
