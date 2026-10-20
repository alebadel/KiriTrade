# fleet/ — the five GPS-layer scripts (code only)

Copies of `GPS/vessel_master.py`, `events_pull.py`, `carriers_pull.py`, `window_events.py` and `bridge.py`
from the KiriTrade working folder, so that the monthly refresh job can run them on a GitHub runner.
They contain no data and no credentials: they read the Global Fishing Watch token from a `KEY.txt` that
the job writes into a temporary folder (`fleet_work/`) and deletes at the end.

**Never commit the scripts' outputs.** `out/*.csv` and the raw JSON hold vessel names, owner names and
addresses. The only fleet file that is published is `data/fleet.json`, which tracker/build_fleet_data.py
aggregates from them (hours and counts only).

Keep these copies in step with the GPS folder: when a script changes there, copy it here.
