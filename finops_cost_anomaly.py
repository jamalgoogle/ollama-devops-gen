import numpy as np
import pandas as pd

# ---------- PART 1: cost anomaly detection ----------
rng = np.random.default_rng(42)                          # fixed seed = same data every run
days = pd.date_range("2026-10-01", periods=30, freq="D")
cost = rng.normal(100, 5, size=30)                       # normal cost: about $100 per day
cost[24] = 260                                           # a hidden problem on day 25
df = pd.DataFrame({"date": days, "service": "EC2", "cost": cost.round(2)})

# Compare each day with the average of the PREVIOUS 7 days
past = df["cost"].shift(1)                               # shift(1): do not include today
mean = past.rolling(7).mean()
std = past.rolling(7).std()
df["z_score"] = (df["cost"] - mean) / std                # how many "std" away from normal
spikes = df[df["z_score"] > 3]                           # more than 3 = very unusual
print("💸 Cost spikes:")
spikes = spikes.assign(z_score=spikes["z_score"].round(1))   # round only the number column
print(spikes[["date", "service", "cost", "z_score"]].to_string(index=False))

# ---------- PART 2: simple rightsizing ----------
fleet = pd.DataFrame({
    "instance": ["web-1", "web-2", "batch-1", "db-1"],
    "type": ["m5.2xlarge", "m5.2xlarge", "c5.4xlarge", "r5.xlarge"],
    "avg_cpu_14d": [6, 9, 71, 38],                       # average CPU % in 14 days
})
def advice(cpu):
    if cpu < 10:
        return "Too big: use a smaller type"
    if cpu > 70:
        return "Busy: check, maybe scale out"
    return "OK"
fleet["advice"] = fleet["avg_cpu_14d"].apply(advice)
print("\n📏 Rightsizing:")
print(fleet.to_string(index=False))
