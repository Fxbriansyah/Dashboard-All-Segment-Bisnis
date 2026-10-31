"""Halaman-halaman dashboard: Upload -> Proses -> Ringkasan -> Dashboard."""
import hashlib
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import hashlib
import html

import data as D
import ui

from config import (BRAND, BRAND_LIGHT, DB_CONFIG, DEFAULT_THEME, KOL_COLUMN, NPL_BAD, PRODUCT_COLORS,
                    REQUIRED_COLUMNS, SAFE_DETAIL_COLUMNS, SEGMENT_ORDER, SEGMENT_THEME)

try:   # zona waktu WIB; butuh paket `tzdata` di Windows
    from zoneinfo import ZoneInfo
    WIB = ZoneInfo("Asia/Jakarta")
except Exception:  # noqa: BLE001
    WIB = timezone(timedelta(hours=7))


def now_wib():
    """Waktu sekarang di WIB, terlepas dari zona waktu server."""
    return datetime.now(WIB)


SESSION_KEYS = ["stage", "data", "file_hash", "file_name", "processed_at"]
FILTER_KEYS = ["f_year", "f_month", "f_status"]
CHART_BOX = 400   # tinggi kotak chart di baris tiga chart (px)
LEGEND_TALL = 130   # tinggi kotak legenda produk di chart donut (px); sisanya bisa di-scroll
PROD_LIST_H = 315   # tinggi kotak daftar produk per segmen (px, kira-kira 5 produk); sisanya bisa di-scroll
TREND_MONTHS, TREND_DAYS = 24, 31   # jumlah bulan / hari terakhir yang ditampilkan di grafik tren


def go_to(stage):
    st.session_state.stage = stage
    st.rerun()


def reset_all():
    st.cache_data.clear()   # buang cache supaya data selalu segar
    for k in SESSION_KEYS + FILTER_KEYS:
        st.session_state.pop(k, None)
    go_to("upload")


def _store(df, name, digest=None):
    st.session_state.update(data=df, file_name=name, file_hash=digest, processed_at=now_wib())


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
def _rp(x):
    """Nominal ringkas ('Rp 172,7 T'); nominal penuh muncul saat kursor diarahkan (tooltip)."""
    return f'<span title="{D.fmt_money(x)}">Rp {ui.compact_rp(float(x or 0))}</span>'


def _product_rows(s, names):
    """Baris produk (2 baris per produk): nama + NoA, lalu plafond + badge NPL."""
    rows = []
    for name in names:
        g = s[s["GROUP_PRODUCT"] == name]
        rows.append(
            f'<div class="prod"><div class="prod-top"><b>{html.escape(str(name))}</b>'
            f'<span>NoA {D.fmt_num(len(g))}</span></div>'
            f'<div class="prod-meta"><span>Plafond <b>{_rp(g["PLAFOND"].sum())}</b></span>'
            f'{D.npl_badge(g, "NPL ")}</div></div>')
    return "".join(rows)


def _legend_html(cmap, tall=False):
    """Legenda nama produk: 2 kolom, tinggi tetap (2 baris; tall=4 baris), sisanya bisa di-scroll."""
    items = "".join(f'<span title="{html.escape(n)}"><i style="background:{c}"></i>{html.escape(n)}</span>'
                    for n, c in cmap.items())
    style = f' style="height:{LEGEND_TALL}px;max-height:{LEGEND_TALL}px;overflow-y:auto"' if tall else ""
    return f'<div class="legend{" tall" if tall else ""}"{style}>{items}</div>'


