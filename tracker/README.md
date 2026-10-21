# Weekly data update - maintenance guide

The published site (`index.html`, `assets/`, `data/*.json`) is static. A GitHub Actions job
(`.github/workflows/update.yml`) refreshes `data/*.json` from UN Comtrade **every Monday at 06:17 UTC**
and can also be run by hand.

## One-time setup (about 5 minutes)
1. Repository -> Settings -> Secrets and variables -> Actions -> New repository secret:
   - `COMTRADE_API_KEY` - your Comtrade subscription key (the premium key).
   - `COMTRADE_TIER` - `premium` (or `free`; free allows 500 rows per call and about 500 calls a day, and the
     updater then works in smaller steps and may need two runs to finish).
2. Settings -> Actions -> General -> Workflow permissions: "Read and write permissions".
3. Settings -> Pages: source = "Deploy from a branch", branch `main`, folder `/ (root)` (already set).
4. Actions tab -> "Weekly data update" -> Run workflow, to test it once.
Never put the key in a file in this repository. `.gitignore` already excludes `.env`, `COMTRADE_API.txt`,
`github_creds.txt` and `publish_config.json`.

## What a run does (`python tracker/update.py`)
1. Asks Comtrade which monthly/annual datasets exist for Kiribati and for each of the 19 panel partners
   (`getDa`). This is the **live percent complete**.
2. Re-pulls only months that are new or were re-released since the last run (`tracker/data/state.json`),
   plus a rolling 24-month window, for partners reporting trade with Kiribati; and Kiribati's own new months.
3. Merges into the committed history (history is never dropped; the newer pull wins for the same
   reporter-period-flow-product) and rebuilds `data/*.json` with `build_site_data.py` and `build_products.py`.
4. Writes `tracker/data/run_report.json` (calls used, status). Exit code 0 = ok, 1 = partial
   (budget reached; the next run continues), 3 = set-up problem (e.g. missing key), 4 = build error.
   A failed run publishes nothing: the JSON on the site stays as it was.
5. The workflow commits only if something changed, then asks Pages to rebuild.

## Run it yourself
```
pip install -r tracker/requirements.txt
python tracker/update.py --offline     # rebuild JSON from committed files, no key, no network
python tracker/update.py               # live (needs COMTRADE_API_KEY in the environment)
python -m pytest tracker/tests -q      # 44 tests, including a fake-Comtrade test of the live path
```

## Honest limits
- The live path was tested only against a fake Comtrade server (the build environment cannot reach
  comtradeapi.un.org). Run the workflow once by hand and read the log before relying on the schedule.
- Until the first live run, "percent complete" is **inferred from the data already pulled** (a lower bound).
  After it, it comes from Comtrade's own availability list (`coverage_method: comtrade_getDa` in manifest.json).
- Pages rebuild: if the "Ask GitHub Pages to rebuild" step is refused, the push itself normally triggers a build.
- If a partner's data move to a new reporter code or stop being published, the panel table shows its latest
  published month; panel weights are recomputed only with `--rebuild-panel`.
- BOP and GDP inputs come from `tracker/data/bop_extract.csv` (extracted once from KIR_BOP.xlsx / KIR_MT.xlsx).
  Update that file when the BOP workbook has a new year.

## Fleet (AIS) layer - `fleet.html`, `data/fleet.json`

The Fleet page is built from `data/fleet.json` (monthly fishing hours, quarterly port calls, transhipment facts;
**aggregates only - no vessel, owner or company names**). The file is produced by `tracker/build_fleet_data.py`
from the GPS-layer tables, which are *not* in this repository (they contain vessel and company names):
`GPS/out/` in the KiriTrade working folder, or `fleet_work/out/` on a GitHub runner.

### Manual refresh (until `update_v2.yml` is in place) - from the KiriTrade working folder
1. Export the WCPFC register by hand (browser; the endpoint refuses scripts): https://vessels.wcpfc.int/browse-rfv,
   flags KIR, NRU, TUV; save as `GPS\out\rfv_current.csv` (and the "include deleted vessels" view as `rfv_with_deleted.csv`).
2. In the `GPS` folder run, in order: `python vessel_master.py --skip-rfv-pull --refresh-gfw`, `python events_pull.py`,
   `python carriers_pull.py`, `python window_events.py`, `python bridge.py`.
3. From the site folder: `python tracker/build_fleet_data.py --gps-out "<...>\GPS\out" --rfv-export-date YYYY-MM-DD`
   (the date is read from the export file name when it is a `Rfv_database_export_<epoch>.csv`).
