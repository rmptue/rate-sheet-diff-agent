"""AI narration layer.

This module takes a fully-computed ``DiffResult`` from Layer 1 and asks
Claude to write a business-readable HTML email summary plus a subject
line. The model is forbidden from recomputing or altering numbers; its
job is narration only. See ``ai/prompts.py`` for the exact contract.

If the ``ANTHROPIC_API_KEY`` environment variable is not set, this module
gracefully falls back to a deterministic local renderer so the rest of
the pipeline (and the demo) still works end-to-end without network or
billing. The fallback is clearly labeled in the rendered output.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from core.models import DiffResult
from .prompts import SUMMARY_PROMPT_V1


CLAUDE_MODEL = "claude-sonnet-4-20250514"


@dataclass
class EmailDraft:
    subject: str
    html: str
    source: str  # "claude" or "fallback"


def _render_fallback(diff: DiffResult) -> EmailDraft:
    """Deterministic HTML renderer used when no API key is configured.

    Keeps demos and tests fully offline-runnable. Intentionally plain.
    """
    c = diff.counts_reconciled()
    raw = diff.counts_raw()

    rows_html = []
    for u in diff.updated:
        for d in u.deltas:
            rows_html.append(
                "<tr>"
                f"<td>{u.new.customer}</td>"
                f"<td>{u.new.origin}</td>"
                f"<td>{u.new.destination}</td>"
                f"<td>{u.new.effective_date.isoformat()}</td>"
                f"<td>{d.field}</td>"
                f"<td>{d.old}</td>"
                f"<td>{d.new}</td>"
                "</tr>"
            )
    updated_table = (
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:sans-serif;font-size:13px'>"
        "<thead><tr style='background:#f0f0f0'>"
        "<th>Customer</th><th>Origin</th><th>Destination</th><th>Effective</th>"
        "<th>Field</th><th>Old</th><th>New</th></tr></thead>"
        f"<tbody>{''.join(rows_html) or '<tr><td colspan=7>No updated rows.</td></tr>'}</tbody></table>"
    )

    redated_html = "".join(
        f"<li>Customer <b>{p.deleted.customer}</b> &mdash; {p.deleted.origin} &rarr; {p.deleted.destination}: "
        f"Effective Date shifted <b>{p.old_effective.isoformat()} &rarr; {p.new_effective.isoformat()}</b> "
        f"(same lane re-issued, not a new lane or a cancellation).</li>"
        for p in diff.redated
    ) or "<li>None.</li>"

    html = f"""
<div style='font-family:sans-serif;font-size:14px;color:#222'>
  <p><b>Rate Sheet Change Summary</b></p>
  <p>Reconciled view: <b>{c['new']}</b> new, <b>{c['deleted']}</b> deleted,
     <b>{c['updated']}</b> updated, <b>{c['redated']}</b> re-dated.</p>

  <h3>Updated rows</h3>
  {updated_table}

  <h3>Re-dated lanes</h3>
  <ul>{redated_html}</ul>

  <p style='color:#888;font-size:12px'>
    Raw row-level counts (before reconciliation):
    {raw['new']} new / {raw['deleted']} deleted / {raw['updated']} updated.
    Re-dated lanes appear as 1 New + 1 Deleted in the raw view; the
    reconciled view pairs them so the email reflects the real change.
  </p>
  <p style='color:#aaa;font-size:11px'>[Rendered locally — ANTHROPIC_API_KEY not set]</p>
</div>
""".strip()

    subject = (
        f"Rate sheet update: {c['updated']} updated, {c['redated']} re-dated"
        + (f", {c['new']} new, {c['deleted']} deleted" if (c['new'] or c['deleted']) else "")
    )
    return EmailDraft(subject=subject, html=html, source="fallback")


def summarize_diff(diff: DiffResult) -> EmailDraft:
    """Return an EmailDraft for the given diff, using Claude when available."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _render_fallback(diff)

    try:
        # Local import so the rest of the project doesn't require the SDK.
        from anthropic import Anthropic
    except ImportError:
        return _render_fallback(diff)

    client = Anthropic(api_key=api_key)
    diff_json = json.dumps(diff.to_json_dict(), default=str, indent=2)

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SUMMARY_PROMPT_V1,
        messages=[{"role": "user", "content": f"Diff JSON:\n```json\n{diff_json}\n```"}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text").strip()

    # Tolerate models that wrap their JSON in a fenced code block.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
        return EmailDraft(subject=parsed["subject"], html=parsed["html"], source="claude")
    except (json.JSONDecodeError, KeyError):
        # If the model misbehaves, fall back rather than ship malformed email.
        fallback = _render_fallback(diff)
        fallback.source = "fallback-after-parse-error"
        return fallback