def segment_card(df, segment):
    th = SEGMENT_THEME.get(segment, DEFAULT_THEME)
    s = df[df["PRODUCT_OWNER"] == segment]
    plafond = s["PLAFOND"].sum()
    names = list(s.groupby("GROUP_PRODUCT")["PLAFOND"].sum().sort_values(ascending=False).index)
    with st.container(border=True):
        st.markdown(
            f'<div class="seg-head" style="--seg-bg:{th["bg"]};--seg-border:{th["border"]};--seg-color:{th["color"]}">'
            f'<span>{th["icon"]}</span>{segment}</div>'
            f'<div class="seg-stats">'
            f'<div><span>NoA</span><b>{D.fmt_num(len(s))}</b></div>'
            f'<div><span>Produk</span><b>{D.fmt_num(len(names))}</b></div>'
            f'<div class="wide"><span>Plafond</span><b>{_rp(plafond)}</b></div>'
            f'<div class="wide"><span>NPL (kol 3-5)</span><b>{D.npl_badge(s)}</b></div></div>'
            f'<div class="seg-sub" style="--seg-color:{th["color"]}">Rincian per produk ({len(names)})</div>'
            f'<div class="prod-list" style="height:{PROD_LIST_H}px!important;max-height:{PROD_LIST_H}px!important;'
            f'overflow-y:auto!important;overflow-x:hidden!important">{_product_rows(s, names)}</div>',
            unsafe_allow_html=True)
        st.markdown(f'<div class="seg-sub" style="--seg-color:{th["color"]}">Komposisi group produk</div>',
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


def _npl_check(df):
    """Panel pemeriksaan: tampilkan dasar hitung NPL % supaya angka yang janggal (mis. 100%) mudah ditelusuri."""
    with st.expander("Cek perhitungan NPL"):
        st.caption("NPL % = outstanding kolektabilitas 3-5 / total outstanding. "
                   "Kalau persennya tinggi, lihat apakah total outstanding produk itu memang kecil.")
        kol = (df.groupby(KOL_COLUMN).agg(noa=("OUTSTANDING", "size"), out=("OUTSTANDING", "sum"))
               .reset_index().sort_values(KOL_COLUMN))
        tot = kol["out"].sum()
        kol_view = pd.DataFrame({
            "Kolektabilitas (nilai asli di file)": kol[KOL_COLUMN],
            "NoA": kol["noa"].map(D.fmt_num),
            "Outstanding": kol["out"].map(D.fmt_money),
            "% dari total outstanding": (kol["out"] / tot * 100 if tot else kol["out"] * 0).map(D.fmt_pct)})
        st.markdown("**Sebaran per nilai kolektabilitas**")
        st.dataframe(kol_view, hide_index=True, width="stretch")

        d = df.assign(_npl_out=df["OUTSTANDING"].where(df["IS_NPL"], 0), _aktif=df["OUTSTANDING"] > 0,
                      _npl_noa=df["IS_NPL"])
        prod = (d.groupby(["PRODUCT_OWNER", "GROUP_PRODUCT"])
                .agg(noa=("OUTSTANDING", "size"), aktif=("_aktif", "sum"), npl_noa=("_npl_noa", "sum"),
                     total=("OUTSTANDING", "sum"), npl=("_npl_out", "sum")).reset_index())
        prod["pct"] = (prod["npl"] / prod["total"] * 100).where(prod["total"] > 0, 0)
        prod = prod.sort_values("pct", ascending=False)
        prod_view = pd.DataFrame({
            "Segmen": prod["PRODUCT_OWNER"], "Produk": prod["GROUP_PRODUCT"],
            "NoA": prod["noa"].map(D.fmt_num), "NoA outstanding > 0": prod["aktif"].map(D.fmt_num),
            "NoA kol 3-5": prod["npl_noa"].map(D.fmt_num),
            "Total outstanding": prod["total"].map(D.fmt_money), "Outstanding kol 3-5": prod["npl"].map(D.fmt_money),
            "NPL %": prod["pct"].map(D.fmt_pct)})
        st.markdown("**Rincian per produk (diurutkan dari NPL % tertinggi)**")
        st.dataframe(prod_view, hide_index=True, width="stretch")


def _trend_chart(d, x, order, metric, segs, kind="Garis", xfmt=None, date_axis=False, tickangle=0):
    """Tren per segmen. kind = 'Garis' (satu garis per segmen + garis putus-putus total) atau 'Kolom' (bertumpuk).
    metric = 'Plafond' (nominal) atau 'NoA' (jumlah rekening)."""
    g = d.groupby([x, "PRODUCT_OWNER"], as_index=False).agg(val=("PLAFOND", "sum" if metric == "Plafond" else "size"))
    color_of = {n: SEGMENT_THEME.get(n, DEFAULT_THEME)["color"] for n in segs}
    unit = "Rp %{y:,.0f}" if metric == "Plafond" else "%{y:,.0f} rekening"
    hover = f"%{{fullData.name}}: {unit}<extra></extra>"   # judul hover = nilai sumbu X

    if kind == "Garis":
        idx = list(pd.date_range(min(order), max(order))) if date_axis else list(order)   # periode kosong = 0
        p = (g.pivot_table(index=x, columns="PRODUCT_OWNER", values="val", aggfunc="sum")
             .reindex(idx).fillna(0))
        fig = go.Figure()
        for n in segs:
            if n in p.columns:
                fig.add_trace(go.Scatter(x=p.index, y=p[n], name=n, mode="lines+markers", hovertemplate=hover,
                                         line=dict(color=color_of[n], width=2.5), marker=dict(size=6)))
        total = p.sum(axis=1)
        fig.add_trace(go.Scatter(x=p.index, y=total, name="Total", mode="lines", hovertemplate=hover,
                                 line=dict(color="#334155", width=2, dash="dot")))
        top = total.max()
    else:
        cats = {"PRODUCT_OWNER": segs} if date_axis else {"PRODUCT_OWNER": segs, x: order}
        fig = px.bar(g, x=x, y="val", color="PRODUCT_OWNER", category_orders=cats, color_discrete_map=color_of)
        fig.update_traces(hovertemplate=hover)
        fig.update_layout(bargap=0.3, barmode="stack")
        top = g.groupby(x)["val"].sum().max()

    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="date" if date_axis else "category", tickangle=tickangle,
                     **({"tickformat": "%d %b", "hoverformat": "%d %b %Y"} if date_axis else {}))
    if metric == "Plafond":
        ui.rupiah_axis(fig, top)
    ui.style_fig(fig, 330)
    # legenda di atas grafik (di bawah bertabrakan dengan label sumbu X yang miring)
    fig.update_layout(margin=dict(l=8, r=8, t=44, b=8),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                                  font=dict(size=12), title_text=""))
    ui.show_fig(fig)


