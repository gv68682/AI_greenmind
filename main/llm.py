# ─────────────────────────────────────────────
# AFTER (Streamlit)
# ─────────────────────────────────────────────
import os
import streamlit as st
from main.config import GOOGLE_API_KEY

@st.cache_resource
def build_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        #model="gemini-2.0-flash",
        temperature=0.2,
        convert_system_message_to_human=True,
        model_kwargs={
            "thinking_config": {"thinking_budget": 0}  # ← disable thinking
        }
    )
    return llm