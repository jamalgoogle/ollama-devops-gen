import pandas as pd                           # tables
import numpy as np                            # numbers (imported in the repo code)
from sklearn.ensemble import IsolationForest  # the machine learning model

log_file_path = "system_logs.txt"             # path to the log file
with open(log_file_path, "r") as file:
    logs = file.readlines()                   # read all lines into a list

data = []                                     # rows for the table
for log in logs:
    parts = log.strip().split(" ", 3)         # split into 4 parts: date, time, level, message
    if len(parts) < 4:
        continue                              # skip broken lines
    timestamp = parts[0] + " " + parts[1]     # join date + time
    level = parts[2]
    message = parts[3]
    data.append([timestamp, level, message])

df = pd.DataFrame(data, columns=["timestamp", "level", "message"])
df["timestamp"] = pd.to_datetime(df["timestamp"])   # text -> date/time

# Computers need numbers, so we turn each level into a score
level_mapping = {"INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
df["level_score"] = df["level"].map(level_mapping)

# Feature 2: how long is the message?
df["message_length"] = df["message"].apply(len)

# The AI model: expect about 10% of the logs to be strange
model = IsolationForest(contamination=0.1, random_state=42)   # fixed seed = same result each run
# fit_predict learns and answers in one step: -1 = anomaly, 1 = normal
df["anomaly"] = model.fit_predict(df[["level_score", "message_length"]])

# Make the result easy to read
df["is_anomaly"] = df["anomaly"].apply(lambda x: "❌ Anomaly" if x == -1 else "✅ Normal")

anomalies = df[df["is_anomaly"] == "❌ Anomaly"]    # keep only the strange rows
print("\n🔍 **Detected Anomalies:**\n", anomalies)