def _trend_section(df):
    """Tren pencairan harian / bulanan / tahunan, dipecah per segmen."""
    st.subheader("Tren pencairan")
    r1, r2, _ = st.columns([1.2, 1.2, 3])
    metric = r1.radio("Ukuran", ["Plafond", "NoA"], horizontal=True, key="trend_metric")
    kind = r2.radio("Tampilan", ["Garis", "Kolom"], horizontal=True, key="trend_kind")
    segs = [s for s in SEGMENT_ORDER if s in set(df["PRODUCT_OWNER"])]
    segs += [s for s in df["PRODUCT_OWNER"].unique() if s not in segs]
    t_day, t_month, t_year = st.tabs(["Harian", "Bulanan", "Tahunan"])

    with t_day:
        d = df.dropna(subset=["TANGGAL_PENCAIRAN"]).copy()
        if d.empty:
            st.info("Tidak ada tanggal pencairan yang valid untuk filter ini.")
        else:
            d["TANGGAL"] = d["TANGGAL_PENCAIRAN"].dt.normalize()
            days = sorted(d["TANGGAL"].unique())[-TREND_DAYS:]
            d = d[d["TANGGAL"].isin(days)]
            _trend_chart(d, "TANGGAL", days, metric, segs, kind, xfmt="%d %b %Y", date_axis=True)
            n_kosong = int(df["TANGGAL_PENCAIRAN"].isna().sum())
            st.caption(f"Menampilkan {len(days)} hari pencairan terakhir (maks. {TREND_DAYS})."
                       + (f" {D.fmt_num(n_kosong)} baris tanpa tanggal valid tidak ikut." if n_kosong else ""))

    with t_month:
        d = df.dropna(subset=["TAHUN PENCAIRAN", "BULAN_PENCAIRAN"]).copy()
        if d.empty:
            st.info("Tidak ada data tahun/bulan pencairan untuk filter ini.")
        else:
            d["_p"] = d["TAHUN PENCAIRAN"].astype(int) * 100 + d["BULAN_PENCAIRAN"].astype(int)
            periods = sorted(d["_p"].unique())[-TREND_MONTHS:]
            d = d[d["_p"].isin(periods)]
            label = lambda p: f"{D.fmt_bulan(p % 100)[:3]} {p // 100}"
            d["BULAN"] = d["_p"].map(label)
            _trend_chart(d, "BULAN", [label(p) for p in periods], metric, segs, kind,
                         tickangle=-45 if len(periods) > 12 else 0)
            st.caption(f"Menampilkan {len(periods)} bulan terakhir (maks. {TREND_MONTHS}).")

    with t_year:
        d = df.dropna(subset=["TAHUN PENCAIRAN"]).copy()
        if d.empty:
            st.info("Tidak ada data tahun pencairan untuk filter ini.")
        else:
            years = sorted(d["TAHUN PENCAIRAN"].astype(int).unique())
            d["TAHUN"] = d["TAHUN PENCAIRAN"].astype(int).astype(str)
            _trend_chart(d, "TAHUN", [str(y) for y in years], metric, segs, kind)


