"""Dashboard Pencairan - titik masuk aplikasi.  Jalankan:  streamlit run app.py"""
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
LOGO = BASE_DIR / "assets" / "logo.png"

load_dotenv(BASE_DIR / ".env")  # baca kredensial DB dari .env (opsional)
st.set_page_config(
    page_title="Dashboard Pencairan",
    page_icon=str(LOGO),
    layout="wide",
    initial_sidebar_state="auto",
)
if LOGO.exists():
    st.logo(str(LOGO), size="large")

import ui  # noqa: E402  (setelah set_page_config)
import views  # noqa: E402

PAGES = {
    "upload": views.page_upload,
    "processing": views.page_processing,
    "summary": views.page_summary,
    "dashboard": views.page_dashboard,
}


def main():
    ui.inject_css()
    st.session_state.setdefault("stage", "upload")
    PAGES.get(st.session_state.stage, views.page_upload)()


main()