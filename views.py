"""Halaman-halaman dashboard: Upload -> Proses -> Ringkasan -> Dashboard."""
import hashlib
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import hashlib
import html

import data as D
import ui

from config import (BRAND, BRAND_LIGHT, BUNGA_COLUMN, DB_CONFIG, DEFAULT_THEME, PRODUCT_COLORS,
                    REQUIRED_COLUMNS, SAFE_DETAIL_COLUMNS, SEGMENT_ORDER, SEGMENT_THEME)

SESSION_KEYS = ["stage", "data", "file_hash", "file_name", "processed_at"]
FILTER_KEYS = ["f_year", "f_month", "f_status"]
CHART_BOX = 400   # tinggi kotak chart di baris tiga chart (px)


def go_to(stage):
    st.session_state.stage = stage
    st.rerun()


def reset_all():
    st.cache_data.clear()   # buang cache supaya data selalu segar
    for k in SESSION_KEYS + FILTER_KEYS:
        st.session_state.pop(k, None)
    go_to("upload")


def _store(df, name, digest=None):
    st.session_state.update(data=df, file_name=name, file_hash=digest, processed_at=datetime.now())


# ======================= 1. UPLOAD =======================
def page_upload():
    ui.stepper(0)
    ui.page_header("Upload data", "Unggah file Excel, atau ambil langsung dari database untuk membangun dashboard.")
    sumber = st.radio("Sumber data", ["📤 Upload file Excel", "🗄️ Ambil dari database"],
                      horizontal=True, label_visibility="collapsed")
    if sumber.startswith("📤"):
        _upload_excel()
    else:
        _upload_db()


def _upload_excel():
    with st.container(border=True):
        uploaded = st.file_uploader("Pilih file Excel (.xlsx / .xls / .xlsm)", type=["xlsx", "xls", "xlsm"],
                                    help="Data hanya diproses untuk sesi ini dan tidak disimpan di source code.")
        st.markdown("**Kolom wajib di file:**")
        st.code(", ".join(REQUIRED_COLUMNS), language=None)
    if uploaded is None:
        return
    raw = uploaded.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    if digest == st.session_state.get("file_hash"):   # file yang sama: tidak perlu diproses ulang
        go_to("summary")
    st.session_state.update(_pending=(raw, digest, uploaded.name))
    go_to("processing")


def _upload_db():
    with st.container(border=True):
        st.markdown(f'<div class="hint">Ambil data dari PostgreSQL tanpa upload file.<br>'
                    f'Target: <b>{DB_CONFIG["host"]}:{DB_CONFIG["port"]}/{DB_CONFIG["dbname"]}</b></div>',
                    unsafe_allow_html=True)
        ok, err = D.check_db()
        if not ok:
            st.error("Tidak bisa terhubung ke database. Periksa DB_HOST, DB_PORT, DB_NAME, DB_USER, "
                     "DB_PASSWORD di file `.env`, lalu pastikan server database bisa diakses.")
            st.code(err, language=None)
            if st.button("Coba lagi"):
                D.check_db.clear()
                st.rerun()
            return
        try:
            batches = D.get_upload_batches()
        except Exception as e:  # noqa: BLE001
            batches = pd.DataFrame(columns=["id", "file_name", "total_rows"])
            st.warning(f"Daftar batch upload tidak bisa dibaca: {e}")

        options = {"Semua data": None} | {
            f"#{r.id} - {r.file_name} ({D.fmt_num(r.total_rows)} baris)": r.id for r in batches.itertuples()}
        pilihan = st.selectbox("Pilih data", list(options))
        if st.button("Ambil data", type="primary", width="stretch"):
            with st.spinner("Mengambil & memproses data..."):
                try:
                    df = D.load_from_db(options[pilihan])
                except Exception as e:  # noqa: BLE001
                    st.error(f"Gagal mengambil data: {e}")
                    return
            if df.empty:
                st.warning("Tidak ada data di database untuk pilihan ini.")
                return
            _store(df, f"Database - {pilihan}")
            go_to("summary")


