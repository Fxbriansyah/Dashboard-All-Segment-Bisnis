"""Halaman-halaman dashboard: Upload -> Proses -> Ringkasan -> Dashboard."""
import hashlib
import html

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

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
FILTER_KEYS = ["f_status"]
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
def _fmt_size(n):
    """Ukuran file: 95420000 -> '91,0 MB'."""
    for div, unit in ((1024 ** 2, "MB"), (1024, "KB")):
        if n >= div:
            return f"{n / div:,.1f} {unit}".replace(".", ",")
    return f"{n} B"


def page_processing():
    ui.stepper(1)
    ui.page_header("Memproses data", "Mohon tunggu, file sedang dibaca dan dibersihkan. Jangan tutup halaman ini.")
    pending = st.session_state.get("_pending")
    if not pending:
        go_to("upload")
    raw_bytes, digest, name = pending

    problem = None
    for _ in range(3):   # timpa sisa elemen halaman upload (uploader redup) selama proses berjalan
        st.empty()
    with st.container(border=True, key="proc-card"):
        st.markdown(
            f'<div class="proc-file"><div class="proc-ico">📄</div>'
            f'<div><b>{html.escape(name)}</b><small>{_fmt_size(len(raw_bytes))}</small></div></div>',
            unsafe_allow_html=True)
        st.markdown("**Kolom wajib di file:**")
        st.markdown('<div class="proc-cols">' + "".join(f"<span>{c}</span>" for c in REQUIRED_COLUMNS) + "</div>",
                    unsafe_allow_html=True)
        with st.status("Memproses file...", expanded=True) as status:
            try:
                st.write("Membaca file Excel (file besar bisa memakan waktu)")
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
            status.update(label="Gagal memproses file" if problem else "Selesai",
                          state="error" if problem else "complete")

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
    key = "tile_seg_" + "".join(ch if ch.isalnum() else "_" for ch in segment)
    with st.container(border=False, key=key):
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


def _trend_chart(d, x, order, metric, segs, kind="Garis", xfmt=None, date_axis=False, tickangle=0,
                 height=330, tmargin=44):
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
    ui.style_fig(fig, height)
    # legenda di atas grafik (di bawah bertabrakan dengan label sumbu X yang miring)
    fig.update_layout(margin=dict(l=8, r=8, t=tmargin, b=8),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                                  font=dict(size=14), title_text=""))
    ui.show_fig(fig)

def _daily_rows(s, names):
    """Baris produk untuk kartu harian: nama + NoA, lalu plafond dan outstanding."""
    rows = []
    for name in names:
        g = s[s["GROUP_PRODUCT"] == name]
        rows.append(
            f'<div class="prod"><div class="prod-top"><b>{html.escape(str(name))}</b>'
            f'<span>NoA {D.fmt_num(len(g))}</span></div>'
            f'<div class="prod-meta"><span>Plafond</span><b>{_rp(g["PLAFOND"].sum())}</b></div>'
            f'<div class="prod-meta"><span>Outstanding</span><b>{_rp(g["OUTSTANDING"].sum())}</b></div></div>')
    return "".join(rows)

def _period_rows(s, names):
    """Baris produk: nama, lalu NoA, lalu plafond (tiga baris)."""
    rows = []
    for name in names:
        g = s[s["GROUP_PRODUCT"] == name]
        rows.append(
            f'<div class="prod"><div class="prod-top"><b>{html.escape(str(name))}</b></div>'
            f'<div class="prod-meta"><span>NoA</span><b>{D.fmt_num(len(g))}</b></div>'
            f'<div class="prod-meta"><span>Plafond</span><b>{_rp(g["PLAFOND"].sum())}</b></div></div>')
    return "".join(rows)


