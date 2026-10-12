"""Format angka, pembersihan data Excel, dan akses database (opsional)."""
import io

import pandas as pd
import streamlit as st

from config import (BULAN_LABEL, BULAN_TEXT_TO_NUM, BUNGA_COLUMN, DB_COLUMN_TO_APP, DB_CONFIG,
                    REQUIRED_COLUMNS, STATUS_LOAN_LABEL, TEXT_COLUMNS)


# ---------- Format ala Indonesia (titik ribuan, koma desimal) ----------
def _id(s):
    return s.translate(str.maketrans(",.", ".,"))


def fmt_num(x):
    return f"{x:,.0f}".replace(",", ".")


def fmt_money(x):
    """Nominal penuh: 170040123456789 -> 'Rp 170.040.123.456.789'."""
    return f"Rp {fmt_num(float(x or 0))}"


def fmt_pct(x):
    return f"{_id(f'{x:,.2f}')}%"


def fmt_status(code):
    return STATUS_LOAN_LABEL.get(str(code), str(code))


def fmt_bulan(m):
    try:
        return BULAN_LABEL.get(int(m), str(m))
    except (TypeError, ValueError):
        return str(m)


def fmt_tahun(y):
    try:
        return str(int(y))
    except (TypeError, ValueError):
        return str(y)


# ---------- Pipeline Excel ----------
def validate_columns(df):
    """Kembalikan daftar kolom wajib yang belum ada."""
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def prepare_data(raw):
    """Bersihkan tipe data: angka, bulan (angka/teks), tanggal, dan kolom teks."""
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for c in ("PLAFOND", "OUTSTANDING", BUNGA_COLUMN):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["TAHUN PENCAIRAN"] = pd.to_numeric(df["TAHUN PENCAIRAN"], errors="coerce")

    # Bulan bisa berupa angka (1-12) atau nama ("Jan", "Januari", "January").
    bulan = df["BULAN_PENCAIRAN"]
    df["BULAN_PENCAIRAN"] = pd.to_numeric(bulan, errors="coerce").fillna(
        bulan.astype(str).str.strip().str.lower().map(BULAN_TEXT_TO_NUM))

    # Tanggal: mendukung datetime, YYYYMMDD, nomor seri Excel, dan teks tanggal.
    tgl = df["TANGGAL_PENCAIRAN"]
    if pd.api.types.is_datetime64_any_dtype(tgl):
        parsed = tgl
    else:
        num = pd.to_numeric(tgl, errors="coerce")
        txt = tgl.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        is_ymd = txt.str.fullmatch(r"\d{8}")
        parsed = pd.to_datetime(txt.where(is_ymd), format="%Y%m%d", errors="coerce")
        serial = num.where(num.between(20000, 80000) & ~is_ymd)   # nomor seri tanggal Excel
        parsed = parsed.fillna(pd.to_datetime(serial, unit="D", origin="1899-12-30", errors="coerce"))
        parsed = parsed.fillna(pd.to_datetime(tgl.where(num.isna()), errors="coerce"))
    df["TANGGAL_PENCAIRAN"] = parsed.where(parsed >= "1980-01-01")  # tanggal tak masuk akal -> kosong

    # Kode seperti 1 bisa terbaca "1.0" kalau kolomnya ada sel kosong -> dirapikan jadi "1".
    for c in TEXT_COLUMNS:
        if c in df.columns:
            df[c] = (df[c].fillna("(Kosong)").astype(str).str.strip()
                     .str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True))
    return df


@st.cache_data(show_spinner=False)
def read_excel_bytes(file_bytes):
    return pd.read_excel(io.BytesIO(file_bytes))


# ---------- Database (opsional, import dilazy agar app tetap jalan tanpa driver DB) ----------
@st.cache_resource(show_spinner=False)
def get_engine():
    from sqlalchemy import create_engine
    c = DB_CONFIG
    url = f"postgresql+psycopg2://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{c['dbname']}"
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(show_spinner=False, ttl=60)
def check_db():
    """Return (ok, pesan_error)."""
    try:
        from sqlalchemy import text
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)


@st.cache_data(show_spinner=False, ttl=300)
def get_upload_batches():
    from sqlalchemy import text
    with get_engine().connect() as conn:
        return pd.read_sql(text("SELECT id, file_name, total_rows FROM upload_batches ORDER BY id DESC"), conn)


@st.cache_data(show_spinner=False, ttl=300)
def load_from_db(batch_id=None):
    """Ambil tabel `pencairan` (semua batch, atau satu batch) lalu bersihkan seperti jalur Excel."""
    from sqlalchemy import text
    sql, params = ("SELECT * FROM pencairan WHERE batch_id = :bid", {"bid": batch_id}) if batch_id \
        else ("SELECT * FROM pencairan", {})
    with get_engine().connect() as conn:
        raw = pd.read_sql(text(sql), conn, params=params)
    return prepare_data(raw.rename(columns=DB_COLUMN_TO_APP)) if not raw.empty else raw
