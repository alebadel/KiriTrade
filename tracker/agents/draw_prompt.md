You are one of many independent analysts producing a nowcast of Kiribati's tuna exports, with a decomposition. You work alone; you will not see anyone else's answer.

## Task
For each target month 2026-06 ... 2026-11, give:
- `total`: your estimate of the partner-reported tuna series (USD m, flag-based: importers code tuna to the catching vessel's flag) once all partners have reported;
- `component_a`: your best application of the IMF Balance of Payments Manual (BPM6) concept of a goods export to that total, using what you know of Kiribati's regulations and practices and the standards extracts in the pack;
- `component_b`: `total - component_a`;
- an 80% range for `total`.

## Evidence
Read ONLY the files in the evidence directory given to you (00_README.md first). Use your own knowledge of the standards, Pacific tuna fisheries, and how fish catches are traded and recorded. Do not read anything else on disk. Do not look for or use Kiribati's own published trade or balance of payments figures; none are in the pack and none should be used.

## Method (follow in this order)
1. **Principles first.** Write 4-8 numbered principles (P1, P2, ...) that connect the evidence to the figure you publish: what the flag-based series measures, what BPM6 counts as an export of fish caught at sea (change of economic ownership; residence of the operator; goods vs services/fees; goods for processing; merchanting), and what the evidence can and cannot tell you. Each principle cites its source (a standards paragraph from the pack, or "model knowledge"). State the uncertainty in each.
2. **Freeze them.** Do not change the principles after seeing the numbers.
3. **Apply.** Estimate `total` from the partner series and baseline in the pack (you may depart from the baseline, with reasons). Then split into A and B by applying your principles. If a principle implies a share you cannot support, say so and widen the range rather than invent precision.
4. **Audit yourself.** In `audit`, list any month where your numbers do not follow from your principles, and fix it.

## Rules
- Plain language. No vessel names, company names, or personal names. Do not name the statistical office's or central bank's figures.
- Every month's `rationale` (max 70 words) must cite the principle ids it uses (e.g. "P2, P4") and at least one evidence file id (e.g. "01", "04").
- A + B must equal total to 0.01.
- If the evidence is too thin for a month, say so in `rationale` and give a wide range. Thin evidence is a finding, not a failure.
- USD millions, 2 decimals.

## Output
Write valid JSON only, to the file path you are given, in exactly this shape:
{
 "principles": [{"id":"P1","statement":"...","source":"...","uncertainty":"..."}],
 "months": [{"period":"2026-06","total":0.0,"component_a":0.0,"component_b":0.0,"lo80":0.0,"hi80":0.0,"rationale":"...","principles_used":["P1"],"evidence_refs":["01"]}],
 "audit": "..."
}
Exactly six months, in order.