def _period_card(d, segment, prefix):
    """Kartu satu segmen: NoA (besar), jumlah produk, plafond + rincian per produk."""
    th = SEGMENT_THEME.get(segment, DEFAULT_THEME)
    s = d[d["PRODUCT_OWNER"] == segment]
    names = list(s.groupby("GROUP_PRODUCT")["PLAFOND"].sum().sort_values(ascending=False).index)
    key = f"segcard_{prefix}_" + "".join(ch if ch.isalnum() else "_" for ch in segment)   # unik per tab; kartu ber-border (lihat style.css)
    with st.container(border=False, key=key):
        st.markdown(
            f'<div class="seg-head" style="--seg-bg:{th["bg"]};--seg-border:{th["border"]};--seg-color:{th["color"]}">'
            f'<span>{th["icon"]}</span>{segment}</div>'
            f'<div class="seg-stats">'
            f'<div><span>NoA</span><b>{D.fmt_num(len(s))}</b></div>'
            f'<div><span>Produk</span><b>{D.fmt_num(len(names))}</b></div>'
            f'<div class="wide"><span>Plafond</span><b>{_rp(s["PLAFOND"].sum())}</b></div></div>'
            f'<div class="seg-sub" style="--seg-color:{th["color"]}">Produk cair ({len(names)})</div>'
            f'<div class="prod-list" style="height:{PROD_LIST_H}px!important;max-height:{PROD_LIST_H}px!important;'
            f'overflow-y:auto!important;overflow-x:hidden!important">{_period_rows(s, names)}</div>',
            unsafe_allow_html=True)


def _period_report(d, segs, prefix, title, empty_msg):
    """Isi satu tab tren: total NoA + plafond, lalu kartu per segmen (hanya segmen yang ada pencairannya)."""
    st.markdown(f'<div class="trend-title">{html.escape(title)}</div>', unsafe_allow_html=True)
    if d.empty:
        st.info(empty_msg)
        return
    with st.container(key=f"trendkpi_{prefix}"):
        ui.kpis([("Total NoA", D.fmt_num(len(d))),
                 ("Total plafond", _rp(d["PLAFOND"].sum()), "", D.fmt_money(d["PLAFOND"].sum()))])
    aktif = [s for s in segs if s in set(d["PRODUCT_OWNER"])]
    with st.container(key=f"segments_{prefix}"):
        for i in range(0, len(aktif), 4):
            row = aktif[i:i + 4]
            for col, seg in zip(st.columns(len(row)), row):
                with col:
                    _period_card(d, seg, prefix)


def _daily_report(df, segs):
    today = now_wib().date()
    with st.container(border=True, key="trendbox_day"):
        picked = st.date_input("Tanggal pencairan", value=(today, today), format="DD/MM/YYYY",
                               key="trend_day", help="Pilih satu hari, atau dua tanggal untuk satu rentang.")
    if isinstance(picked, (tuple, list)):
        if len(picked) < 2:   # baru memilih tanggal awal
            st.info("Pilih tanggal akhir untuk melengkapi rentang.")
            return
        start, end = picked
    else:
        start = end = picked

    d = df.dropna(subset=["TANGGAL_PENCAIRAN"])
    d = d[d["TANGGAL_PENCAIRAN"].between(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1),
                                         inclusive="left")]
    if start == end:
        title = f"Pencairan {'hari ini' if start == today else 'tanggal'} - {start:%d/%m/%Y}"
    else:
        title = f"Pencairan {start:%d/%m/%Y} s.d. {end:%d/%m/%Y}"
    last = df["TANGGAL_PENCAIRAN"].max()
    msg = ("Tidak ada pencairan pada tanggal ini dengan filter yang dipilih."
           + (f" Tanggal pencairan terakhir di data: {last:%d/%m/%Y}." if pd.notna(last) else ""))
    _period_report(d, segs, "day", title, msg)


def _year_options(df, now):
    """Tahun yang ada di data, ditambah tahun berjalan, terbaru di atas."""
    return sorted({int(y) for y in df["TAHUN PENCAIRAN"].dropna().unique()} | {now.year}, reverse=True)


def _monthly_report(df, segs):
    now = now_wib()
    years = _year_options(df, now)
    with st.container(border=True, key="trendbox_month"):
        c1, c2 = st.columns(2)
        year = c1.selectbox("Tahun", years, index=years.index(now.year), key="trend_m_year")
        month = c2.selectbox("Bulan", list(range(1, 13)), index=now.month - 1,
                             format_func=D.fmt_bulan, key="trend_m_month")
    d = df[(df["TAHUN PENCAIRAN"] == year) & (df["BULAN_PENCAIRAN"] == month)]
    suffix = "" if (year, month) == (now.year, now.month) else ""
    _period_report(d, segs, "month", f"Pencairan {D.fmt_bulan(month)} {year}{suffix}",
                   "Tidak ada pencairan pada bulan ini dengan filter yang dipilih.")


def _yearly_report(df, segs):
    now = now_wib()
    years = _year_options(df, now)
    with st.container(border=True, key="trendbox_year"):
        year = st.selectbox("Tahun", years, index=years.index(now.year), key="trend_y_year")
    d = df[df["TAHUN PENCAIRAN"] == year]
    suffix = "" if year == now.year else ""
    _period_report(d, segs, "year", f"Pencairan tahun {year}{suffix}",
                   "Tidak ada pencairan pada tahun ini dengan filter yang dipilih.")


