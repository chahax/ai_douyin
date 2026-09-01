"""Shared visual language for the Streamlit admin workspace.

The theme borrows the information hierarchy of modern AI creation studios:
quiet canvas, dark tool rail, compact page headers, rounded work surfaces, and
one obvious primary action per surface.  Business pages should use these
helpers instead of creating page-specific CSS.
"""

from __future__ import annotations

from html import escape
from typing import Iterable, Mapping

import streamlit as st


APP_THEME_CSS = """
<style>
:root {
    --studio-bg: #f6f6fa;
    --studio-surface: #ffffff;
    --studio-surface-soft: #f9f9fc;
    --studio-sidebar: #16171f;
    --studio-sidebar-2: #1d1e28;
    --studio-text: #181921;
    --studio-muted: #777986;
    --studio-line: #e9e9f0;
    --studio-accent: #655cf6;
    --studio-accent-2: #8b5cf6;
    --studio-success: #17a673;
    --studio-warning: #d98a18;
    --studio-danger: #dd4b5f;
    --studio-shadow: 0 8px 28px rgba(25, 26, 40, 0.055);
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: var(--studio-bg);
    color: var(--studio-text);
}

.block-container {
    max-width: 1380px !important;
    padding: 2rem 2.5rem 4.5rem !important;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--studio-sidebar) 0%, #12131a 100%);
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}

[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: 0.75rem;
}

[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: rgba(255, 255, 255, 0.82) !important;
}

[data-testid="stSidebarNav"] a {
    min-height: 2.5rem;
    margin: 0.14rem 0.55rem;
    padding: 0.52rem 0.7rem;
    border-radius: 0.72rem;
    color: rgba(255, 255, 255, 0.68) !important;
    transition: background 150ms ease, color 150ms ease, transform 150ms ease;
}

[data-testid="stSidebarNav"] a:hover {
    background: rgba(255, 255, 255, 0.075);
    color: #ffffff !important;
    transform: translateX(2px);
}

[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: linear-gradient(135deg, rgba(101, 92, 246, 0.92), rgba(139, 92, 246, 0.82));
    color: #ffffff !important;
    box-shadow: 0 8px 22px rgba(101, 92, 246, 0.22);
}

[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stLinkButton > a {
    background: rgba(255, 255, 255, 0.055);
    border-color: rgba(255, 255, 255, 0.11);
    color: rgba(255, 255, 255, 0.88);
}

h1, h2, h3 {
    color: var(--studio-text);
    letter-spacing: -0.025em;
}

h2 {
    margin-top: 1.7rem !important;
    font-size: 1.22rem !important;
}

h3 {
    font-size: 1.02rem !important;
}

hr {
    margin: 1.65rem 0 !important;
    border-color: var(--studio-line) !important;
}

.studio-page-header {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    padding: 0.2rem 0 1.55rem;
}

.studio-page-icon {
    width: 3rem;
    height: 3rem;
    flex: 0 0 3rem;
    display: grid;
    place-items: center;
    border-radius: 1rem;
    font-size: 1.35rem;
    background: linear-gradient(145deg, #7168ff 0%, #a15cf4 100%);
    color: #ffffff;
    box-shadow: 0 10px 26px rgba(101, 92, 246, 0.22);
}

.studio-page-copy {
    min-width: 0;
    padding-top: 0.05rem;
}

.studio-eyebrow {
    margin-bottom: 0.34rem;
    color: var(--studio-accent);
    font-size: 0.69rem;
    font-weight: 750;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.studio-page-title {
    margin: 0;
    font-size: 1.85rem;
    line-height: 1.2;
    font-weight: 750;
    letter-spacing: -0.035em;
}

.studio-page-description {
    max-width: 760px;
    margin: 0.52rem 0 0;
    color: var(--studio-muted);
    font-size: 0.9rem;
    line-height: 1.65;
}

.studio-section-header {
    margin: 1.4rem 0 0.72rem;
}

.studio-section-title {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 720;
}

.studio-section-description {
    margin: 0.28rem 0 0;
    color: var(--studio-muted);
    font-size: 0.82rem;
}

div[data-testid="stMetric"] {
    min-height: 7.1rem;
    padding: 1rem 1.08rem;
    background: var(--studio-surface);
    border: 1px solid var(--studio-line);
    border-radius: 1rem;
    box-shadow: var(--studio-shadow);
}

div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
    color: var(--studio-muted);
    font-size: 0.78rem;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: var(--studio-text);
    font-size: 1.42rem;
    font-weight: 720;
}

[data-testid="stForm"],
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--studio-surface);
    border-color: var(--studio-line) !important;
    border-radius: 1.05rem !important;
    box-shadow: var(--studio-shadow);
}

[data-testid="stForm"] {
    padding: 1.15rem 1.2rem 1.25rem;
}

[data-testid="stExpander"] {
    overflow: hidden;
    background: var(--studio-surface);
    border: 1px solid var(--studio-line) !important;
    border-radius: 0.95rem !important;
    box-shadow: 0 5px 18px rgba(25, 26, 40, 0.035);
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
    overflow: hidden;
    background: var(--studio-surface);
    border: 1px solid var(--studio-line);
    border-radius: 1rem;
    box-shadow: var(--studio-shadow);
}

[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div,
.stTextInput input,
.stNumberInput input,
.stTextArea textarea {
    border-color: var(--studio-line) !important;
    border-radius: 0.78rem !important;
    background: #fbfbfd !important;
}

[data-baseweb="select"] > div:focus-within,
[data-baseweb="input"] > div:focus-within,
[data-baseweb="textarea"] > div:focus-within {
    border-color: rgba(101, 92, 246, 0.62) !important;
    box-shadow: 0 0 0 3px rgba(101, 92, 246, 0.09) !important;
}

.stButton > button,
.stLinkButton > a,
[data-testid="stFormSubmitButton"] > button {
    min-height: 2.55rem;
    border-radius: 0.78rem;
    border-color: var(--studio-line);
    font-weight: 650;
    transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease;
}

.stButton > button:hover,
.stLinkButton > a:hover,
[data-testid="stFormSubmitButton"] > button:hover {
    transform: translateY(-1px);
    border-color: rgba(101, 92, 246, 0.42);
    box-shadow: 0 7px 18px rgba(25, 26, 40, 0.08);
}

.stButton > button[kind="primary"],
[data-testid="stFormSubmitButton"] > button[kind="primary"] {
    color: #ffffff;
    border: 0;
    background: linear-gradient(135deg, var(--studio-accent), var(--studio-accent-2));
    box-shadow: 0 8px 20px rgba(101, 92, 246, 0.22);
}

[data-testid="stAlert"] {
    border-radius: 0.9rem;
    border-width: 1px;
}

.studio-workflow-overview {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
    margin: 0.4rem 0 1.2rem;
}

.studio-phase-card {
    position: relative;
    overflow: hidden;
    min-height: 10rem;
    padding: 1rem;
    border-radius: 1rem;
    border: 1px solid var(--studio-line);
    background: linear-gradient(145deg, #ffffff 0%, #faf9ff 100%);
    box-shadow: var(--studio-shadow);
}

.studio-phase-card::after {
    content: "";
    position: absolute;
    width: 5rem;
    height: 5rem;
    right: -2.4rem;
    top: -2.4rem;
    border-radius: 50%;
    background: rgba(101, 92, 246, 0.08);
}

.studio-phase-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.55rem;
    height: 1.55rem;
    margin-right: 0.45rem;
    border-radius: 0.5rem;
    color: #ffffff;
    background: var(--studio-accent);
    font-size: 0.68rem;
    font-weight: 750;
}

.studio-phase-title {
    font-size: 0.92rem;
    font-weight: 720;
}

.studio-phase-list {
    display: grid;
    gap: 0.52rem;
    margin-top: 0.8rem;
}

.studio-phase-row {
    display: flex;
    justify-content: space-between;
    gap: 0.7rem;
    font-size: 0.76rem;
}

.studio-phase-row span:first-child {
    color: var(--studio-muted);
}

.studio-phase-row strong {
    overflow: hidden;
    color: var(--studio-text);
    text-overflow: ellipsis;
    white-space: nowrap;
}

.studio-node-card-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-bottom: 0.25rem;
}

.studio-node-card-title strong {
    font-size: 0.92rem;
}

.studio-pill {
    display: inline-flex;
    align-items: center;
    min-height: 1.45rem;
    padding: 0.1rem 0.52rem;
    border-radius: 999px;
    font-size: 0.66rem;
    font-weight: 700;
    white-space: nowrap;
}

.studio-pill--hot {
    color: #127456;
    background: #e8f8f2;
}

.studio-pill--profile {
    color: #6550b6;
    background: #f0ecff;
}

.studio-pill--external {
    color: #8b6118;
    background: #fff5dc;
}

.studio-pill--active {
    color: #ffffff;
    background: linear-gradient(135deg, var(--studio-accent), var(--studio-accent-2));
}

div[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.35rem;
    padding: 0.26rem;
    border-radius: 0.85rem;
    background: #ececf3;
}

div[data-testid="stTabs"] [data-baseweb="tab"] {
    min-height: 2.35rem;
    padding: 0.4rem 0.9rem;
    border-radius: 0.65rem;
}

div[data-testid="stTabs"] [aria-selected="true"] {
    background: #ffffff;
    box-shadow: 0 3px 10px rgba(25, 26, 40, 0.08);
}

@media (max-width: 900px) {
    .block-container {
        padding: 1.35rem 1rem 3rem !important;
    }
    .studio-workflow-overview {
        grid-template-columns: 1fr;
    }
    .studio-page-title {
        font-size: 1.55rem;
    }
}
</style>
"""


