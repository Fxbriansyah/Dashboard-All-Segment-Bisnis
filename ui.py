"""Komponen UI kecil yang dipakai di banyak halaman."""
import math

import streamlit as st

from config import BRAND, CSS_PATH, STEPS


# CSS tambahan (dimuat setelah assets/style.css, jadi menimpa gaya yang sama).
# Hapus blok ini kalau ingin kembali ke tampilan lama.
EXTRA_CSS = """
/* Sembunyikan bilah atas Streamlit (Deploy, menu titik tiga, garis warna, status "Running").
   Header dibiarkan transparan (logo tetap tampil) dan tidak menangkap klik, supaya tombol di bawahnya bisa diklik. */
[data-testid="stToolbar"],[data-testid="stAppDeployButton"],[data-testid="stMainMenu"],
[data-testid="stDecoration"],[data-testid="stStatusWidget"],#MainMenu,footer{display:none !important}
[data-testid="stHeader"]{background:transparent !important;pointer-events:none !important}
[data-testid="stMainBlockContainer"]{padding-top:4.5rem !important}
/* Sidebar dihilangkan; filter ada di bar atas halaman */
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"]{display:none !important}

/* NPL: badge berwarna (hijau < NPL_WARN, kuning < NPL_BAD, merah di atasnya) */
.npl{display:inline-block;padding:2px 9px;border-radius:999px;font-weight:700;font-size:.82em;line-height:1.5;white-space:nowrap}
.npl-ok{background:#dcfce7;color:#166534}
.npl-warn{background:#fef3c7;color:#92400e}
.npl-bad{background:#fee2e2;color:#b91c1c}
.npl-na{background:#f1f5f9;color:#64748b}

/* KPI: angka lebih besar + catatan kecil; kartu NPL diberi garis warna di kiri */
.kpi b{font-size:1.5rem !important;line-height:1.25 !important}
.kpi>span{color:#475569 !important;font-size:12px !important;font-weight:600 !important}
.kpi-note{display:block;margin-top:3px;font-size:11px;color:#64748b;font-weight:500}
.kpi.kpi-ok{border-left:4px solid #22c55e !important}
.kpi.kpi-warn{border-left:4px solid #f59e0b !important}
.kpi.kpi-bad{border-left:4px solid #ef4444 !important}
.kpi .npl{font-size:.75em;padding:3px 12px}

/* Kartu segmen: label lebih kontras */
.seg-stats>div>span,.prod-meta>span{color:#475569 !important}
.seg-stats .npl{font-size:.9em}

/* Daftar produk: tinggi tetap (diatur PROD_LIST_H di views.py) + scroll, jadi semua kartu segmen sejajar */
.prod-list{flex:none !important;scrollbar-width:thin;scrollbar-color:#cbd5e1 transparent}
.prod-list::-webkit-scrollbar{width:6px}
.prod-list::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:6px}
.prod-list .prod{flex:none !important}
.prod-meta{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:4px;font-size:12px}
.prod-meta b{font-weight:700;color:#0f172a}
"""


def inject_css():
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}{EXTRA_CSS}</style>", unsafe_allow_html=True)


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
    """Baris metrik ringkas. items: [(label, nilai[, catatan[, tooltip[, kelas_css]]]), ...]; nilai boleh HTML."""
    cells = []
    for label, value, *rest in items:
        note, title, cls = (list(rest) + ["", "", ""])[:3]
        cells.append(
            f'<div class="kpi {cls}"' + (f' title="{title}"' if title else "") + '>'
            f'<span>{label}</span><b>{value}</b>' + (f'<small class="kpi-note">{note}</small>' if note else "")
            + '</div>')
    st.markdown(f'<div class="kpis">{"".join(cells)}</div>', unsafe_allow_html=True)


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