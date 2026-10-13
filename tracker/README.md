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
