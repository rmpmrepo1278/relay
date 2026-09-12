# Career Coach — Hermes command routing (skill)

When Rohit sends any of these commands in Telegram, handle them by running the coach CLI on the
host and responding with its output. Do NOT invent coach data yourself — always call the CLI.

Host access (same as career_ops_pipeline uses):
`ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i /opt/data/.ssh/id_ed25519 rohit@127.0.0.1 "cd /home/rohit/.hermes/scripts && python3 career_coach.py <args>"`

You may also use any working terminal path to the host. Run on the HOST, never in your own container,
because state must live at `~/.hermes/state/career_coach` and `~/.hermes/data/career/coach`.

## Commands

### /story
- `/story` — start guided capture. Ask for the 6 fields IN ORDER (one message per field, from the
  coach's prompts): title → situation → task → action → result → tags. Echo each field back briefly,
  then at the end run:
  `python3 career_coach.py add --json '{"title":"...","situation":"...","task":"...","action":"...","result":"...","metrics":"...","competencies":["..."]}'`
  Report the JSON output (confidence /5 + hints) conversationally and offer refinements.
- `/story list` — `python3 career_coach.py list`
- `/story show <id>` — `python3 career_coach.py show <id>`
- `/story refine <id>` — ask which field, then run `refine <id> --field <f> --value "<v>"`.

### /mock [topic]
Topic maps to competency: program/strategy→"Program Strategy & Portfolio",
delivery/scale→"Delivery at Scale", stakeholder/exec/steerco→"Stakeholder & Executive Communication",
financial/budget/commercial→"Financial & Commercial", risk/governance→"Risk, Dependency & Governance",
leadership/talent→"Leadership & Talent", else generic.
1. `python3 career_coach.py question --competency "<topic>"` → present the question.
2. After Rohit answers, score with `python3 career_coach.py score --text "<answer>" --competency "<topic>"`.
3. Reply conversationally: overall /5 (structure, metrics, clarity, impact), the tips list, a concrete
   rewrite suggestion of the weakest sentence, then offer "next question?".

### /coach <text>
`python3 career_coach.py coach --text "<past your text>"` → summarize the dims + tips for speech/clarity.

### /linkedin
`python3 career_coach.py linkedin` → show headline, About, outreach template, and a content idea.

### /career
Progress: `python3 career_coach.py weekly` (stats) + `python3 career_coach.py list` (stories). Summarize:
stories banked + avg confidence, interview count + avg score, weakest competency, coverage gaps.

## Ground rules
- Always run real CLI calls; never fabricate metrics/confidence.
- Keep answers concise for Telegram; reformat CLI JSON into short bullet lists.
- Multi-turn capture: keep the accumulated fields in the conversation; only run `add` at the end.
- Do NOT long-poll the Telegram bot or fight the gateway's getUpdates (getUpdates 409 conflict rule — see docs/agent-parliament.md).