# ======================= 2. PROSES =======================
def page_processing():
    ui.stepper(1)
    ui.page_header("Memproses data")
    pending = st.session_state.get("_pending")
    if not pending:
        go_to("upload")
    raw_bytes, digest, name = pending

    problem = None
    with st.status("Memproses file...", expanded=True) as status:
        try:
            st.write("Membaca file Excel")
            raw = D.read_excel_bytes(raw_bytes)
            st.write("Memeriksa kolom wajib")
            missing = D.validate_columns(raw)
            if missing:
                problem = "Kolom wajib belum ada:\n" + "\n".join(missing)
            else:
                st.write("Membersihkan & mengonversi tipe data")
                df = D.prepare_data(raw)
        except Exception as e:  # noqa: BLE001
            problem = f"File tidak bisa dibaca: {e}"
        status.update(label="Gagal memproses file" if problem else "Selesai", state="error" if problem else "complete")

    if problem:
        st.error("File tidak sesuai template. Perbaiki file lalu upload lagi.")
        st.code(problem, language=None)
        if st.button("Kembali ke upload"):
            st.session_state.pop("_pending", None)
            go_to("upload")
        return
    st.session_state.pop("_pending", None)
    _store(df, name, digest)
    go_to("summary")


# ======================= 3. RINGKASAN =======================
def page_summary():
    ui.stepper(2)
    df = st.session_state.get("data")
    if df is None:
        go_to("upload")
    ui.page_header("Ringkasan data")
    st.markdown('<div class="banner">Data berhasil diproses dan siap ditampilkan.</div>', unsafe_allow_html=True)

    tahun = df["TAHUN PENCAIRAN"].dropna()
    periode = f"{D.fmt_tahun(tahun.min())} - {D.fmt_tahun(tahun.max())}" if not tahun.empty else "-"
    ui.kpis([("Total records", D.fmt_num(len(df))), ("Total kolom", D.fmt_num(df.shape[1])),
             ("Segmen bisnis", D.fmt_num(df["PRODUCT_OWNER"].nunique())), ("Periode pencairan", periode)])

    b1, b2 = st.columns(2)
    if b1.button("Tampilkan dashboard", type="primary", width="stretch"):
        go_to("dashboard")
    if b2.button("Upload ulang", width="stretch"):
        reset_all()
    st.caption(f"Sumber: {st.session_state.get('file_name', '-')}")


# ======================= 4. DASHBOARD =======================
def _product_list_html(s, color):
    """Daftar per group produk: NoA, plafond, dan pendapatan bunga (diurutkan dari plafond terbesar)."""
    agg = {"noa": ("PLAFOND", "size"), "plafond": ("PLAFOND", "sum")}
    if BUNGA_COLUMN in s.columns:
        agg["bunga"] = (BUNGA_COLUMN, "sum")
    g = s.groupby("GROUP_PRODUCT").agg(**agg).sort_values("plafond", ascending=False)
    rows = "".join(
        f'<div class="prod"><div class="prod-top"><b>{html.escape(str(name))}</b>'
        f'<span>NoA {D.fmt_num(r["noa"])}</span></div>'
        f'<div class="prod-row"><span>Plafond</span><b>{D.fmt_money(r["plafond"])}</b></div>'
        f'<div class="prod-row"><span>Pend_Bunga</span>'
        f'<b>{D.fmt_money(r["bunga"]) if "bunga" in g.columns else "-"}</b></div></div>'
        for name, r in g.iterrows())
    return (f'<div class="seg-sub" style="--seg-color:{color}">Rincian per produk ({len(g)})</div>'
            f'<div class="prod-list">{rows}</div>')

def _legend_html(cmap, tall=False):
    """Legenda nama produk: 2 kolom, tinggi tetap (2 baris; tall=4 baris), sisanya bisa di-scroll."""
    items = "".join(f'<span title="{html.escape(n)}"><i style="background:{c}"></i>{html.escape(n)}</span>'
                    for n, c in cmap.items())
    return f'<div class="legend{" tall" if tall else ""}">{items}</div>'

