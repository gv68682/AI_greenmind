import time
import streamlit as st
import random
import re
rag1 = "docs/rag1.txt"
rag2 = "docs/rag2.txt"

from tools.rag import build_both_vectorstores
from tools.tools import build_tools
from main.llm import build_llm
from main.agent import build_agent
from tools.prompts import system_prompt_text
from main.log import log_interaction, GreenMindCallbackHandler
from langchain_core.messages import ToolMessage

# ─────────────────────────────────────────────
# 1. Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="GreenMind",
    page_icon="🌿",
    layout="centered"
)

# ─────────────────────────────────────────────
# 2. Cache Heavy Resources
# ─────────────────────────────────────────────
@st.cache_resource
def load():
    vectordb_1, vectordb_2 = build_both_vectorstores(rag1, rag2)
    tools          = build_tools(vectordb_1, vectordb_2)
    llm            = build_llm()
    agent_executor = build_agent(llm, tools, system_prompt_text)
    return agent_executor


# ─────────────────────────────────────────────
# Load quotes once at startup
# ─────────────────────────────────────────────
def load_quotes() -> list[str]:
    with open("docs/quotes.txt", "r", encoding="utf-8") as f:
        content = f.read()
    quotes = [q.strip() for q in content.split('"') if q.strip()]
    return quotes

quotes = load_quotes()


# ─────────────────────────────────────────────
# 3. Helper — Extract Response
# ─────────────────────────────────────────────
def extract_response(result: dict) -> str:
    messages = result.get("messages", [])
    # In extract_response() — add after messages = result.get("messages", [])
    print("DEBUG — total messages:", len(messages))
    for i, msg in enumerate(messages):
        content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
        print(f"DEBUG — msg[{i}] FULL content: {str(content)[:300]}")
        # print("DEBUG — msg[4] full content:", messages[4].content)
        # print("DEBUG — msg[4] type of content:", type(messages[4].content))

    if not messages:
        return "⚠️ GreenMind could not generate a response. Please try again."

    last_message = messages[-1]

    content = last_message.content if hasattr(last_message, "content") \
              else last_message.get("content", "")

    if isinstance(content, list):
        text_parts = [
            m["text"] for m in content
            if isinstance(m, dict) and m.get("type") == "text"
        ]
        final_text = " ".join(text_parts)

    elif isinstance(content, str):
        final_text = content

    else:
        final_text = str(content)

    print("DEBUG — Final text :", final_text[:200] if final_text else "EMPTY")

    if not final_text.strip():
        return "⚠️ GreenMind received the data but could not formulate a response. Please try again."

    return final_text


# ─────────────────────────────────────────────
# 4. UI Header
# ─────────────────────────────────────────────
st.title("🌿 GreenMind")
st.caption("Your Environmental Intelligence Assistant")
st.divider()

# ─────────────────────────────────────────────
# 5. Build on App Startup
# ─────────────────────────────────────────────
placeholder = st.empty()
placeholder.write("🌱 GreenMind is loading knowledge base... please wait")
agent_executor = load()
placeholder.empty()
st.success("🌍 Welcome!! Grateful to have you here for Earth.")

# ─────────────────────────────────────────────
# 7. Session State
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "is_first_message" not in st.session_state:
    st.session_state.is_first_message = True

# ─────────────────────────────────────────────
# 6. Initialize Callback Handler
# ─────────────────────────────────────────────
callback_handler = GreenMindCallbackHandler()

# ─────────────────────────────────────────────
# Display chat history
# ─────────────────────────────────────────────
for message in st.session_state.messages:
    avatar = "👤" if message["role"] == "user" else "🌿"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# ─────────────────────────────────────────────
