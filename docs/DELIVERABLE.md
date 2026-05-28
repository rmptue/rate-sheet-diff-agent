# Rate Sheet Diff Agent — Deliverable

## 1. AI tech used (and why)

| Component                | Tech                              | Why                                                                                              |
| ------------------------ | --------------------------------- | ------------------------------------------------------------------------------------------------ |
| Narration                | **Anthropic Claude (Sonnet 4)**   | Best-in-class long-context summarization; strong instruction-following for "narrate, don't compute". |
| Tool-calling agent       | **Anthropic SDK tool-use loop**   | Lets the model orchestrate read → diff → summarize → send. Same control-flow shape as Bedrock / Azure AI Foundry agents — portable. |
| Deterministic diff       | **Pure Python** (pandas + dicts)  | Pricing data must be auditable. An LLM is **not** allowed to decide whether two rates differ.    |
| No-code surface          | **n8n workflow** + **Streamlit**  | Two demo faces: business users (n8n, Streamlit) vs. engineers (CLI agent). Mirrors how this would actually be sold internally. |
| Email                    | **Gmail API (OAuth)** + **SMTP fallback** | OAuth shows modern best practice; App-Password SMTP guarantees the live demo always sends.   |

**The single non-obvious AI design choice:** the LLM lives *downstream*
of a deterministic engine. The engine produces a structured `DiffResult`;
the LLM only ever narrates it. The prompt in
[`ai/prompts.py`](../ai/prompts.py) explicitly forbids the model from
recomputing or restating any number. This is the pattern that turns
"AI demo" into "AI a CFO would sign off on."

## 2. Prompts, agent instructions, workflow logic

- **System prompt:** [`ai/prompts.py`](../ai/prompts.py) — `SUMMARY_PROMPT_V1`.
  Versioned by constant so it can be swapped / A/B-tested.
- **Agent system instructions:** see `run_agent()` in
  [`agent/orchestrator.py`](../agent/orchestrator.py) — instructs Claude
  to call the four tools in order, always default `dry_run=true`, and
  stop after a successful send.
- **Tool schemas:** `TOOL_SCHEMA` in the same file. Four tools:
  `read_rate_sheets`, `compute_diff`, `summarize_changes`, `send_email`.
- **Workflow logic (n8n):** [`n8n/workflow.json`](../n8n/workflow.json)
  is structurally identical: manual trigger → read both files → HTTP
  call into the Python diff engine → Anthropic node for summary → Gmail
  node for send.

## 3. End-to-end workflow

```
            ┌────────────────┐   ┌────────────────┐
            │ Example_1.xlsx │   │ Example_2.xlsx │   (mixed date types — normalized at load)
            └────────┬───────┘   └───────┬────────┘
                     │                   │
                     ▼                   ▼
              ┌──────────────────────────────┐
              │ core.loader.load_rate_sheet  │  ← dates coerced to datetime.date
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ core.differ.diff_rate_sheets │  ← 1 New / 1 Deleted / 4 Updated
              │  + re-dated reconciliation   │     → 0 New / 0 Deleted / 4 Updated / 1 Re-dated
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ ai.summarizer.summarize_diff │  ← Claude narrates (numbers locked)
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ agent.email_sender.send_email│  ← Gmail API / SMTP / dry-run
              └──────────────────────────────┘

        Orchestrated by agent.orchestrator.run_agent() — Claude tool-use loop,
        with a scripted fallback path when ANTHROPIC_API_KEY is absent.
```

**Why the re-dated reconciliation is the centerpiece:**
the example data hides a single logical lane (`Customer 115 / HAN / AZ`)
whose Effective Date shifts from `2026-06-01` to `2026-07-01`. A naive
row-level diff reports this as `1 New + 1 Deleted` and pollutes the
summary with two unrelated-looking changes. The reconciliation pass
detects that the deleted and new rows share `Customer + Origin +
Destination` and only differ on `Effective Date`, pairs them into a
`RE-DATED` bucket, and removes them from the New/Deleted lists. The
final email now reads "0 new, 0 deleted, 4 updated, 1 re-dated" with a
plain-English explanation of the re-dating — which is what an actual
operator wants to see.

## 4. How to run the demo

```bash
# from the repo root
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# (optional — without this, the AI layer renders a deterministic fallback)
export ANTHROPIC_API_KEY=sk-ant-...

# 1. CLI agent (always dry-run unless --send is passed)
python -m agent.orchestrator
#   or:  ./run_demo.sh

# 2. Streamlit UI
streamlit run web/app.py

# 3. n8n
#    n8n -> Workflows -> Import from File -> n8n/workflow.json
#    Replace Anthropic + Gmail credentials in the imported workflow.

# 4. Tests
pytest -v
```