def _trend_section(df):
    """Pencairan hari ini / bulan berjalan / tahun berjalan, dipecah per segmen dan produk."""
    st.subheader("Tren pencairan")
    segs = [s for s in SEGMENT_ORDER if s in set(df["PRODUCT_OWNER"])]
    segs += [s for s in df["PRODUCT_OWNER"].unique() if s not in segs]
    t_day, t_month, t_year = st.tabs(["Harian", "Bulanan", "Tahunan"])
    with t_day:
        _daily_report(df, segs)
    with t_month:
        _monthly_report(df, segs)
    with t_year:
        _yearly_report(df, segs)
        
def _reset_filters():
    for k in FILTER_KEYS:
        st.session_state[k] = []


def _side_label(icon, text):
    st.markdown(f'<div class="side-label"><i>{icon}</i>{text}</div>', unsafe_allow_html=True)


def _sidebar_filters(df0):
    """Filter + pilihan tampilan (Ringkas / Rinci) di sidebar, dikelompokkan dalam kartu."""
    fname = html.escape(str(st.session_state.get("file_name", "-")))
    with st.sidebar:
        with st.container(border=True, key="side_view"):
            _side_label("▦", "Tampilan")
            st.segmented_control("Tampilan", ["Ringkas", "Rinci"], key="view_mode", width="stretch",
                                 label_visibility="collapsed",
                                 format_func=lambda m: {"Ringkas": "▦ Ringkas", "Rinci": "☰ Rinci"}[m])
            st.caption("Ringkas: semua tile dalam satu layar. Rinci: lengkap dengan kartu segmen, grafik, dan tabel.")

        with st.container(border=True, key="side_filter"):
            _side_label("⚙", "Saring data")
            st.multiselect("Status loan", sorted(df0["STATUS_LOAN"].unique()), key="f_status",
                           format_func=D.fmt_status, placeholder="Semua status")
            picked = st.session_state.get("f_status") or []
            if picked:
                st.markdown('<div class="side-chips">' + "".join(
                    f"<span>Status {html.escape(D.fmt_status(c))}</span>" for c in picked) + "</div>",
                    unsafe_allow_html=True)

        aktif = sum(bool(st.session_state.get(k)) for k in FILTER_KEYS)
        total, shown = len(df0), len(_apply_filters(df0))
        pct = shown / total * 100 if total else 0
        info = f"dari {D.fmt_num(total)} record" + (f" · {aktif} filter aktif" if aktif else "")
        st.markdown(f'<div class="side-result"><span>Data ditampilkan</span>'
                    f'<b>{D.fmt_num(shown)}</b><small>{info}</small>'
                    f'<div class="side-bar"><div style="width:{pct:.1f}%"></div></div>'
                    f'<small>{D.fmt_pct(pct)} dari seluruh data</small></div>',
                    unsafe_allow_html=True)
        
        if st.button("Upload ulang", icon=":material/upload_file:", width="stretch"):
            reset_all()
        st.markdown(f'<div class="side-source"><i>📄</i><div><b>{fname}</b>'
                    f'<small>Kolom identitas sensitif tidak ditampilkan di tabel.</small></div></div>',
                    unsafe_allow_html=True)


def _apply_filters(df0):
    df, ss = df0, st.session_state
    if ss.get("f_status"):
        df = df[df["STATUS_LOAN"].isin(ss["f_status"])]
    return df


THEME_CSS = """
.stApp{background:#19c98f !important}
[data-testid="stMainBlockContainer"]{padding-top:1.2rem !important;padding-bottom:1rem !important;max-width:100% !important}
[class*="st-key-tile_"],[data-testid="stExpander"]{background:#fff !important;border:0 !important;
  border-radius:20px !important;box-shadow:none !important;box-sizing:border-box}
[class*="st-key-tile_"]{padding:12px 14px !important}
[data-testid="stExpander"] details{border:0 !important}
[data-testid="stHeading"] h1,[data-testid="stHeading"] h2,[data-testid="stHeading"] h3{color:#06382c !important}
[data-testid="stCaptionContainer"]{color:#06382c !important}
[class*="st-key-tile_"] [data-testid="stHeading"] h3,[class*="st-key-tile_"] [data-testid="stCaptionContainer"]{color:#0f172a !important}
"""