# 9. Chat Input + Agent Invoke
# ─────────────────────────────────────────────
if prompt := st.chat_input("Ask GreenMind about the environment..."):

    if not prompt.strip():
        st.warning("Please type a question.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    # ─────────────────────────────────────────────
    # Variables outside spinner
    # ─────────────────────────────────────────────
    error_message = None
    response      = None

    with st.chat_message("assistant", avatar="🌿"):
        with st.spinner("🌱 GreenMind is thinking..."):

            callback_handler.reset()

            # ─────────────────────────────────
            # First message or follow-up
            # ─────────────────────────────────
            greeting_words = [
                "hi", "hello", "hey", "good morning",
                "good evening", "howdy", "hi!", "hi,",
                "hello!", "hello,"
            ]

            if st.session_state.is_first_message:
                full_prompt = prompt
                if prompt.strip().lower() not in greeting_words:
                    st.session_state.is_first_message = False
            else:
                full_prompt = (
                    f"[FOLLOW-UP QUESTION — DO NOT GREET — "
                    f"answer directly]: {prompt}"
                )

            # ─────────────────────────────────
            # Greeting handler
            # ─────────────────────────────────
            if prompt.strip().lower() in greeting_words:
                response = "Hello! Ask me anything about pollution, climate, biodiversity, or environmental policies!"

            else:
                # ─────────────────────────────────
                # Agent invoke with retry on 429
                # ─────────────────────────────────
                result = None

                for attempt in range(1, 3):
                    try:
                        result = agent_executor.invoke(
                            {"messages": [("user", full_prompt)]},
                            config={
                                "recursion_limit": 25,
                                "callbacks": [callback_handler]
                            }
                        )
                        break  # success — exit retry loop
                    except Exception as e:
                        print(f"DEBUG — Exception type: {type(e).__name__}")
                        print(f"DEBUG — Exception message: {str(e)}")
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            error_message = "⚠️ We're a bit busy right now. Please try again shortly."
                        else:
                            error_message = "⚠️ Something went wrong. Please try again."
                        break

                # ─────────────────────────────────
                # Process result — only if no error
                # ─────────────────────────────────
                if not error_message:

                    if result is None:
                        error_message = "⚠️ No response generated. Please try again."

                    else:
                        messages = result.get("messages", [])

                        tool_was_called = any(
                            isinstance(msg, ToolMessage)
                            for msg in messages
                        )

                        candidate = extract_response(result)
                        candidate = candidate.strip().lstrip("🌿").strip()

                        opener_pattern = r'^GreenMind (is happy to|is here to|is delighted to|is excited to)\s+\S+.*?\n+'
                        candidate = re.sub(opener_pattern, '', candidate, flags=re.IGNORECASE).strip()

                        out_of_scope_phrases = [
                            "GreenMind focuses on environmental health",
                            "GreenMind is dedicated solely to environmental topics",
                            "I'd recommend checking weather.com"
                        ]

                        is_out_of_scope = any(
                            phrase in candidate for phrase in out_of_scope_phrases
                        )

                        if is_out_of_scope or (tool_was_called and candidate.strip()):
                            response = candidate
                        elif candidate.strip() and len(candidate) > 50:
                            response = candidate
                        else:
                            response = (
                                "I don't have enough information to "
                                "answer this accurately. Please try "
                                "rephrasing your question or ask about "
                                "a related environmental topic."
                            )

                # ─────────────────────────────────
                # Append quote + log if no error
                # ─────────────────────────────────
                if response:
                    random_quote = random.choice(quotes)
                    response = response + f"\n\n🌍 *{random_quote}*"
                    log_interaction(
                        user_question=prompt,
                        greenmind_answer=response,
                        tools_used=callback_handler.tools_used,
                        tool_logs=callback_handler.tool_logs
                    )

        # ─────────────────────────────────
        # ← OUTSIDE spinner
        # Show error OR response
        # ─────────────────────────────────
        if error_message:
            st.warning(error_message)
        elif response:
            st.markdown(response)
            st.session_state.messages.append(
                {"role": "assistant", "content": response}
            )