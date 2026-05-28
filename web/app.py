"""Streamlit demo UI — sidebar-driven layout with tabs.

Run locally:   streamlit run web/app.py
Deployed at:   https://rate-sheet-diff-agent-production.up.railway.app

Design choices that survive Streamlit's CSS quirks:
    - Theme color + background set via .streamlit/config.toml (native, not CSS).
    - Sidebar for controls so they never compete with the main content.
    - st.container(border=True) instead of custom card divs — bordered
      cards that Streamlit actually renders consistently.
    - st.tabs() for switching between Overview / Detail / Email — fewer
      vertical scroll-to-find moments.
    - Minimal, conservative CSS: only the bits that reliably stick
      (block-container padding, headline weight, metric padding).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

# Mirror Streamlit / Railway secrets into env.
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
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Light, conservative CSS — only what reliably sticks in Streamlit.
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1200px; }

    /* Tighter headings */
    h1 { font-weight: 700 !important; letter-spacing: -0.02em !important; }
    h2 { font-weight: 600 !important; letter-spacing: -0.01em !important; margin-top: 0 !important; }
    h3 { font-weight: 600 !important; letter-spacing: -0.01em !important; }

    /* Metric cards — bigger numbers, smaller labels */
    [data-testid="stMetric"] {
        background: white;
        padding: 18px 20px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
    }
    [data-testid="stMetricValue"] {
        font-size: 32px !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #64748b !important;
        font-weight: 600 !important;
    }
    [data-testid="stMetricDelta"] { font-size: 11px !important; }
    [data-testid="stMetricDelta"] svg { display: none; }

    /* Hide Streamlit chrome */
    #MainMenu, footer, header { visibility: hidden; }

    /* Sidebar polish */
    [data-testid="stSidebar"] {
        background: white;
        border-right: 1px solid #e2e8f0;
    }
    [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px 10px 0 0;
        padding: 10px 18px;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background: #4f46e5 !important;
        color: white !important;
        border-color: #4f46e5 !important;
    }

    /* Dataframe — clean borders */
    .stDataFrame { border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar — data source + status
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### Rate Sheet Diff Agent")
    st.caption("AI automation showcase")
    st.divider()

    st.markdown("**Data source**")
    source = st.radio(
        "Data source",
        ["Test fixtures",
         "Full sample (783 rows)",
         "Upload my own"],
        label_visibility="collapsed",
    )

    uploaded_old = uploaded_new = None
    if source == "Upload my own":
        uploaded_old = st.file_uploader("OLD .xlsx", type=["xlsx"], key="old")
        uploaded_new = st.file_uploader("NEW .xlsx", type=["xlsx"], key="new")

    st.divider()
    st.markdown("**Status**")
    claude_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    resend_ok = bool(os.environ.get("RESEND_API_KEY"))
    st.markdown(f"{'🟢' if claude_ok else '⚪'} Claude narration")
    st.markdown(f"{'🟢' if resend_ok else '⚪'} Resend email")

    st.divider()
    st.caption(
        "[GitHub repo](https://github.com/rmptue/rate-sheet-diff-agent) · "
        "Built as a take-home AI automation showcase."
    )


# ---------------------------------------------------------------------------
# Resolve data source
# ---------------------------------------------------------------------------

old_path: Path | None = None
new_path: Path | None = None
data_label = ""

if source == "Test fixtures":
    old_path = ROOT / "data" / "Test_OLD.xlsx"
    new_path = ROOT / "data" / "Test_NEW.xlsx"
    data_label = "Test fixtures · 14 rows · one of every change type"
elif source == "Full sample (783 rows)":
    old_path = ROOT / "data" / "Example_1.xlsx"
    new_path = ROOT / "data" / "Example_2.xlsx"
    data_label = "Original brief sample · 783 rows · 6 real changes"
elif uploaded_old and uploaded_new:
    tmp = Path("/tmp"); tmp.mkdir(parents=True, exist_ok=True)
    old_path = tmp / "old.xlsx"
    new_path = tmp / "new.xlsx"
    old_path.write_bytes(uploaded_old.getvalue())
    new_path.write_bytes(uploaded_new.getvalue())
    data_label = f"Uploaded · {uploaded_old.name} vs {uploaded_new.name}"


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

header_col1, header_col2 = st.columns([3, 2])
with header_col1:
    st.markdown(
        """
        <div style="margin-bottom:8px">
          <span style="background:#eef2ff;color:#4f46e5;padding:4px 10px;
                       border-radius:999px;font-size:11px;font-weight:600;
                       text-transform:uppercase;letter-spacing:.06em">
            AI Automation · Take-home Showcase
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("# Rate Sheet Diff Agent")
    st.markdown(
        "<p style='color:#64748b;font-size:15px;line-height:1.6;margin-top:-8px'>"
        "Deterministic Excel rate-sheet diff with <b style='color:#0f172a'>re-dated lane reconciliation</b>, "
        "narrated by Claude into a business-readable email. Pure-Python audit; "
        "the LLM only narrates — it never decides whether numbers changed.</p>",
        unsafe_allow_html=True,
    )

