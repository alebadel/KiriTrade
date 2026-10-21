You are one of many independent analysts. You work alone and will not see anyone else's answer.

## Question
For each of calendar 2023, 2024 and 2025: importing countries recorded tuna as Kiribati-origin (the "raw mirror": coded by the catching vessel's flag, usually valued CIF). The raw mirror totals are 81.77 (2023), 97.57 (2024) and 86.93 (2025) USD m. What is the TRUE value of Kiribati's tuna exports in each year?

"True exports" means: the FOB value of fish that Kiribati residents (operators and owners resident in Kiribati) caught and sold to non-residents in that year, whatever the vessel's flag, whatever route the fish took, and whether or not any statistic recorded it as Kiribati's. It is the economic reality, not a figure produced by any statistics office. BPM6 tells you who counts as a resident and when ownership changes; use it to build the whole picture, including fish the mirror misses and fish the mirror wrongly includes. Do NOT stop at the part of the mirror that meets BPM6 tests.

## Evidence
Read ONLY the files in the evidence directory given to you (00_README.md first). Use your own knowledge of the standards, Pacific tuna fisheries, access agreements, joint ventures, how catch is transshipped, landed and traded, and how importers code origin. Do not read anything else on disk.

File 06 holds Kiribati's official statistics (balance-of-payments goods exports, customs returns). You MAY use them as evidence: they tell you what the compiler recorded and, read with the standards, something about the compiler's coverage and practice. They are NOT the answer and NOT the target: the official figure can sit below or above true exports (a compiler may miss resident catch sold at sea, or may count fish that is not a resident's). State in `official_use` how you used them, in at most 60 words.

## Method
1. **Principles first.** Write 4-8 numbered principles (P1, P2, ...) linking the evidence to the true-export concept. Each cites a source (pack paragraph or "model knowledge") and states its uncertainty. Include one principle on how the official figures relate to true exports.
2. **Freeze them.** Do not change them after seeing numbers.
3. **Bridge, one per year.** Start from the raw mirror and walk to true exports with these layers, in this order. Each layer is a signed USD m amount (negative removes, positive adds), with an 80% range (lo, hi) for that layer, a confidence tag ("stated in a source" / "observed in data" / "inferred") and a rationale of at most 50 words citing principle ids and evidence file ids:
   - `L1_valuation`: convert CIF to FOB (remove freight and insurance that importers include).
   - `L2_nonresident_operated`: remove fish caught by Kiribati-flagged vessels whose operator is not resident in Kiribati (chartered, foreign-run, foreign joint-venture partners): a sale between non-residents is not a Kiribati export. Access fees they pay are not goods and are not part of this bridge.
   - `L3_other_origin_coding`: add fish caught by Kiribati-resident operators that importers did NOT code as Kiribati-origin (for example vessels flagged elsewhere, origin coded to the landing or processing country).
   - `L4_unrecorded_routes`: add fish sold by Kiribati residents to non-residents by routes the partner series does not capture (sales at sea to carriers, partners that do not report, landings in third countries, fish not under these HS codes).
   - `L5_treatment`: add or remove for treatment issues that change what counts as a good (goods sent for processing without change of ownership, merchanting, fish that stays in the economy, re-exports).
   - `L6_other`: anything else you believe matters; name it. Use 0 if nothing.
   `true_exports` = raw mirror + sum of layers. Give an 80% range for `true_exports` that reflects how the layer uncertainties combine (not simply the sum of the widths). Use the same principles for all three years; let the numbers differ where the evidence differs (fleet hours, Thai share, official returns).
   Layers are your honest best estimates. If the evidence cannot size a layer, give a wide range, not false precision.
4. **Audit yourself.** In `audit`, list any layer that does not follow from your principles and fix it.

## Rules
- Plain language. No vessel, company or personal names. Do not name the statistical office's or central bank's figures as "wrong" or "right": differences between records are differences of concept, timing and coverage.
- Conditions, not accusations: "if the operator is resident in Kiribati...". Banned words: misreporting, evasion, under-reporting, fraud. Never compare the mirror with licence or access fees.
- Each bridge must reconcile: raw mirror + sum of layers = true_exports (to 0.01).
- USD millions, 2 decimals.

## Output
Valid JSON only, written to the path you are given, exactly this shape:
{
 "principles": [{"id":"P1","statement":"...","source":"...","uncertainty":"..."}],
 "official_use": "...",
 "bridges": [
  {"period":"2023","start":81.77,
   "layers":[{"id":"L1_valuation","value":0.0,"lo80":0.0,"hi80":0.0,"confidence":"inferred","rationale":"...","principles_used":["P1"],"evidence_refs":["01"]}],
   "true_exports":0.0,"true_lo80":0.0,"true_hi80":0.0},
  {"period":"2024","start":97.57, "layers":[...], "true_exports":0.0,"true_lo80":0.0,"true_hi80":0.0},
  {"period":"2025","start":86.93, "layers":[...], "true_exports":0.0,"true_lo80":0.0,"true_hi80":0.0}
 ],
 "audit": "..."
}
Exactly three bridges in that order; exactly six layers, L1 to L6 in order, in each.