RINGKAS_CSS = """
[data-testid="stVerticalBlock"]{gap:.7rem !important}
.tile-title{font-weight:800;font-size:var(--fs-md);color:#0f172a;text-align:center;margin-bottom:2px}
.tile-big{font-size:var(--fs-2xl);font-weight:800;color:#0f172a;text-align:center;line-height:1.2;margin-top:6px}
.tile-big .npl{font-size:.8em;padding:2px 18px}
.tile-sub{text-align:center;font-size:var(--fs-xs);color:#64748b;margin-top:2px}
table.mini{width:100%;border-collapse:collapse;font-size:var(--fs-sm);margin-top:4px}
table.mini th{text-align:left;color:#475569;font-weight:700;border-bottom:1px solid #cbd5e1;padding:4px 6px}
table.mini td{padding:5px 6px;border-bottom:1px solid #f1f5f9;color:#0f172a}
table.mini .num{text-align:right;white-space:nowrap}
table.mini tr.total td{font-weight:800;border-top:1px solid #cbd5e1;border-bottom:0}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
"""

def _badge(p):
    return f'<span class="npl npl-{D.npl_level(p)}">{"-" if p is None else D.fmt_pct(p)}</span>'


def _mini_table(headers, rows, total=None):
    """Tabel HTML kecil. headers: [teks]; rows/total: [html sel]; kolom pertama rata kiri, sisanya rata kanan."""
    def tr(cells, cls=""):
        return f'<tr class="{cls}">' + "".join(
            f'<td class="{"num" if i else ""}">{c}</td>' for i, c in enumerate(cells)) + "</tr>"
    head = "".join(f'<th class="{"num" if i else ""}">{h}</th>' for i, h in enumerate(headers))
    body = "".join(tr(r) for r in rows) + (tr(total, "total") if total else "")
    return f'<table class="mini"><tr>{head}</tr>{body}</table>'


def _tile_title(text):
    st.markdown(f'<div class="tile-title">{text}</div>', unsafe_allow_html=True)


def _product_stats(df):
    """Per group produk: plafond, outstanding, NPL % (None kalau kolom kolektabilitas tidak ada)."""
    has = "IS_NPL" in df.columns
    d = df.assign(_n=df["OUTSTANDING"].where(df["IS_NPL"], 0) if has else 0.0)
    t = d.groupby("GROUP_PRODUCT").agg(plafond=("PLAFOND", "sum"), outstanding=("OUTSTANDING", "sum"),
                                       npl=("_n", "sum")).reset_index()
    t["pct"] = (t["npl"] / t["outstanding"] * 100).where(t["outstanding"] > 0, 0.0) if has else None
    return t


