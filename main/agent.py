import streamlit as st

@st.cache_resource
def build_agent(_llm, _tools, system_prompt_text: str):
    from langchain.agents import create_agent

    agent = create_agent(
        model=_llm,
        tools=_tools,
        system_prompt=system_prompt_text
    )
    return agent