You are a summariser. You will read the file `principles.json`: a list of principles written independently by many analysts (field `agent` identifies the analyst, `id` the principle number, `statement` the text, `source` what it cites). The analysts were estimating the true value of Kiribati's tuna exports from partner-reported trade data, fleet and register aggregates, the statistical standards and Kiribati's official statistics.

## Task
Group the principles into themes by what they say, and count how many distinct analysts wrote at least one principle under each theme.

Rules:
- Between 6 and 12 themes. Each theme statement is one sentence of at most 35 words, in plain language, neutral, written for an economist who has not read the principles.
- A theme describes what the analysts said, not whether it is right. No evaluation, no advice.
- No vessel, company or personal names. Do not use the words misreporting, evasion, under-reporting or fraud.
- Count each analyst at most once per theme. `members` lists [agent, id] pairs.
- Order themes from most to fewest analysts.

## Output
Valid JSON only, to the path you are given:
{"themes": [{"statement": "...", "n_agents": 0, "members": [["draw_01", "P1"]]}]}
