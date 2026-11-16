import pandas as pd
import ollama

MODEL = "llama3.1:8b"
LOG_FILE = "system_logs.txt"

# 1) Read + sort the logs (same as the clean-up step)
rows = [l.strip().split(" ", 3) for l in open(LOG_FILE) if len(l.split()) > 3]
df = pd.DataFrame(rows, columns=["date", "time", "level", "message"])
df["timestamp"] = pd.to_datetime(df["date"] + " " + df["time"])
df = df.sort_values("timestamp")

# 2) Pick only the important lines. LLMs have a size limit, so we cannot send 1000 lines.
important = df[df["level"].isin(["ERROR", "CRITICAL"])].head(60)   # first 60 bad lines
log_text = "\n".join(f"{r.timestamp} {r.level} {r.message}" for r in important.itertuples())

# 3) Count messages: a short summary of the whole file helps the AI
top = df["message"].value_counts().head(8).to_string()

prompt = f"""You are an SRE. Read the logs and answer in simple English.
1. Summary (3 lines)
2. Most likely root cause
3. Top 3 actions to fix it
If the data is not enough, say so. Do not invent facts.

Most common messages:
{top}

ERROR and CRITICAL logs:
{log_text}
"""

answer = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
print(answer["message"]["content"])