def inject_app_theme() -> None:
    """Install the shared visual system once per Streamlit rerun."""

    st.markdown(APP_THEME_CSS, unsafe_allow_html=True)


def page_header(
    title: str,
    description: str,
    *,
    icon: str = "✦",
    eyebrow: str = "AI DOUYIN STUDIO",
) -> None:
    st.markdown(
        f"""
        <div class="studio-page-header">
          <div class="studio-page-icon">{escape(icon)}</div>
          <div class="studio-page-copy">
            <div class="studio-eyebrow">{escape(eyebrow)}</div>
            <h1 class="studio-page-title">{escape(title)}</h1>
            <p class="studio-page-description">{escape(description)}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, description: str = "") -> None:
    description_html = (
        f'<p class="studio-section-description">{escape(description)}</p>'
        if description
        else ""
    )
    st.markdown(
        f"""
        <div class="studio-section-header">
          <h2 class="studio-section-title">{escape(title)}</h2>
          {description_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def node_card_header(title: str, status: str, tone: str) -> None:
    st.markdown(
        f"""
        <div class="studio-node-card-title">
          <strong>{escape(title)}</strong>
          <span class="studio-pill studio-pill--{escape(tone)}">{escape(status)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def workflow_overview(
    phases: Iterable[tuple[str, Iterable[str]]],
    selections: Mapping[str, str],
    labels: Mapping[str, str],
    implementation_labels: Mapping[tuple[str, str], str],
) -> None:
    cards: list[str] = []
    for index, (phase_name, stages) in enumerate(phases, start=1):
        rows = []
        for stage in stages:
            implementation_id = selections[stage]
            rows.append(
                '<div class="studio-phase-row">'
                f"<span>{escape(labels.get(stage, stage))}</span>"
                f"<strong>{escape(implementation_labels[(stage, implementation_id)])}</strong>"
                "</div>"
            )
        cards.append(
            '<div class="studio-phase-card">'
            f'<div><span class="studio-phase-index">0{index}</span>'
            f'<span class="studio-phase-title">{escape(phase_name)}</span></div>'
            f'<div class="studio-phase-list">{"".join(rows)}</div>'
            "</div>"
        )
    st.markdown(
        f'<div class="studio-workflow-overview">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