with header_col2:
    with st.container(border=True):
        st.markdown("**How it works**")
        st.markdown(
            "<span style='font-size:13px;color:#475569;line-height:1.6'>"
            "<b>1.</b> Deterministic engine classifies New / Updated / Deleted.<br>"
            "<b>2.</b> Reconciliation pass pairs <i>re-dated lanes</i> "
            "(same Customer + Origin + Destination, different Effective Date).<br>"
            "<b>3.</b> Claude narrates the structured diff into HTML email.<br>"
            "<b>4.</b> Resend delivers it to your inbox."
            "</span>",
            unsafe_allow_html=True,
        )

if not old_path or not new_path:
    st.divider()
    st.info("← Pick a data source in the sidebar to continue.")
    st.stop()


# ---------------------------------------------------------------------------
# Compute diff
# ---------------------------------------------------------------------------

with st.spinner("Loading and diffing..."):
    old = load_rate_sheet(old_path)
    new = load_rate_sheet(new_path)
    diff = diff_rate_sheets(old, new)

raw = diff.counts_raw()
rec = diff.counts_reconciled()

st.divider()
st.caption(f"📂 {data_label}")


# ---------------------------------------------------------------------------
# Top metric ribbon
# ---------------------------------------------------------------------------

m1, m2, m3, m4 = st.columns(4)
m1.metric("Updated", rec["updated"])
m2.metric("Re-dated lanes", rec["redated"])
m3.metric("New", rec["new"], delta=f"raw view: {raw['new']}", delta_color="off")
m4.metric("Deleted", rec["deleted"], delta=f"raw view: {raw['deleted']}", delta_color="off")


# ---------------------------------------------------------------------------
# Tabs: Diff Detail / AI Email / Send
# ---------------------------------------------------------------------------

st.markdown("<br>", unsafe_allow_html=True)
tab_diff, tab_email, tab_send = st.tabs(["📊  Diff Detail", "✉️  AI Email", "📨  Send"])


# --- Tab 1: Diff Detail --------------------------------------------------
with tab_diff:

    if diff.redated:
        with st.container(border=True):
            st.markdown(
                f"<div style='color:#92400e;background:#fffbeb;padding:14px 16px;"
                f"border-radius:8px;margin-bottom:14px;font-size:13.5px;line-height:1.55'>"
                f"<b>🔁 {len(diff.redated)} re-dated lane{'s' if len(diff.redated)>1 else ''} detected.</b> "
                f"A naive row-level diff would report these as <code>New</code> + <code>Deleted</code> rows. "
                f"They are the same logical lane being re-issued on a new Effective Date — "
                f"the reconciliation pass pairs them so the email reflects the real change."
                f"</div>",
                unsafe_allow_html=True,
            )
            st.dataframe(
                pd.DataFrame([
                    {
                        "Customer": p.deleted.customer,
                        "Origin": p.deleted.origin,
                        "Destination": p.deleted.destination,
                        "Old Effective": p.old_effective.isoformat(),
                        "New Effective": p.new_effective.isoformat(),
                        "Rate": p.new.rate,
                    }
                    for p in diff.redated
                ]),
                use_container_width=True, hide_index=True,
            )

    col_a, col_b = st.columns(2)

    with col_a:
        with st.container(border=True):
            st.markdown("##### Updated rows")
            if diff.updated:
                rows = []
                for u in diff.updated:
                    for d in u.deltas:
                        change_dir = ""
                        if d.field == "rate":
                            change_dir = "↓" if d.new < d.old else "↑"
                        rows.append({
                            "Customer": u.new.customer,
                            "Lane": f"{u.new.origin} → {u.new.destination}",
                            "Effective": u.new.effective_date.isoformat(),
                            "Field": d.field.replace("_", " "),
                            "Change": f"{d.old} {change_dir} {d.new}".strip(),
                        })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No updated rows.")

    with col_b:
        with st.container(border=True):
            st.markdown("##### Genuinely new lanes")
            if diff.new_after_reconcile:
                st.dataframe(pd.DataFrame([{
                    "Customer": r.customer,
                    "Lane": f"{r.origin} → {r.destination}",
                    "Effective": r.effective_date.isoformat(),
                    "Rate": r.rate,
                } for r in diff.new_after_reconcile]),
                use_container_width=True, hide_index=True)
            else:
                st.caption("None.")

        with st.container(border=True):
            st.markdown("##### Genuinely deleted lanes")
            if diff.deleted_after_reconcile:
                st.dataframe(pd.DataFrame([{
                    "Customer": r.customer,
                    "Lane": f"{r.origin} → {r.destination}",
                    "Effective": r.effective_date.isoformat(),
                    "Rate": r.rate,
                } for r in diff.deleted_after_reconcile]),
                use_container_width=True, hide_index=True)
            else:
                st.caption("None.")


