"""Streamlit demo UI — single-page, two-column, zero-friction.

Run locally:   streamlit run web/app.py
Deployed at:   https://rate-sheet-diff-agent-production.up.railway.app

Design principle: the reviewer should land and immediately see the demo
running. No tabs, no setup, no "what do I click first" — sample data is
loaded by default, both halves of the story (the diff *and* the AI email
it produced) are visible at the same time, and the "Email it to me"
button is the loudest thing on the page.

Layout:

    ┌─────────────────────────── HERO ───────────────────────────┐
    │  Title · 1-line value prop · primary CTA                   │
    └────────────────────────────────────────────────────────────┘
    ┌─────────────── METRIC RIBBON (4 stat cards) ───────────────┐
    └────────────────────────────────────────────────────────────┘
    ┌──────────── RE-DATED CALLOUT (only when present) ──────────┐
    └────────────────────────────────────────────────────────────┘
    ┌─────────────────────┐  ┌─────────────────────────────────┐
    │  WHAT CHANGED       │  │  AI-WRITTEN EMAIL               │
    │  (diff tables)      │  │  Subject + body                 │
    │                     │  │  ┌─ Email me a copy ─────────┐  │
    │                     │  │  │  email input + SEND       │  │
    │                     │  │  └───────────────────────────┘  │
    └─────────────────────┘  └─────────────────────────────────┘
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

try:
    for key in ("ANTHROPIC_API_KEY", "RESEND_API_KEY", "RESEND_FROM"):
        if key in st.secrets and not os.environ.get(key):
            os.environ[key] = st.secrets[key]
except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
    pass

import pandas as pd

from core.loader import load_rate_sheet
from core.differ import diff_rate_sheets
from ai.summarizer import summarize_diff
from agent.resend_sender import send_via_resend


st.set_page_config(
    page_title="Rate Sheet Diff Agent",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",  # Get the sidebar out of the way.
)


# ---------------------------------------------------------------------------
# Visual polish — kept tight, only what reliably sticks in Streamlit.
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 4rem;
        max-width: 1280px;
    }
    h1, h2, h3, h4 { letter-spacing: -0.02em !important; }

    /* Hero strip */
    .hero {
        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%);
        color: white;
        padding: 36px 44px;
        border-radius: 20px;
        margin-bottom: 28px;
        box-shadow: 0 10px 30px -10px rgba(79,70,229,.35);
    }
    .hero-eyebrow {
        display: inline-block;
        background: rgba(255,255,255,.18);
        color: white;
        padding: 5px 12px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 14px;
    }
    .hero h1 {
        font-size: 38px !important;
        margin: 0 0 10px 0 !important;
        color: white !important;
        font-weight: 700 !important;
        line-height: 1.1;
    }
    .hero p {
        font-size: 16px;
        line-height: 1.55;
        color: rgba(255,255,255,.92);
        max-width: 720px;
        margin: 0;
    }

    /* Metric cards — bigger, more product-y */
    [data-testid="stMetric"] {
        background: white;
        padding: 20px 22px;
        border-radius: 14px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 2px rgba(15,23,42,.04);
        transition: transform .15s ease;
    }
    [data-testid="stMetric"]:hover { transform: translateY(-2px); }
    [data-testid="stMetricValue"] {
        font-size: 38px !important;
        font-weight: 700 !important;
        color: #0f172a !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748b !important;
        font-weight: 600 !important;
    }
    [data-testid="stMetricDelta"] { font-size: 11px !important; color: #94a3b8 !important; }
    [data-testid="stMetricDelta"] svg { display: none; }

    /* Big primary button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
        color: white !important;
        border: none !important;
        padding: 14px 24px !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 14px rgba(79,70,229,.35) !important;
        transition: all .15s ease !important;
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(79,70,229,.45) !important;
    }
    .stButton > button[kind="primary"]:disabled {
        background: #cbd5e1 !important;
        box-shadow: none !important;
        color: #64748b !important;
    }

    /* Section heading */
    .section-title {
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #4f46e5;
        margin-bottom: 8px;
    }
    .section-subtitle {
        font-size: 22px;
        font-weight: 700;
        color: #0f172a;
        margin: 0 0 4px 0;
        letter-spacing: -0.02em;
    }
    .section-desc {
        font-size: 13px;
        color: #64748b;
        margin: 0 0 16px 0;
    }

    /* Re-dated banner */
    .redated-callout {
        background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
        border: 1px solid #fbbf24;
        border-radius: 14px;
        padding: 18px 22px;
        margin-bottom: 24px;
    }
    .redated-callout-title {
        color: #78350f;
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .redated-callout-body {
        color: #92400e;
        font-size: 13px;
        line-height: 1.55;
    }

    /* Email preview frame */
    .email-frame {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 0;
        overflow: hidden;
    }
    .email-meta {
        background: #f8fafc;
        border-bottom: 1px solid #e2e8f0;
        padding: 14px 20px;
        font-size: 13px;
    }
    .email-meta-row {
        display: flex;
        gap: 12px;
        align-items: baseline;
        margin-bottom: 6px;
    }
    .email-meta-row:last-child { margin-bottom: 0; }
    .email-meta-label {
        color: #94a3b8;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        min-width: 70px;
    }
    .email-meta-value { color: #0f172a; font-weight: 500; }

    /* Send card */
    .send-card {
        background: linear-gradient(135deg, #eef2ff 0%, #ddd6fe 100%);
        border: 1px solid #c7d2fe;
        border-radius: 14px;
        padding: 22px;
        margin-top: 20px;
    }
    .send-card-title {
        font-size: 15px;
        font-weight: 700;
        color: #312e81;
        margin: 0 0 4px 0;
    }
    .send-card-desc {
        font-size: 12.5px;
        color: #4338ca;
        margin: 0 0 14px 0;
        line-height: 1.5;
    }

    /* Status pill */
    .pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
    }
    .pill-success { background: #d1fae5; color: #065f46; }
    .pill-muted   { background: #f1f5f9; color: #64748b; }
    .pill-info    { background: #dbeafe; color: #1e40af; }

    /* Inputs */
    .stTextInput input {
        border-radius: 10px !important;
        border: 1px solid #cbd5e1 !important;
        padding: 10px 14px !important;
        font-size: 14px !important;
    }
    .stTextInput input:focus {
        border-color: #4f46e5 !important;
        box-shadow: 0 0 0 3px rgba(79,70,229,.1) !important;
    }

    /* Radio pills inside expander */
    div[role="radiogroup"] { gap: 6px !important; }
    div[role="radiogroup"] > label {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
        cursor: pointer;
    }
    div[role="radiogroup"] > label:has(input:checked) {
        border-color: #4f46e5;
        background: #eef2ff;
        font-weight: 600;
    }

    /* Dataframe */
    .stDataFrame { border-radius: 10px; overflow: hidden; }

    /* Hide Streamlit chrome */
    #MainMenu, footer, header, [data-testid="stToolbar"] { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
      <span class="hero-eyebrow">AI Automation · Take-home Showcase</span>
      <h1>Compare two rate sheets. Get the email written for you.</h1>
      <p>Drop in two Excel rate sheets — the deterministic engine finds every change
      (including <b>re-dated lanes</b> that naive diffs miss), and Claude narrates
      it into a business-readable email you can send to yourself in one click.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data source (sticky bar — collapsed-by-default expander)
# ---------------------------------------------------------------------------

# Default: bundled test fixtures (small + every change type). Reviewer
# can switch to the full 783-row sample or upload their own from the
# expander below.
DEFAULT_OLD = ROOT / "data" / "Test_OLD.xlsx"
DEFAULT_NEW = ROOT / "data" / "Test_NEW.xlsx"

if "data_choice" not in st.session_state:
    st.session_state["data_choice"] = "Test fixtures (recommended)"

old_path = DEFAULT_OLD
new_path = DEFAULT_NEW
data_label = "Test fixtures · 14 rows · one of every change type"

with st.expander("📂  Data source · " + data_label, expanded=False):
    choice = st.radio(
        "Pick data source",
        ["Test fixtures (recommended)",
         "Full 783-row brief sample",
         "Upload my own .xlsx files"],
        key="data_choice",
        horizontal=True,
        label_visibility="collapsed",
    )

    if choice == "Test fixtures (recommended)":
        old_path = ROOT / "data" / "Test_OLD.xlsx"
        new_path = ROOT / "data" / "Test_NEW.xlsx"
        data_label = "Test fixtures · 14 rows · one of every change type"
    elif choice == "Full 783-row brief sample":
        old_path = ROOT / "data" / "Example_1.xlsx"
        new_path = ROOT / "data" / "Example_2.xlsx"
        data_label = "Original brief · 783 rows · 6 real changes"
    else:
        col_u1, col_u2 = st.columns(2)
        f_old = col_u1.file_uploader("OLD .xlsx", type=["xlsx"])
        f_new = col_u2.file_uploader("NEW .xlsx", type=["xlsx"])
        if f_old and f_new:
            tmp = Path("/tmp"); tmp.mkdir(parents=True, exist_ok=True)
            old_path = tmp / "old.xlsx"
            new_path = tmp / "new.xlsx"
            old_path.write_bytes(f_old.getvalue())
            new_path.write_bytes(f_new.getvalue())
            data_label = f"Uploaded · {f_old.name} vs {f_new.name}"
        else:
            st.info("Upload both files to continue with custom data.")
            old_path = new_path = None


if not (old_path and new_path):
    st.stop()


# ---------------------------------------------------------------------------
# Compute diff + draft email (cached on data identity)
# ---------------------------------------------------------------------------

with st.spinner("Loading sheets and computing diff…"):
    old = load_rate_sheet(old_path)
    new = load_rate_sheet(new_path)
    diff = diff_rate_sheets(old, new)

cache_key = f"draft::{old_path.name}::{new_path.name}::{len(diff.updated)}::{len(diff.redated)}"
if st.session_state.get("draft_key") != cache_key:
    with st.spinner("Claude is writing the email summary…"):
        st.session_state["draft"] = summarize_diff(diff)
        st.session_state["draft_key"] = cache_key

draft = st.session_state["draft"]
raw = diff.counts_raw()
rec = diff.counts_reconciled()


# ---------------------------------------------------------------------------
# Metric ribbon
# ---------------------------------------------------------------------------

m1, m2, m3, m4 = st.columns(4)
m1.metric("Updated", rec["updated"])
m2.metric("Re-dated lanes", rec["redated"])
m3.metric("New", rec["new"], delta=f"raw: {raw['new']}", delta_color="off")
m4.metric("Deleted", rec["deleted"], delta=f"raw: {raw['deleted']}", delta_color="off")


# ---------------------------------------------------------------------------
# Re-dated callout (only when relevant — the centerpiece)
# ---------------------------------------------------------------------------

st.markdown("<br>", unsafe_allow_html=True)

if diff.redated:
    redated_list = "<br>".join(
        f"&nbsp;&nbsp;<b>Customer {p.deleted.customer}</b> · "
        f"{p.deleted.origin} → {p.deleted.destination} · "
        f"Effective Date shifted <b>{p.old_effective.isoformat()} → {p.new_effective.isoformat()}</b>"
        for p in diff.redated
    )
    st.markdown(
        f"""
        <div class="redated-callout">
          <div class="redated-callout-title">🔁 Re-dated lane{'s' if len(diff.redated)>1 else ''} detected — the centerpiece case</div>
          <div class="redated-callout-body">
            A naive row-level diff would report {len(diff.redated)} of the
            New + {len(diff.redated)} of the Deleted rows as unrelated changes.
            They are the same logical lane being re-issued on a new Effective Date.
            The reconciliation pass pairs them so the email reflects the real change.
            <br><br>{redated_list}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Two-column main: diff (left) + email + send (right)