4. `set FLEET_GPS_OUT=<...>\GPS\out` then `python -m pytest tracker/tests/test_build_fleet_data.py -q`
   (reconciles `fleet.json` with the CSVs and checks that no vessel or company name appears on the site).
5. Push the site with the usual publish step. Nothing from `GPS/` is ever pushed.

### Automatic monthly refresh (`workflow_to_add/update_v2.yml`, to be added through the GitHub web UI)
Adds a `fleet` job (2nd of each month, or "Run workflow" with `refresh_fleet`). Needed once:
- secret `GFW_API_TOKEN` (the token in `KEY.txt`);
- secret `WCPFC_RFV_GZ_B64` = the register CSV, gzip then base64 (PowerShell: build the string with
  `[Convert]::ToBase64String` over the gzip-compressed bytes, or on Linux `gzip -c rfv_current.csv | base64 -w0`);
  optional `WCPFC_RFV_DEL_GZ_B64` for the deleted-vessels view; repository variable `WCPFC_RFV_EXPORT_DATE`.
- copy the five scripts into `fleet/` (already staged) so the runner can run them.
Without the secrets the job logs a notice and leaves `data/fleet.json` unchanged. The register must be re-exported
and the secret updated about monthly; a register more than 60 days old raises a warning, not an error.
The job commits `data/fleet.json` only. The first full pull has not been timed on a runner.

## Tests
`python -m pytest tracker/tests -q` - the fleet tests include a synthetic-data test of the builder, a schema
test, an aggregates-only test (key whitelist; no vessel/company names, MMSI, IMO or GFW ids on the fleet files)
and, where `GPS/out` is available, a reconciliation against the CSVs.

## Site structure (20 Oct 2026) and the three new data files

The site is a story in four parts. `index.html` (home): the question, the fish-cycle diagram, five input cards, the
AI-based inference (run log, waterfall, three-records chart) and the validation design. One detail page per input:
`comtrade.html` (the former home page: coverage, partner series, comparison with official figures, peers, products),
`fleet.html` (ship tracking), `registry.html` (vessel register), `official.html` (official statistics),
`documents.html` (rules, standards and research). Then `inference.html` (the bridges year by year, the agents'
principles and their notes on the official figures, the early estimate of the partner series), `validation.html`
(design only, no scores yet), `methods.html`, `literature.html`.

Data files added, all aggregates only:
- `data/registry.json` <- `python tracker/build_registry_data.py --master "<...>\GPS\out\vessel_master.csv" --out data/registry.json --export-date YYYY-MM-DD`.
  Counts by flag, status, type, owner-address hint, build decade, previous flag, AIS match. No names or identifiers (tested).
- `data/corpus.json` <- `python tracker/build_corpus_data.py --root "<KiriTrade folder>" --out data/corpus.json`.
  Inventory of the knowledge base: standards_docs/_KB (INDEX.md + md/*.md), mirror_papers/_KB/INDEX_ALL.md, the author's
  briefs listed in the script, and any files dropped in `country_docs/<ISO3>/<type>/`. Titles and counts only.
- `data/inference.json` <- `python tracker/build_inference_data.py --draws <folder of draw_*.json> --out data/inference.json --run-id <id> --run-date YYYY-MM-DD --prompt tracker/agents/bridge_prompt.md --official <official.json>`.
  Aggregates of the agents' bridges (mean, sd, p10/p50/p90, min, max per layer and per end value), their principles,
  their notes on the official figures and their audits. Draws live in `GPS/ensemble/<run>/` (never committed).
- `data/runs.json` - the run log shown on the home page; edit by hand when a run is added or superseded.

### Running the agents (manual, from the KiriTrade folder)
1. Build the evidence pack: the six files in `GPS/ensemble/bridge_<date>/pack/` (00_README.md, 01 partner series, 02 fleet
   aggregates, 03 partner imports by flag state, 05 standards extracts, 06 Kiribati official statistics). `build_evidence_pack.py`
   makes 01-05; 06 is drawn from `data/national_accounts.json` (BOP goods lines, customs returns, months published; no licence fees).
2. Run 30 agents, one fresh context each, with `tracker/agents/bridge_prompt.md`; each writes `draw_NN.json` into the run folder.
3. `python tracker/build_inference_data.py ...` (step above). Then one summariser agent reads `principles[]` (exported to a
   `principles.json`) with `tracker/agents/themes_prompt.md` and writes `themes.json`; `python tracker/build_themes.py --themes
   themes.json --inference data/inference.json` recounts the members and stores `principle_themes`.
4. Add the run to `data/runs.json`; write `notes/<date>-<run>.md`; run `python -m pytest tracker/tests -q`.
