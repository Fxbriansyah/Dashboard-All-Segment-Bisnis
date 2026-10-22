"""Komponen UI kecil yang dipakai di banyak halaman."""
import streamlit as st

import math

import streamlit as st

from config import BRAND, CSS_PATH, STEPS


def inject_css():
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def page_header(title, desc=""):
    st.markdown(f'<div class="page-title">{title}</div>'
                + (f'<div class="page-desc">{desc}</div>' if desc else ""), unsafe_allow_html=True)


def stepper(current):
    """Penunjuk langkah. current: indeks 0..len(STEPS)-1."""
    items = "".join(
        f'<div class="step {"done" if i < current else "active" if i == current else ""}">'
        f'<i>{"✓" if i < current else i + 1}</i>{label}</div>'
        for i, label in enumerate(STEPS))
    st.markdown(f'<div class="stepper">{items}</div>', unsafe_allow_html=True)


def kpis(items):
    """Baris metrik ringkas. items: [(label, nilai), ...]"""
    html = "".join(f'<div class="kpi"><span>{k}</span><b>{v}</b></div>' for k, v in items)
    st.markdown(f'<div class="kpis">{html}</div>', unsafe_allow_html=True)


def style_fig(fig, height=340, legend_bottom=False):
    """Gaya chart seragam: transparan, font sama, tanpa judul sumbu, format angka Indonesia."""
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=8, b=8), font=dict(size=11, family="Plus Jakarta Sans"),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", autosize=True,
                      separators=",.")   # desimal koma, ribuan titik
    fig.update_xaxes(automargin=True, title_text="", showgrid=False)
    fig.update_yaxes(automargin=True, title_text="", gridcolor="#eef1f6")
    if legend_bottom:
        fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.05, xanchor="center", x=0.5,
                                      font=dict(size=10), title_text=""))
    return fig


def short_rp(x):
    """Singkatan sumbu: 4500000000000 -> '4,5 T', 650000000000 -> '650 M' (M = miliar)."""
    for div, unit in ((1e12, "T"), (1e9, "M"), (1e6, "Jt")):
        if abs(x) >= div:
            return f"{x / div:g} {unit}".replace(".", ",")
    return f"{x:g}".replace(".", ",")


def compact_rp(x):
    """Label ringkas satu desimal: 92729400677204 -> '92,7 T', 647267072927 -> '647,3 M'."""
    for div, unit in ((1e12, "T"), (1e9, "M"), (1e6, "Jt")):
        if abs(x) >= div:
            return f"{x / div:,.1f} {unit}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{x:,.0f}".replace(",", ".")


def rupiah_axis(fig, max_value, n=4):
    """Sumbu Y dengan angka 'bulat' dan satuan Indonesia (Jt / M / T)."""
    if not max_value or max_value <= 0:
        return fig
    raw = max_value / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    vals = [i * step for i in range(n + 2) if i * step <= max_value + step]
    fig.update_yaxes(tickvals=vals, ticktext=[short_rp(v) for v in vals])
    return fig


def show_fig(fig):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "responsive": True})


LINE_STYLE = dict(line_color=BRAND, line_width=3, marker=dict(size=6, color=BRAND))