# ---------------------------------------------------------------------------

left, right = st.columns([5, 7], gap="large")


# --- LEFT: What changed --------------------------------------------------
with left:
    st.markdown(
        """
        <div>
          <div class="section-title">▸ Step 1</div>
          <div class="section-subtitle">What changed</div>
          <p class="section-desc">Deterministic engine output — pure Python, fully auditable, the LLM never touches these numbers.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if diff.updated:
        st.markdown("**Updated rows**")
        rows = []
        for u in diff.updated:
            for d in u.deltas:
                arrow = ""
                if d.field == "rate":
                    arrow = " ↓" if d.new < d.old else " ↑"
                rows.append({
                    "Customer": u.new.customer,
                    "Lane": f"{u.new.origin} → {u.new.destination}",
                    "Effective": u.new.effective_date.isoformat(),
                    "Field": d.field.replace("_", " "),
                    "Old → New": f"{d.old} → {d.new}{arrow}",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if diff.new_after_reconcile:
        st.markdown("**Genuinely new lanes**")
        st.dataframe(pd.DataFrame([{
            "Customer": r.customer,
            "Lane": f"{r.origin} → {r.destination}",
            "Effective": r.effective_date.isoformat(),
            "Rate": r.rate,
        } for r in diff.new_after_reconcile]), use_container_width=True, hide_index=True)

    if diff.deleted_after_reconcile:
        st.markdown("**Genuinely deleted lanes**")
        st.dataframe(pd.DataFrame([{
            "Customer": r.customer,
            "Lane": f"{r.origin} → {r.destination}",
            "Effective": r.effective_date.isoformat(),
            "Rate": r.rate,
        } for r in diff.deleted_after_reconcile]), use_container_width=True, hide_index=True)

    if not (diff.updated or diff.new_after_reconcile or diff.deleted_after_reconcile):
        st.caption("No changes detected between the two sheets.")


# --- RIGHT: AI-written email + Send --------------------------------------
with right:
    st.markdown(
        """
        <div>
          <div class="section-title">▸ Step 2</div>
          <div class="section-subtitle">AI-written email</div>
          <p class="section-desc">Claude reads the structured diff (left) and narrates it into a business email. Numbers are locked — model only writes prose.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    pill_class = "pill-success" if draft.source == "claude" else "pill-muted"
    pill_text = "✓ Narrated by Claude · Sonnet 4" if draft.source == "claude" else f"Deterministic renderer · {draft.source}"
    st.markdown(f'<span class="pill {pill_class}">{pill_text}</span>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # Email preview with a fake mail header
    st.markdown(
        f"""
        <div class="email-frame">
          <div class="email-meta">
            <div class="email-meta-row">
              <span class="email-meta-label">From</span>
              <span class="email-meta-value">Rate Sheet Demo &lt;onboarding@resend.dev&gt;</span>
            </div>
            <div class="email-meta-row">
              <span class="email-meta-label">Subject</span>
              <span class="email-meta-value">{draft.subject}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.components.v1.html(
        f"<div style='border:1px solid #e2e8f0;border-top:none;border-radius:0 0 14px 14px;"
        f"padding:24px;background:white;font-family:-apple-system,Inter,sans-serif'>"
        f"{draft.html}</div>",
        height=480, scrolling=True,
    )

    # --- The headline action: SEND ---
    if "sends_this_session" not in st.session_state:
        st.session_state["sends_this_session"] = 0
    MAX_SENDS = 3

    resend_ready = bool(os.environ.get("RESEND_API_KEY"))

    st.markdown(
        f"""
        <div class="send-card">
          <div class="send-card-title">✉️  Email this to yourself</div>
          <div class="send-card-desc">
            {"Sends a real email via Resend. Recipient is locked to whatever you type below — no relay. "
             f"Up to {MAX_SENDS} sends per browser session."
             if resend_ready else
             "Send is disabled — server has no RESEND_API_KEY. The preview above is the deliverable."}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_in, col_btn = st.columns([3, 2])
    with col_in:
        recipient = st.text_input(
            "Your email",
            placeholder="you@yourcompany.com",
            label_visibility="collapsed",
        )
    with col_btn:
        clicked = st.button(
            "Email this to me  →",
            type="primary",
            disabled=not resend_ready,
            use_container_width=True,
        )

    # Send-state pill
    if not resend_ready:
        st.markdown(
            '<span class="pill pill-muted">Sending disabled · server has no Resend key</span>',
            unsafe_allow_html=True,
        )
    else:
        remaining = MAX_SENDS - st.session_state["sends_this_session"]
        st.markdown(
            f'<span class="pill pill-info">{remaining} send{"s" if remaining != 1 else ""} remaining this session</span>',
            unsafe_allow_html=True,
        )

    def _valid_email(s: str) -> bool:
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))

    if clicked:
        if not _valid_email(recipient):
            st.error("Enter a valid email address.")
        elif st.session_state["sends_this_session"] >= MAX_SENDS:
            st.error("Per-session send limit reached. Reload the page to send more.")
        else:
            with st.spinner(f"Sending to {recipient}…"):
                result = send_via_resend(draft.subject, draft.html, recipient)
            if result.ok:
                st.session_state["sends_this_session"] += 1
                st.success(f"✓ Sent to {recipient}")
                st.caption(
                    f"Message ID: `{result.message_id}` · Sender: onboarding@resend.dev "
                    "(Resend's shared demo domain). Check spam if you don't see it within a minute."
                )
                st.balloons()
            else:
                st.error(result.detail)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div style="margin-top:60px;padding-top:24px;border-top:1px solid #e2e8f0;
                text-align:center;font-size:12px;color:#94a3b8">
      Built as a take-home AI-automation showcase ·
      <a href="https://github.com/rmptue/rate-sheet-diff-agent"
         style="color:#4f46e5;text-decoration:none;font-weight:500">View source on GitHub →</a>
    </div>
    """,
    unsafe_allow_html=True,
)
