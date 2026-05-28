"""Tool-calling orchestrator.

The deterministic engine and the AI summarizer are wrapped as tools that
Claude can invoke in a tool-use loop. The model decides the sequence —
in practice it always ends up running:

    read_rate_sheets -> compute_diff -> summarize_changes -> send_email

but the value of doing it this way (vs. a hard-coded script) is that the
agent could plausibly skip steps when a step fails, retry, or branch on
empty diffs. It's also the shape an interviewer expects when "AI agent"
is in the requirements.

If ``ANTHROPIC_API_KEY`` is not present, the orchestrator gracefully
degrades to a *scripted* run: it calls the same four tools in the same
order without the LLM in the loop, so the demo still works offline.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from typing import Any

from core.loader import load_rate_sheet
from core.differ import diff_rate_sheets
from core.models import DiffResult
from ai.summarizer import summarize_diff, EmailDraft
from agent.email_sender import send_email, SendResult


# --- Tool implementations -----------------------------------------------
# Each tool returns plain JSON-friendly dicts so the model can chain them.

_STATE: dict[str, Any] = {}


def tool_read_rate_sheets(old_path: str, new_path: str) -> dict:
    old = load_rate_sheet(old_path)
    new = load_rate_sheet(new_path)
    _STATE["old"] = old
    _STATE["new"] = new
    return {"old_records": len(old), "new_records": len(new), "ok": True}


def tool_compute_diff() -> dict:
    if "old" not in _STATE or "new" not in _STATE:
        return {"ok": False, "error": "rate sheets not loaded yet — call read_rate_sheets first"}
    d = diff_rate_sheets(_STATE["old"], _STATE["new"])
    _STATE["diff"] = d
    return {"ok": True, "diff": d.to_json_dict()}


def tool_summarize_changes() -> dict:
    if "diff" not in _STATE:
        return {"ok": False, "error": "no diff in state — call compute_diff first"}
    draft = summarize_diff(_STATE["diff"])
    _STATE["draft"] = draft
    return {"ok": True, "subject": draft.subject, "source": draft.source, "html_length": len(draft.html)}


def tool_send_email(recipient: str, sender: str = "gmail-api", dry_run: bool = True) -> dict:
    if "draft" not in _STATE:
        return {"ok": False, "error": "no email draft — call summarize_changes first"}
    draft: EmailDraft = _STATE["draft"]
    res = send_email(draft.subject, draft.html, recipient=recipient, sender=sender, dry_run=dry_run)
    return {"ok": res.ok, "backend": res.backend, "detail": res.detail}


TOOL_REGISTRY = {
    "read_rate_sheets": tool_read_rate_sheets,
    "compute_diff": tool_compute_diff,
    "summarize_changes": tool_summarize_changes,
    "send_email": tool_send_email,
}


TOOL_SCHEMA = [
    {
        "name": "read_rate_sheets",
        "description": "Load two Excel rate sheets (OLD and NEW) from disk and normalize their dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "old_path": {"type": "string"},
                "new_path": {"type": "string"},
            },
            "required": ["old_path", "new_path"],
        },
    },
    {
        "name": "compute_diff",
        "description": "Compute a deterministic diff (New/Updated/Deleted + re-dated reconciliation) between the loaded sheets.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "summarize_changes",
        "description": "Use Claude to draft a business-readable HTML email summary of the diff.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_email",
        "description": "Send the drafted email. dry_run=true just prints it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string"},
                "sender": {"type": "string", "enum": ["gmail-api", "smtp"]},
                "dry_run": {"type": "boolean"},
            },
            "required": ["recipient"],
        },
    },
]


def _scripted_run(old_path: str, new_path: str, recipient: str, sender: str, dry_run: bool) -> dict:
    """Fallback path: same tool sequence, no LLM in the loop."""
    out = {}
    out["read"] = tool_read_rate_sheets(old_path, new_path)
    out["diff"] = tool_compute_diff()
    out["summary"] = tool_summarize_changes()
    out["send"] = tool_send_email(recipient=recipient, sender=sender, dry_run=dry_run)
    return out


def run_agent(old_path: str, new_path: str, recipient: str, sender: str = "gmail-api",
              dry_run: bool = True, max_turns: int = 8) -> dict:
    """Run the tool-calling loop, or the scripted fallback if no API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[agent] ANTHROPIC_API_KEY not set — running scripted fallback (no LLM in the loop).")
        return _scripted_run(old_path, new_path, recipient, sender, dry_run)

    try:
        from anthropic import Anthropic
    except ImportError:
        print("[agent] anthropic SDK not installed — running scripted fallback.")
        return _scripted_run(old_path, new_path, recipient, sender, dry_run)

    client = Anthropic(api_key=api_key)
    system_prompt = (
        "You are a rate-sheet diff agent. Use the provided tools in order: "
        "read_rate_sheets, then compute_diff, then summarize_changes, then send_email. "
        "Always pass dry_run=true unless the user explicitly said otherwise. "
        "Stop after send_email returns ok."
    )
    user_msg = (
        f"Compare {old_path} (OLD) against {new_path} (NEW), summarize the changes, "
        f"and send the email to {recipient} via the {sender} backend. dry_run={str(dry_run).lower()}."
    )

    messages: list[dict] = [{"role": "user", "content": user_msg}]
    trace: list[dict] = []

    for _ in range(max_turns):
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            tools=TOOL_SCHEMA,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            trace.append({"final": "model stopped without tool use"})
            break

        tool_results = []
        for block in resp.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            fn = TOOL_REGISTRY.get(block.name)
            if not fn:
                result = {"ok": False, "error": f"unknown tool {block.name}"}
            else:
                try:
                    result = fn(**block.input)
                except Exception as e:  # noqa: BLE001
                    result = {"ok": False, "error": str(e)}
            trace.append({"tool": block.name, "input": block.input, "output": result})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    return {"trace": trace, "state_keys": list(_STATE)}


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Rate-sheet diff agent")
    ap.add_argument("--old", default="data/Example_1.xlsx")
    ap.add_argument("--new", default="data/Example_2.xlsx")
    ap.add_argument("--to", default=os.environ.get("RECIPIENT_EMAIL", "ops@example.com"))
    ap.add_argument("--sender", choices=["gmail-api", "smtp"], default="gmail-api")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Print the email instead of sending it (default: on)")
    ap.add_argument("--send", dest="dry_run", action="store_false",
                    help="Actually send the email (disables --dry-run)")
    args = ap.parse_args()

    result = run_agent(args.old, args.new, args.to, sender=args.sender, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str)[:4000])


if __name__ == "__main__":
    _cli()
