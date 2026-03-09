import os
import re
import atexit
from datetime import datetime
from langchain_core.callbacks.base import BaseCallbackHandler

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
LOG_FILE  = os.path.join(os.path.dirname(__file__), "..", "session.log")
separator = "═" * 60
spacer    = "\n" * 3


# ─────────────────────────────────────────────
# Delete Log on Server Stop
# ─────────────────────────────────────────────
def delete_log_on_exit():
    try:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
            print("🌿 session log deleted.")
    except Exception as e:
        print(f"⚠️ Could not delete log: {e}")

atexit.register(delete_log_on_exit)


# ─────────────────────────────────────────────
# Log Interaction
# ─────────────────────────────────────────────
def log_interaction(
    user_question:    str,
    greenmind_answer: str,
    tools_used:       list[str],
    tool_logs:        list[str]
):
    # Strip markdown from answer for clean log
    clean_answer = re.sub(r'\*{1,3}', '', greenmind_answer)
    clean_answer = re.sub(r'#{1,6}\s', '', clean_answer)
    clean_answer = re.sub(r'`{1,3}', '', clean_answer)
    clean_answer = re.sub(r'_{1,2}', '', clean_answer)
    clean_answer = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_answer)
    clean_answer = re.sub(r'\n{3,}', '\n\n', clean_answer).strip()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(separator + "\n")
        for line in tool_logs:
            f.write(line + "\n")
        f.write(f"TIMESTAMP  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"QUESTION   : {user_question}\n")
        f.write(f"TOOLS USED : {', '.join(tools_used) if tools_used else 'None'}\n")
        f.write(f"ANSWER     : {clean_answer}\n")
        f.write(separator + "\n")
        f.write(spacer)


# ─────────────────────────────────────────────
# Callback Handler
# ─────────────────────────────────────────────
class GreenMindCallbackHandler(BaseCallbackHandler):

    def __init__(self):
        self.tools_used = []
        self.tool_logs  = []

    def reset(self):
        self.tools_used = []
        self.tool_logs  = []

    def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get("name", "unknown_tool")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.tools_used.append(tool_name)
        self.tool_logs.append(
            f"{timestamp} | INFO | TOOL CALLED  : {tool_name} | INPUT: {str(input_str)[:100]}"
        )

    def on_tool_end(self, output, **kwargs):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Extract clean text and remove \n
        clean = output.content if hasattr(output, "content") else str(output)
        clean = (str(clean)
                 .replace("\\n", " ")
                 .replace("\n", " ")
                 .replace("  ", " ")
                 .strip())
        self.tool_logs.append(
            f"{timestamp} | INFO | TOOL OUTPUT  : {clean[:200]}..."
        )

    def on_tool_error(self, error, **kwargs):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.tool_logs.append(
            f"{timestamp} | INFO | TOOL ERROR   : {str(error)[:200]}"
        )