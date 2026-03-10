# main/config.py
import os

def get_api_key():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    import streamlit as st
    return os.getenv("GOOGLE_API_KEY") or st.secrets.get("GOOGLE_API_KEY")

GOOGLE_API_KEY = get_api_key()