def segment_card(df, segment):
    th = SEGMENT_THEME.get(segment, DEFAULT_THEME)
    s = df[df["PRODUCT_OWNER"] == segment]
    plafond = s["PLAFOND"].sum()
    bunga = D.fmt_money(s[BUNGA_COLUMN].sum()) if BUNGA_COLUMN in s.columns else "-"
    with st.container(border=True):
        st.markdown(
            f'<div class="seg-head" style="--seg-bg:{th["bg"]};--seg-border:{th["border"]};--seg-color:{th["color"]}">'
            f'<span>{th["icon"]}</span>{segment}</div>'
            f'<div class="seg-stats">'
            f'<div><span>NoA</span><b>{D.fmt_num(len(s))}</b></div>'
            f'<div><span>Produk</span><b>{D.fmt_num(s["GROUP_PRODUCT"].nunique())}</b></div>'
            f'<div class="wide"><span>Plafond</span><b>{D.fmt_money(plafond)}</b></div>'
            f'<div class="wide"><span>Total pendapatan bunga</span><b>{bunga}</b></div></div>'
            + _product_list_html(s, th["color"])
            + f'<div class="seg-sub" style="--seg-color:{th["color"]}">Komposisi group produk</div>',
            unsafe_allow_html=True)
        produk = s.groupby("GROUP_PRODUCT").size().rename("Jumlah").reset_index().sort_values("Jumlah", ascending=False)
        if not produk.empty:
            cmap = {n: PRODUCT_COLORS[i % len(PRODUCT_COLORS)] for i, n in enumerate(produk["GROUP_PRODUCT"])}
            fig = px.pie(produk, names="GROUP_PRODUCT", values="Jumlah", hole=0.6,
                         color="GROUP_PRODUCT", color_discrete_map=cmap)
            fig.update_traces(textinfo="none")
            fig.update_layout(showlegend=False)
            ui.show_fig(ui.style_fig(fig, height=210))
            st.markdown(_legend_html(cmap), unsafe_allow_html=True)


def _reset_filters():
    for k in FILTER_KEYS:
        st.session_state[k] = []


def _sidebar(df0):
    with st.sidebar:
        st.markdown('<div class="side-title">Filter data</div>'
                    '<div class="side-desc">Berlaku untuk seluruh dashboard.</div>', unsafe_allow_html=True)
        st.multiselect("Tahun pencairan", sorted(df0["TAHUN PENCAIRAN"].dropna().unique()), key="f_year",
                       format_func=D.fmt_tahun, placeholder="Semua")
        st.multiselect("Bulan pencairan", sorted(df0["BULAN_PENCAIRAN"].dropna().unique()), key="f_month",
                       format_func=D.fmt_bulan, placeholder="Semua")
        st.multiselect("Status loan", sorted(df0["STATUS_LOAN"].unique()), key="f_status",
                       format_func=D.fmt_status, placeholder="Semua")

        aktif = sum(bool(st.session_state.get(k)) for k in FILTER_KEYS)
        info = f"dari {D.fmt_num(len(df0))} record" + (f" · {aktif} filter aktif" if aktif else "")
        st.markdown(f'<div class="side-result"><span>Data ditampilkan</span>'
                    f'<b>{D.fmt_num(len(_apply_filters(df0)))}</b><small>{info}</small></div>', unsafe_allow_html=True)
        st.button("Reset filter", on_click=_reset_filters, width="stretch", disabled=not aktif)

        st.divider()
        st.caption(f"Sumber: {st.session_state.get('file_name', '-')}")
        if st.button("Upload ulang", width="stretch"):
            reset_all()
        st.caption("Kolom identitas sensitif tidak ditampilkan di tabel.")

def _apply_filters(df0):
    df, ss = df0, st.session_state
    for key, col in (("f_year", "TAHUN PENCAIRAN"), ("f_month", "BULAN_PENCAIRAN"), ("f_status", "STATUS_LOAN")):
        if ss.get(key):
            df = df[df[col].isin(ss[key])]
    return df