def _dashboard_ringkas(df):
    """Tampilan padat satu layar (cocok untuk screenshot): KPI, tren, ringkasan segmen, 4 tile kecil."""
    st.markdown(f"<style>{RINGKAS_CSS}</style>", unsafe_allow_html=True)
    H_KPI, H_ROW = 124, 270
    plafond, outstanding = df["PLAFOND"].sum(), df["OUTSTANDING"].sum()
    segs = [x for x in SEGMENT_ORDER if x in set(df["PRODUCT_OWNER"])]
    segs += [x for x in df["PRODUCT_OWNER"].unique() if x not in segs]
    color = lambda n: SEGMENT_THEME.get(n, DEFAULT_THEME)["color"]

    # --- Baris 1: KPI ---
    kpi = [("Total NoA", D.fmt_num(len(df)), "jumlah rekening pencairan"),
           ("Total plafond", _rp(plafond), "total yang dicairkan"),
           ("Total outstanding", _rp(outstanding), "sisa pokok yang berjalan"),
           ("Outstanding / plafond", D.fmt_pct(outstanding / plafond * 100 if plafond else 0), "dari total plafond"),
           ("NPL (kol 3-5)", _badge(D.npl_pct(df)), f"batas sehat di bawah {NPL_BAD:g}%")]
    for i, (col, (t, v, sub)) in enumerate(zip(st.columns(5), kpi)):
        with col, st.container(border=False, height=H_KPI, key=f"tile_kpi{i}"):
            st.markdown(f'<div class="tile-title">{t}</div><div class="tile-big">{v}</div>'
                        f'<div class="tile-sub">{sub}</div>', unsafe_allow_html=True)

    # --- Baris 2: tren bulanan + ringkasan per segmen ---
    a, b = st.columns([2, 1.2])
    with a, st.container(border=False, height=H_ROW, key="tile_tren"):
        _tile_title("Tren pencairan bulanan (plafond)")
        d = df.dropna(subset=["TAHUN PENCAIRAN", "BULAN_PENCAIRAN"]).copy()
        if d.empty:
            st.info("Tidak ada data bulan pencairan.")
        else:
            d["_p"] = d["TAHUN PENCAIRAN"].astype(int) * 100 + d["BULAN_PENCAIRAN"].astype(int)
            periods = sorted(d["_p"].unique())[-12:]
            d = d[d["_p"].isin(periods)]
            label = lambda p: f"{D.fmt_bulan(p % 100)[:3]} {p // 100}"
            d["BULAN"] = d["_p"].map(label)
            _trend_chart(d, "BULAN", [label(p) for p in periods], "Plafond", segs, "Garis",
                         tickangle=-45, height=H_ROW - 54, tmargin=26)
    with b, st.container(border=False, height=H_ROW, key="tile_segmen"):
        _tile_title("Ringkasan per segmen")
        rows = []
        for n in segs:
            sdf = df[df["PRODUCT_OWNER"] == n]
            rows.append([f'<i class="dot" style="background:{color(n)}"></i>{html.escape(n)}', D.fmt_num(len(sdf)),
                         _rp(sdf["PLAFOND"].sum()), _rp(sdf["OUTSTANDING"].sum()), _badge(D.npl_pct(sdf))])
        st.markdown(_mini_table(["Segmen", "NoA", "Plafond", "Outstanding", "NPL"], rows,
                                ["Total", D.fmt_num(len(df)), _rp(plafond), _rp(outstanding),
                                 _badge(D.npl_pct(df))]), unsafe_allow_html=True)

    # --- Baris 3: 4 tile kecil ---
    c1, c2, c3, c4 = st.columns(4)
    with c1, st.container(border=False, height=H_ROW, key="tile_mingguan"):
        _tile_title("Pencairan 7 hari terakhir (plafond)")
        w = df.dropna(subset=["TANGGAL_PENCAIRAN"])
        if w.empty:
            st.info("Tidak ada tanggal pencairan valid.")
        else:
            w = w.assign(_t=w["TANGGAL_PENCAIRAN"].dt.normalize())
            days = pd.date_range(w["_t"].max() - pd.Timedelta(days=6), w["_t"].max())
            v = w.groupby("_t")["PLAFOND"].sum().reindex(days).fillna(0)
            fig = go.Figure(go.Scatter(
                x=days, y=v.values, mode="lines+markers+text", text=[ui.compact_rp(x) for x in v.values],
                textposition="top center", textfont=dict(size=14), fill="tozeroy", fillcolor="rgba(147,197,253,.55)",
                line=dict(color=BRAND, width=2.5, shape="spline"), marker=dict(size=7, color="#0f172a"),
                hovertemplate="%{x|%d %b %Y}<br>Rp %{y:,.0f}<extra></extra>"))
            fig.update_xaxes(tickformat="%d %b", tickmode="array", tickvals=days, tickangle=-45)
            fig.update_yaxes(visible=False, range=[0, max(v.max() * 1.3, 1)])
            ui.show_fig(ui.style_fig(fig, H_ROW - 54))
    ps = _product_stats(df)
    with c2, st.container(border=False, height=H_ROW, key="tile_topproduk"):
        _tile_title("Top 5 produk (plafond)")
        top = ps.sort_values("plafond", ascending=False).head(5)
        st.markdown(_mini_table(["Produk", "Plafond", "NPL"], [
            [html.escape(str(r.GROUP_PRODUCT)), _rp(r.plafond), _badge(r.pct)] for r in top.itertuples()]),
            unsafe_allow_html=True)
    with c3, st.container(border=False, height=H_ROW, key="tile_nplproduk"):
        _tile_title("NPL tertinggi (produk)")
        if "IS_NPL" not in df.columns:
            st.info(f"Kolom {KOL_COLUMN} tidak ada di data.")
        else:
            risk = ps[ps["outstanding"] > 0].sort_values("pct", ascending=False).head(5)
            st.markdown(_mini_table(["Produk", "Outstanding", "NPL"], [
                [html.escape(str(r.GROUP_PRODUCT)), _rp(r.outstanding), _badge(r.pct)] for r in risk.itertuples()]),
                unsafe_allow_html=True)
    with c4, st.container(border=False, height=H_ROW, key="tile_donut"):
        _tile_title("Outstanding per segmen")
        o = df.groupby("PRODUCT_OWNER", as_index=False)["OUTSTANDING"].sum()
        fig = px.pie(o, names="PRODUCT_OWNER", values="OUTSTANDING", hole=0.55, color="PRODUCT_OWNER",
                     color_discrete_map={n: color(n) for n in segs}, category_orders={"PRODUCT_OWNER": segs})
        fig.update_traces(textinfo="percent", textfont_size=14, sort=False,
                          hovertemplate="%{label}<br>Rp %{value:,.0f}<extra></extra>")
        ui.style_fig(fig, H_ROW - 54)
        fig.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="center",
                                                       x=0.5, font=dict(size=14), title_text=""))
        ui.show_fig(fig)


