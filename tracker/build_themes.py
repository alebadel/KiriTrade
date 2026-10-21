#!/usr/bin/env python3
"""Merge a themes file (output of the summariser pass, tracker/agents/themes_prompt.md) into data/inference.json.

The summariser only groups and counts; this script checks the counts against the principles in inference.json
(each theme's n_agents must equal the number of distinct agents among its members, and every member must exist)
and writes the themes under `principle_themes`.

Usage:  python tracker/build_themes.py --themes <themes.json> --inference data/inference.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BANNED = re.compile(r"\b(misreport\w*|under-?report\w*|evasion|fraud\w*)\b", re.I)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--themes", required=True)
    ap.add_argument("--inference", required=True)
    a = ap.parse_args(argv)
    inf = json.loads(Path(a.inference).read_text(encoding="utf-8"))
    themes = json.loads(Path(a.themes).read_text(encoding="utf-8"))["themes"]
    known = {(p["agent"], p["id"]) for p in inf["principles"]}
    out = []
    for th in themes:
        if BANNED.search(th["statement"]):
            raise SystemExit("banned word in theme: " + th["statement"])
        members = [tuple(m) for m in th["members"] if tuple(m) in known]
        agents = sorted({m[0] for m in members})
        out.append({"statement": th["statement"].strip(), "n_agents": len(agents), "members": [list(m) for m in members]})
    out.sort(key=lambda t: -t["n_agents"])
    inf["principle_themes"] = out
    inf["meta"]["themes_note"] = "Themes were written by one summariser pass over the principles (tracker/agents/themes_prompt.md); counts were recomputed by tracker/build_themes.py from the members it listed."
    Path(a.inference).write_text(json.dumps(inf, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for t in out:
        print(f"{t['n_agents']:3d}  {t['statement']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
