import pandas as pd                      # tables (DataFrame) for data
from collections import Counter          # counts how many times a value appears
import re                                # regular expressions (text patterns)

log_file = "system_logs.txt"             # the log file from the repo

log_entries = []                         # empty list: we will fill it with rows
with open(log_file, "r") as file:        # open the file for reading
    for line in file:                    # read one line at a time
        # Pattern: date+time, then level (one word), then the message
        match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+) (.+)", line.strip())
        if match:                        # skip lines that do not match
            timestamp, level, message = match.groups()
            log_entries.append([timestamp, level, message])

# Make a table with 3 columns
df = pd.DataFrame(log_entries, columns=["timestamp", "level", "message"])
df["timestamp"] = pd.to_datetime(df["timestamp"])   # text -> real date/time
df = df.sort_values("timestamp")         # FIX: the file is not in time order

# Count ERROR lines inside each 30-second window.
# FIX: new pandas needs "30s" (small s). "30S" now raises an error.
error_counts = Counter(df[df["level"] == "ERROR"]["timestamp"].dt.floor("30s"))

threshold = 3                            # more than 3 errors in 30 seconds = anomaly

for time, count in sorted(error_counts.items()):    # sorted = print in time order
    if count > threshold:
        print(f"🚨 Anomaly detected! {count} ERROR logs in 30 seconds at {time}")

print("\nFull Log Analysis:")
print(df)                                # show the whole table