def _reset_filters():
    for k in FILTER_KEYS:
        st.session_state[k] = []


def _filter_bar(df0):
    """Bar filter di atas halaman (menggantikan sidebar)."""
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2])
        c1.multiselect("Tahun pencairan", sorted(df0["TAHUN PENCAIRAN"].dropna().unique()), key="f_year",
                       format_func=D.fmt_tahun, placeholder="Semua")
        c2.multiselect("Bulan pencairan", sorted(df0["BULAN_PENCAIRAN"].dropna().unique()), key="f_month",
                       format_func=D.fmt_bulan, placeholder="Semua")
        c3.multiselect("Status loan", sorted(df0["STATUS_LOAN"].unique()), key="f_status",
                       format_func=D.fmt_status, placeholder="Semua")
        aktif = sum(bool(st.session_state.get(k)) for k in FILTER_KEYS)
        info = f"dari {D.fmt_num(len(df0))} record" + (f" · {aktif} filter aktif" if aktif else "")
        with c4:
            st.markdown(f'<div class="side-result"><span>Data ditampilkan</span>'
                        f'<b>{D.fmt_num(len(_apply_filters(df0)))}</b><small>{info}</small></div>',
                        unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            b1.button("Reset filter", on_click=_reset_filters, width="stretch", disabled=not aktif)
            if b2.button("Upload ulang", width="stretch"):
                reset_all()
    st.caption(f"Sumber: {st.session_state.get('file_name', '-')} · kolom identitas sensitif tidak ditampilkan di tabel.")


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
    ts = st.session_state.get("processed_at")
    left, right = st.columns([3, 1])
    left.markdown('<div class="title-card"><div class="page-title">Dashboard Pencairan</div>'
                  '<div class="page-desc">Semua segmen bisnis</div></div>', unsafe_allow_html=True)
    right.markdown(f'<div class="chip">Data diproses<b>{ts.strftime("%d %b %Y %H:%M") if ts else "-"}</b></div>',
                   unsafe_allow_html=True)
    st.write("")
    _filter_bar(df0)
    df = _apply_filters(df0)
    if df.empty:
        st.info("Tidak ada data untuk filter ini. Ubah atau reset filter di atas.")
        return

    plafond, outstanding = df["PLAFOND"].sum(), df["OUTSTANDING"].sum()
    npl_p = D.npl_pct(df)
    ui.kpis([
        ("Total NoA", D.fmt_num(len(df)), "jumlah rekening pencairan"),
        ("Total plafond", _rp(plafond), "total yang dicairkan", D.fmt_money(plafond)),
        ("Total outstanding", _rp(outstanding), "sisa pokok yang masih berjalan", D.fmt_money(outstanding)),
        ("Outstanding / plafond", D.fmt_pct(outstanding / plafond * 100 if plafond else 0),
         "makin kecil = makin banyak yang sudah dilunasi"),
        ("NPL (kol 3-5)", D.npl_badge(df), f"batas sehat di bawah {NPL_BAD:g}%", "", f"kpi-{D.npl_level(npl_p)}"),
    ])
    if "IS_NPL" not in df.columns:
        st.caption(f"NPL % tidak dapat dihitung: kolom {KOL_COLUMN} tidak ada di data.")

    _trend_section(df)
    st.write("")

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
            st.subheader("Plafond per segmen")
            with st.container(border=True, height=CHART_BOX):
                pf = (df.groupby("PRODUCT_OWNER", as_index=False)["PLAFOND"].sum()
                      .sort_values("PLAFOND", ascending=False))
                fig = px.bar(pf, x="PRODUCT_OWNER", y="PLAFOND", color="PRODUCT_OWNER",
                             color_discrete_map={s: SEGMENT_THEME.get(s, DEFAULT_THEME)["color"]
                                                 for s in pf["PRODUCT_OWNER"]})
                fig.update_traces(hovertemplate="%{x}<br>Rp %{y:,.0f}<extra></extra>")
                fig.update_layout(bargap=0.35, showlegend=False)
                fig.update_xaxes(tickvals=list(pf["PRODUCT_OWNER"]),
                                 ticktext=[str(n).replace(" ", "<br>") for n in pf["PRODUCT_OWNER"]], tickangle=0)
                ui.rupiah_axis(fig, pf["PLAFOND"].max())
                ui.show_fig(ui.style_fig(fig, CHART_BOX - 48))
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
                fig = ui.style_fig(fig, CHART_BOX - 205)
                fig.update_layout(margin=dict(l=10, r=10, t=12, b=12))
                ui.show_fig(fig)
                st.markdown(_legend_html(cmap, tall=True), unsafe_allow_html=True)

    st.subheader("Plafond vs outstanding per segmen")
    pv = (df.groupby("PRODUCT_OWNER")[["PLAFOND", "OUTSTANDING"]].sum()
          .sort_values("PLAFOND", ascending=False).reset_index())
    long = pv.melt(id_vars="PRODUCT_OWNER", var_name="Jenis", value_name="Nilai")
    long["Jenis"] = long["Jenis"].str.capitalize()   # Plafond / Outstanding
    long["Label"] = long["Nilai"].map(ui.compact_rp)
    with st.container(border=True):
        fig = px.bar(long, x="PRODUCT_OWNER", y="Nilai", color="Jenis", barmode="group", text="Label",
                     category_orders={"PRODUCT_OWNER": list(pv["PRODUCT_OWNER"]), "Jenis": ["Plafond", "Outstanding"]},
                     color_discrete_map={"Plafond": BRAND, "Outstanding": BRAND_LIGHT})
        fig.update_traces(textposition="outside", cliponaxis=False, textfont=dict(size=11),
                          hovertemplate="%{x}<br>%{fullData.name}: Rp %{y:,.0f}<extra></extra>")
        fig.update_layout(bargap=0.35, bargroupgap=0.08)
        ui.rupiah_axis(fig, long["Nilai"].max() * 1.12)
        ui.style_fig(fig, 380, legend_bottom=False)
        fig.update_layout(margin=dict(l=8, r=8, t=40, b=8),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""))
        ui.show_fig(fig)

    if "IS_NPL" in df.columns:
        _npl_check(df)

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
        })
    st.download_button("Download hasil filter (CSV)", detail.to_csv(index=False).encode("utf-8-sig"),
                       file_name="hasil_filter_dashboard.csv", mime="text/csv")
    st.caption(f"{D.fmt_num(len(df))} dari {D.fmt_num(len(df0))} record setelah filter.")