def page_dashboard():
    df0 = st.session_state.get("data")
    if df0 is None:
        go_to("upload")
    ts = st.session_state.get("processed_at")
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)
    st.session_state.setdefault("view_mode", "Ringkas")
    _sidebar_filters(df0)
    ringkas = st.session_state.get("view_mode") != "Rinci"   # None (pilihan dilepas) dianggap Ringkas
    left, right = st.columns([4, 1])
    left.markdown('<div class="title-card"><div class="page-title">Dashboard Pencairan</div>'
                  '<div class="page-desc">Semua segmen bisnis</div></div>', unsafe_allow_html=True)
    right.markdown(f'<div class="chip">Data diproses<b>{ts.strftime("%d %b %Y %H:%M") if ts else "-"}</b></div>',
                   unsafe_allow_html=True)
    st.write("")
    df = _apply_filters(df0)
    if df.empty:
        st.info("Tidak ada data untuk filter ini.")
        return
    if ringkas:
        _dashboard_ringkas(df)
        return

    with st.container(border=False, key="tile_trend"):
        _trend_section(df)
    st.write("")

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

    with st.container(key="charts"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("Plafond per segmen")
            with st.container(border=False, height=CHART_BOX, key="tile_c1"):
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
            with st.container(border=False, height=CHART_BOX, key="tile_c2"):
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
            with st.container(border=False, height=CHART_BOX, key="tile_c3"):
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
    with st.container(border=False, key="tile_pv"):
        fig = px.bar(long, x="PRODUCT_OWNER", y="Nilai", color="Jenis", barmode="group", text="Label",
                     category_orders={"PRODUCT_OWNER": list(pv["PRODUCT_OWNER"]), "Jenis": ["Plafond", "Outstanding"]},
                     color_discrete_map={"Plafond": BRAND, "Outstanding": BRAND_LIGHT})
        fig.update_traces(textposition="outside", cliponaxis=False, textfont=dict(size=14),
                          hovertemplate="%{x}<br>%{fullData.name}: Rp %{y:,.0f}<extra></extra>")
        fig.update_layout(bargap=0.35, bargroupgap=0.08)
        ui.rupiah_axis(fig, long["Nilai"].max() * 1.12)
        ui.style_fig(fig, 380, legend_bottom=False)
        fig.update_layout(margin=dict(l=8, r=8, t=40, b=8),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""))
        ui.show_fig(fig)

    if "IS_NPL" in df.columns:
        _npl_check(df)

    with st.container(border=False, key="tile_detail"):
        st.subheader("Detail data (hasil filter)")
        cols = [c for c in SAFE_DETAIL_COLUMNS if c in df.columns]
        detail = df[cols]
        max_rows = st.number_input("Jumlah baris ditampilkan", min_value=10, max_value=5000, value=100, step=10)
        st.dataframe(
            detail.head(max_rows), width="stretch", hide_index=True,
            column_config={
                "TANGGAL_PENCAIRAN": st.column_config.DateColumn("TANGGAL_PENCAIRAN", format="dd/mm/yyyy"),
                "TAHUN PENCAIRAN": st.column_config.NumberColumn("TAHUN PENCAIRAN", format="%d"),
                "BULAN_PENCAIRAN": st.column_config.NumberColumn("BULAN_PENCAIRAN", format="%d"),
                "PLAFOND": st.column_config.NumberColumn("PLAFOND", format="localized"),
                "OUTSTANDING": st.column_config.NumberColumn("OUTSTANDING", format="localized"),
            })
        st.download_button("Download hasil filter (CSV)", detail.to_csv(index=False).encode("utf-8-sig"),
                           file_name="hasil_filter_dashboard.csv", mime="text/csv")
        st.caption(f"{D.fmt_num(len(df))} dari {D.fmt_num(len(df0))} record setelah filter.")