# --- Tab 2: AI email preview ----------------------------------------------
with tab_email:
    cache_key = f"draft::{old_path.name}::{new_path.name}::{len(diff.updated)}::{len(diff.redated)}"
    if st.session_state.get("draft_key") != cache_key:
        with st.spinner("Asking Claude to narrate the diff…"):
            st.session_state["draft"] = summarize_diff(diff)
            st.session_state["draft_key"] = cache_key

    draft = st.session_state["draft"]

    pill_color = "#059669" if draft.source == "claude" else "#64748b"
    pill_bg = "#ecfdf5" if draft.source == "claude" else "#f1f5f9"
    pill_text = "✓ Narrated by Claude (Sonnet 4)" if draft.source == "claude" else f"Deterministic renderer · {draft.source}"

    st.markdown(
        f"<span style='background:{pill_bg};color:{pill_color};padding:5px 12px;"
        f"border-radius:999px;font-size:11px;font-weight:600'>{pill_text}</span>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.caption("SUBJECT")
        st.markdown(f"#### {draft.subject}")

    st.markdown("**Body preview**")
    st.components.v1.html(
        f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:24px;"
        f"background:white;font-family:Inter,sans-serif'>{draft.html}</div>",
        height=620, scrolling=True,
    )


# --- Tab 3: Send ----------------------------------------------------------
with tab_send:
    if "sends_this_session" not in st.session_state:
        st.session_state["sends_this_session"] = 0
    MAX_SENDS = 3

    draft = st.session_state.get("draft")
    if not draft:
        st.info("Open the **AI Email** tab first to generate the draft.")
        st.stop()

    with st.container(border=True):
        st.markdown("##### Email this summary to yourself")
        st.caption(
            "We send via Resend's shared demo sender. Recipient is locked "
            "to whatever you type below — no third-party relay. Up to "
            f"{MAX_SENDS} sends per session."
        )

        recipient = st.text_input(
            "Your email address",
            placeholder="you@yourcompany.com",
        )

        c1, c2 = st.columns([1, 2])
        with c1:
            disabled = not bool(os.environ.get("RESEND_API_KEY"))
            clicked = st.button(
                "Send to me",
                type="primary",
                disabled=disabled,
                use_container_width=True,
            )
        with c2:
            if disabled:
                st.markdown(
                    "<span style='background:#f1f5f9;color:#64748b;padding:5px 12px;"
                    "border-radius:999px;font-size:11px;font-weight:500'>"
                    "Sending disabled — server has no Resend key</span>",
                    unsafe_allow_html=True,
                )
            else:
                remaining = MAX_SENDS - st.session_state["sends_this_session"]
                st.markdown(
                    f"<span style='background:#eef2ff;color:#4f46e5;padding:5px 12px;"
                    f"border-radius:999px;font-size:11px;font-weight:500'>"
                    f"{remaining} send{'s' if remaining != 1 else ''} remaining this session</span>",
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
                st.success(f"✓ {result.detail}")
                if result.message_id:
                    st.caption(f"Message ID: `{result.message_id}`")
                st.caption(
                    "Sender appears as `onboarding@resend.dev` — Resend's "
                    "shared demo sender. Check spam if you don't see it."
                )
            else:
                st.error(result.detail)
