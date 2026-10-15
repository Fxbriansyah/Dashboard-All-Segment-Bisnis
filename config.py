"""Konstanta & konfigurasi dashboard. Edit di sini kalau ada kolom/segmen/warna baru."""
import os
from pathlib import Path

import plotly.express as px

BASE_DIR = Path(__file__).parent
CSS_PATH = BASE_DIR / "assets" / "style.css"

# Nama kolom NPL (nominal) di dashboard & Excel (cukup diubah di sini).
NPL_COLUMN = "NPL"

# Kolom WAJIB di file Excel.
REQUIRED_COLUMNS = [
    "PRODUCT_OWNER", "GROUP_PRODUCT", "PLAN_CODE", "JENIS_FASILITAS",
    "PLAFOND", "OUTSTANDING", "STATUS_LOAN", NPL_COLUMN,
    "TAHUN PENCAIRAN", "BULAN_PENCAIRAN", "TANGGAL_PENCAIRAN",
]
# Kolom di tabel detail (kolom identitas nasabah sengaja tidak ditampilkan).
SAFE_DETAIL_COLUMNS = [
    "PRODUCT_OWNER", "GROUP_PRODUCT", "PLAN_CODE", "JENIS_FASILITAS",
    "TAHUN PENCAIRAN", "BULAN_PENCAIRAN", "TANGGAL_PENCAIRAN",
    "PLAFOND", "OUTSTANDING", NPL_COLUMN, "STATUS_LOAN", "BRANCH_CODE",
]
TEXT_COLUMNS = ["PRODUCT_OWNER", "GROUP_PRODUCT", "PLAN_CODE", "JENIS_FASILITAS", "STATUS_LOAN", "BRANCH_CODE"]

# Urutan & tema segmen. Segmen yang tidak terdaftar otomatis ditaruh di belakang.
SEGMENT_ORDER = ["Retail & Micro Loan", "Supply Chain Financing", "Consumer", "SME Commercial"]
SEGMENT_THEME = {
    "Retail & Micro Loan":    {"icon": "👥", "color": "#2563eb", "bg": "#eff6ff", "border": "#bfdbfe"},
    "Supply Chain Financing": {"icon": "🔗", "color": "#059669", "bg": "#ecfdf5", "border": "#a7f3d0"},
    "Consumer":               {"icon": "🧑", "color": "#d97706", "bg": "#fffbeb", "border": "#fde68a"},
    "SME Commercial":         {"icon": "💼", "color": "#7c3aed", "bg": "#f5f3ff", "border": "#ddd6fe"},
}
DEFAULT_THEME = {"icon": "📁", "color": "#334155", "bg": "#f8fafc", "border": "#e2e8f0"}
PRODUCT_COLORS = px.colors.qualitative.Set2 + px.colors.qualitative.Pastel
BRAND, BRAND_LIGHT = "#1d4ed8", "#93c5fd"

BULAN_LABEL = {1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
               7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November", 12: "Desember"}
BULAN_TEXT_TO_NUM = {
    "januari": 1, "jan": 1, "january": 1, "februari": 2, "feb": 2, "february": 2,
    "maret": 3, "mar": 3, "march": 3, "april": 4, "apr": 4, "mei": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6, "juli": 7, "jul": 7, "july": 7,
    "agustus": 8, "agu": 8, "aug": 8, "august": 8, "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "oct": 10, "october": 10, "november": 11, "nov": 11,
    "desember": 12, "des": 12, "dec": 12, "december": 12,
}
# TODO: lengkapi nama untuk kode "7" dan "8". Kode yang tidak terdaftar tampil apa adanya.
STATUS_LOAN_LABEL = {"1": "Active", "2": "Lunas", "7": "7", "8": "8"}

STEPS = ["Upload data", "Validasi & proses", "Ringkasan", "Dashboard"]

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "dashboard_pencairan"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}
# Kolom tabel `pencairan` (snake_case) -> nama kolom yang dipakai dashboard.
DB_COLUMN_TO_APP = {
    "product_owner": "PRODUCT_OWNER", "group_product": "GROUP_PRODUCT", "plan_code": "PLAN_CODE",
    "jenis_fasilitas": "JENIS_FASILITAS", "plafond": "PLAFOND", "outstanding": "OUTSTANDING",
    "status_loan": "STATUS_LOAN", "tahun_pencairan": "TAHUN PENCAIRAN",
    "bulan_pencairan": "BULAN_PENCAIRAN", "tanggal_pencairan": "TANGGAL_PENCAIRAN",
    "branch_code": "BRANCH_CODE", "npl": NPL_COLUMN,
}