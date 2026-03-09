import streamlit as st
from langchain.agents import create_agent

@st.cache_resource   # ← ONLY CHANGE
def build_agent(_llm, _tools, system_prompt_text: str):
#               ↑
#underscore prefix tells Streamlit NOT to hash this argument (LLM objects are not hashable — will error without it)
    agent = create_agent(
        model=_llm,
        tools=_tools,
        system_prompt=system_prompt_text,
    )
    return agent

# @st.cache_resource → cache agent, built once reused across all reruns
