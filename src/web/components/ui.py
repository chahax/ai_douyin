"""Shared visual language for the Streamlit admin workspace.

The theme borrows the information hierarchy of modern AI creation studios:
graphite canvas, grouped tool rail, compact page headers, rounded work surfaces, and
one obvious primary action per surface.  Business pages should use these
helpers instead of creating page-specific CSS.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable, Mapping

import streamlit as st


THEME_PATH = Path(__file__).with_name("studio.css")


def inject_app_theme() -> None:
    """Install the shared visual system once per Streamlit rerun."""

    st.markdown("<style>" + THEME_PATH.read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


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