def page_dashboard():
    df0 = st.session_state.get("data")
    if df0 is None:
        go_to("upload")
    _sidebar(df0)
    if BUNGA_COLUMN not in df0.columns:
        st.warning(f"Kolom {BUNGA_COLUMN} tidak ada di data. Untuk database: pastikan kolomnya ada di tabel "
                   "dan terdaftar di DB_COLUMN_TO_APP (config.py), lalu muat ulang data lewat load_to_postgres.py.")
    df = _apply_filters(df0)

    ts = st.session_state.get("processed_at")
    left, right = st.columns([3, 1])
    left.markdown('<div class="title-card"><div class="page-title">Dashboard Pencairan</div>'
                  '<div class="page-desc">Semua segmen bisnis</div></div>', unsafe_allow_html=True)
    right.markdown(f'<div class="chip">Data diproses<b>{ts.strftime("%d %b %Y %H:%M") if ts else "-"}</b></div>',
                   unsafe_allow_html=True)
    st.write("")
    if df.empty:
        st.info("Tidak ada data untuk filter ini. Ubah atau reset filter di sidebar.")
        return

    plafond, outstanding = df["PLAFOND"].sum(), df["OUTSTANDING"].sum()
    ui.kpis([("Total NoA", D.fmt_num(len(df))), ("Total plafond", D.fmt_money(plafond)),
             ("Total outstanding", D.fmt_money(outstanding)),
             ("Outstanding / plafond", D.fmt_pct(outstanding / plafond * 100 if plafond else 0))])

    # Kartu per segmen (maks. 4 per baris; kolom otomatis turun baris di layar sempit)
    segs = [s for s in SEGMENT_ORDER if s in set(df["PRODUCT_OWNER"])]
    segs += [s for s in df["PRODUCT_OWNER"].unique() if s not in segs]
    with st.container(key="segments"):
        for i in range(0, len(segs), 4):
            row = segs[i:i + 4]
            for col, seg in zip(st.columns(len(row)), row):
                with col:
                    segment_card(df, seg)

    st.divider()
    
    with st.container(key="charts"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("Pencairan 5 tahun terakhir per segmen (plafond)")
            with st.container(border=True, height=CHART_BOX):
                d = df.dropna(subset=["TAHUN PENCAIRAN"])
                last = sorted(d["TAHUN PENCAIRAN"].unique())[-5:]   # 5 tahun terakhir
                d = d[d["TAHUN PENCAIRAN"].isin(last)]
                ys = d.groupby(["TAHUN PENCAIRAN", "PRODUCT_OWNER"], as_index=False)["PLAFOND"].sum()
                ys["TAHUN"] = ys["TAHUN PENCAIRAN"].astype(int).astype(str)
                segs_here = [s for s in SEGMENT_ORDER if s in set(ys["PRODUCT_OWNER"])]
                segs_here += [s for s in ys["PRODUCT_OWNER"].unique() if s not in segs_here]
                fig = px.bar(ys, x="TAHUN", y="PLAFOND", color="PRODUCT_OWNER",
                             category_orders={"PRODUCT_OWNER": segs_here,
                                              "TAHUN": [str(int(y)) for y in last]},
                             color_discrete_map={s: SEGMENT_THEME.get(s, DEFAULT_THEME)["color"] for s in segs_here})
                fig.update_traces(hovertemplate="%{x} - %{fullData.name}<br>Rp %{y:,.0f}<extra></extra>")
                fig.update_layout(bargap=0.3, barmode="stack")
                fig.update_xaxes(type="category")
                ui.rupiah_axis(fig, ys.groupby("TAHUN")["PLAFOND"].sum().max())
                ui.show_fig(ui.style_fig(fig, CHART_BOX - 48, legend_bottom=True))
        with c2:
            st.subheader("Outstanding per segmen")
            with st.container(border=True, height=CHART_BOX):
                comp = df.groupby("PRODUCT_OWNER")["OUTSTANDING"].sum().sort_values(ascending=False)
                top = comp.max() or 1
                rows = "".join(
                    f'<div><div class="hbar-top"><span>{html.escape(str(n))}</span><b>{D.fmt_money(val)}</b></div>'
                    f'<div class="hbar-track"><div style="width:{max(val / top * 100, 1.5):.1f}%;'
                    f'background:{SEGMENT_THEME.get(n, DEFAULT_THEME)["color"]}"></div></div></div>'
                    for n, val in comp.items())
                st.markdown(f'<div class="hbars">{rows}</div>', unsafe_allow_html=True)
        with c3:
            st.subheader("Outstanding per group produk")
            with st.container(border=True, height=CHART_BOX):
                po = (df.groupby("GROUP_PRODUCT", as_index=False)["OUTSTANDING"].sum()
                      .sort_values("OUTSTANDING", ascending=False))
                cmap = {n: PRODUCT_COLORS[i % len(PRODUCT_COLORS)] for i, n in enumerate(po["GROUP_PRODUCT"])}
                fig = px.pie(po, names="GROUP_PRODUCT", values="OUTSTANDING", hole=0.6,
                             color="GROUP_PRODUCT", color_discrete_map=cmap)
                fig.update_traces(textinfo="none")
                fig.update_layout(showlegend=False)
                fig = ui.style_fig(fig, CHART_BOX - 190)
                fig.update_layout(margin=dict(l=10, r=10, t=12, b=12))
                ui.show_fig(fig)
                st.markdown(_legend_html(cmap, tall=True), unsafe_allow_html=True)

    st.subheader("Plafond vs outstanding per segmen")
    pv = (df.groupby("PRODUCT_OWNER")[["PLAFOND", "OUTSTANDING"]].sum()
          .sort_values("PLAFOND", ascending=False))
    top = pv.to_numpy().max() or 1   # skala bersama, jadi antar segmen bisa dibandingkan

    def _bar(label, val, color):
        return (f'<div class="hbar-top"><span>{label}</span><b>{D.fmt_money(val)}</b></div>'
                f'<div class="hbar-track"><div style="width:{max(val / top * 100, 1.5):.1f}%;'
                f'background:{color}"></div></div>')

    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex;gap:16px;font-size:12px;margin-bottom:6px">'
            f'<span><span style="color:{BRAND}">&#9632;</span> Plafond</span>'
            f'<span><span style="color:{BRAND_LIGHT}">&#9632;</span> Outstanding</span></div>',
            unsafe_allow_html=True)
        for i in range(0, len(pv), 4):
            chunk = list(pv.iloc[i:i + 4].iterrows())
            for col, (name, r) in zip(st.columns(len(chunk)), chunk):
                col.markdown(
                    f'<div class="hbars"><b>{html.escape(str(name))}</b>'
                    f'<div>{_bar("Plafond", r["PLAFOND"], BRAND)}</div>'
                    f'<div>{_bar("Outstanding", r["OUTSTANDING"], BRAND_LIGHT)}</div></div>',
                    unsafe_allow_html=True)

    st.divider()
    st.subheader("Detail data (hasil filter)")
    cols = [c for c in SAFE_DETAIL_COLUMNS if c in df.columns]
    detail = df[cols]
    max_rows = st.number_input("Jumlah baris ditampilkan", min_value=10, max_value=5000, value=100, step=10)
    st.dataframe(
        detail.head(max_rows), width="stretch", hide_index=True,
        column_config={
            "TANGGAL_PENCAIRAN": st.column_config.DateColumn("TANGGAL_PENCAIRAN", format="DD/MM/YYYY"),
            "TAHUN PENCAIRAN": st.column_config.NumberColumn("TAHUN PENCAIRAN", format="%d"),
            "BULAN_PENCAIRAN": st.column_config.NumberColumn("BULAN_PENCAIRAN", format="%d"),
            "PLAFOND": st.column_config.NumberColumn("PLAFOND", format="localized"),
            "OUTSTANDING": st.column_config.NumberColumn("OUTSTANDING", format="localized"),
            BUNGA_COLUMN: st.column_config.NumberColumn(BUNGA_COLUMN, format="localized"),
        })
    st.download_button("Download hasil filter (CSV)", detail.to_csv(index=False).encode("utf-8-sig"),
                       file_name="hasil_filter_dashboard.csv", mime="text/csv")
    st.caption(f"{D.fmt_num(len(df))} dari {D.fmt_num(len(df0))} record setelah filter.")