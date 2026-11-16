import re
import pandas as pd
from sklearn.ensemble import IsolationForest

LOG_FILE = "system_logs.txt"

# 1) Read and parse -------------------------------------------------------------
pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+) (.+)")
rows = []
with open(LOG_FILE) as f:
    for line in f:
        m = pattern.match(line.strip())
        if m:
            rows.append(m.groups())
df = pd.DataFrame(rows, columns=["timestamp", "level", "message"])
df["timestamp"] = pd.to_datetime(df["timestamp"])
df = df.sort_values("timestamp").reset_index(drop=True)     # 2) put logs in time order

# 3) Fix wrong levels: the message tells us how serious it REALLY is ------------
ERROR_WORDS = ["failed", "failure", "unreachable", "deadlock", "unhandled", "unauthorized", "exceeded threshold"]
WARN_WORDS = ["cpu usage", "low", "latency", "high", "slow", "rate limit", "restarted", "brute force"]

def expected_level(message):
    text = message.lower()
    if any(w in text for w in ERROR_WORDS):
        return "ERROR"
    if any(w in text for w in WARN_WORDS):
        return "WARNING"
    return "INFO"

df["expected_level"] = df["message"].apply(expected_level)
score = {"INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
df["level_score"] = df["level"].map(score)
# Use the higher one: the written level or the level from the message words
df["real_score"] = df[["level_score", "expected_level"]].apply(
    lambda r: max(r["level_score"], score[r["expected_level"]]), axis=1)

# 4) Better features -------------------------------------------------------------
df["is_bad"] = (df["real_score"] >= 3).astype(int)                      # 1 = ERROR or CRITICAL
df = df.set_index("timestamp")
df["bad_last_minute"] = df["is_bad"].rolling("60s").sum()               # bad lines in last 60 s
df = df.reset_index()
df["message_length"] = df["message"].str.len()

# 5) Train the model ------------------------------------------------------------------
features = df[["real_score", "bad_last_minute", "message_length"]]
model = IsolationForest(contamination=0.05, random_state=42)
df["anomaly"] = model.fit_predict(features)

print("Total logs  :", len(df))
print("Wrong levels:", int((df["level_score"] < df["real_score"]).sum()), "(raised after cleaning)")
print("Anomalies   :", int((df["anomaly"] == -1).sum()))
print(df[df["anomaly"] == -1][["timestamp", "level", "message", "bad_last_minute"]].head(8).to_string(index=False))
