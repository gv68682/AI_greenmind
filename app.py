
#Streamlit does not provide its own IDE.** It’s a **Python framework for building web apps*
#streamlit run app.py

# import streamlit as st
# st.title("Green Mind")
# st.write("Hello World!")


import streamlit as st
import random
rag1 = "docs/rag1.txt"
rag2 = "docs/rag2.txt"

from tools.rag import build_both_vectorstores
from tools.tools import build_tools
from main.llm import build_llm
from main.agent import build_agent
from tools.prompts import system_prompt_text
from main.log import log_interaction, GreenMindCallbackHandler

# ─────────────────────────────────────────────
# 1. Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="GreenMind 🌿",
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

    if not messages:
        return "⚠️ GreenMind could not generate a response. Please try again."

    last_message = messages[-1]

    print("DEBUG — Last message type :", type(last_message))
    print("DEBUG — Last message      :", last_message)
    print("DEBUG — Has content attr  :", hasattr(last_message, "content"))

    content = last_message.content if hasattr(last_message, "content") \
              else last_message.get("content", "")

    print("DEBUG — Content type      :", type(content))
    print("DEBUG — Content value     :", content)

    if isinstance(content, list):
        print("DEBUG — Content is LIST, items:")
        for i, m in enumerate(content):
            print(f"  [{i}] type={type(m)}, value={m}")
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
        print("DEBUG — Full agent result:")
        print(result)
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
#with st.spinner("🌱 GreenMind is loading knowledge base... please wait"):
# ─────────────────────────────────────────────
# Hide "Running..." Streamlit cache message
# ─────────────────────────────────────────────
# st.markdown("""
#     <style>
#     [data-testid="stStatusWidget"] { display: none; }
#     </style>
# """, unsafe_allow_html=True)
placeholder = st.empty()
placeholder.write("🌱 GreenMind is loading knowledge base... please wait")
agent_executor = load() 
placeholder.empty()
st.success("✅ GreenMind is ready!")

# ─────────────────────────────────────────────
# 6. Initialize Callback Handler           ✅
#    BEFORE session state & chat history
# ─────────────────────────────────────────────
callback_handler = GreenMindCallbackHandler()

# ─────────────────────────────────────────────
# 7. Session State
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "is_first_message" not in st.session_state:
    st.session_state.is_first_message = True

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

    with st.chat_message("assistant", avatar="🌿"):
        with st.spinner("🌱 GreenMind is thinking..."):

            callback_handler.reset()

             # ─────────────────────────────────
            # ✅ Tell agent if its first message
            # or a follow-up question
            # ─────────────────────────────────
            if st.session_state.is_first_message:
                full_prompt = prompt
                st.session_state.is_first_message = False
            else:
                full_prompt = (
                    f"[FOLLOW-UP QUESTION — DO NOT GREET — "
                    f"answer directly]: {prompt}"
                )


            MAX_RETRIES = 3
            response    = None

            for attempt in range(1, MAX_RETRIES + 1):
                from langchain_core.messages import ToolMessage
                result = agent_executor.invoke(
                    {"messages": [("user", full_prompt)]},
                    config={
                        "recursion_limit": 25,
                        "callbacks": [callback_handler]
                    }
                )

                messages = result.get("messages", [])

                tool_was_called = any(
                    isinstance(msg, ToolMessage)
                    for msg in messages
                )

                candidate = extract_response(result)

                if tool_was_called and candidate.strip():
                    response = candidate
                    break
                else:
                    print(f"DEBUG — Attempt {attempt}: No tool called, retrying...")
                    callback_handler.reset()
                    continue

            if not response:
                response = (
                    "🌿 I don't have enough information to "
                    "answer this accurately. Please try "
                    "rephrasing your question or ask about "
                    "a related environmental topic."
                )
            # Choose random quote and append to response
            random_quote = random.choice(quotes)
            response = response + f"\n\n🌿 *{random_quote}*"
            log_interaction(
                user_question=prompt,
                greenmind_answer=response,
                tools_used=callback_handler.tools_used,
                tool_logs=callback_handler.tool_logs
            )
        
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
