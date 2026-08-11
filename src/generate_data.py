"""
generate_data.py
Generates a synthetic daily payments dataset (like a simplified UPI/payments
ops feed) with realistic trend + weekly seasonality, plus a few deliberately
planted anomalies so we can test/demo detection later.

Columns:
    date               - calendar date
    total_transactions - count of transactions that day
    tpv                - total payment value (INR, in lakhs for readability)
    success_rate        - % of transactions that succeeded
    failure_rate        - % of transactions that failed (100 - success_rate - pending)
    avg_ticket_size     - average transaction value (INR)
    refunds             - count of refunds that day
    unique_merchants    - count of distinct merchants transacting
"""

import numpy as np
import pandas as pd

np.random.seed(42)

START_DATE = "2026-02-01"
NUM_DAYS = 150

dates = pd.date_range(start=START_DATE, periods=NUM_DAYS, freq="D")

# ---- Base trend: slow organic growth in transactions over time ----
day_idx = np.arange(NUM_DAYS)
base_txns = 500_000 + day_idx * 800  # gradual growth

# ---- Weekly seasonality: weekends slightly lower (people transacting less via merchants) ----
weekday = dates.dayofweek  # 0=Mon ... 6=Sun
weekend_dip = np.where(weekday >= 5, 0.92, 1.0)

# ---- Random daily noise ----
noise = np.random.normal(1.0, 0.02, NUM_DAYS)

total_transactions = (base_txns * weekend_dip * noise).astype(int)

# ---- TPV roughly tracks transactions * avg ticket size (with its own noise) ----
avg_ticket_size = np.random.normal(450, 15, NUM_DAYS)  # INR
tpv = (total_transactions * avg_ticket_size / 100000).round(2)  # in lakhs INR

# ---- Success rate: normally high and stable (~98%) ----
success_rate = np.random.normal(98.2, 0.3, NUM_DAYS)
success_rate = np.clip(success_rate, 90, 99.8)
failure_rate = (100 - success_rate - np.random.uniform(0.1, 0.3, NUM_DAYS)).round(2)

# ---- Refunds: small % of transactions ----
refunds = (total_transactions * np.random.normal(0.004, 0.0005, NUM_DAYS)).astype(int)

# ---- Unique merchants: grows slowly, correlated with transactions ----
unique_merchants = (150_000 + day_idx * 120 + np.random.normal(0, 800, NUM_DAYS)).astype(int)

df = pd.DataFrame({
    "date": dates,
    "total_transactions": total_transactions,
    "tpv": tpv,
    "success_rate": success_rate.round(2),
    "failure_rate": failure_rate,
    "avg_ticket_size": avg_ticket_size.round(2),
    "refunds": refunds,
    "unique_merchants": unique_merchants,
})

# =========================================================
# PLANT DELIBERATE ANOMALIES (so we can validate detection)
# =========================================================

# 1) Outage day: transactions crash, success rate tanks (day 45)
outage_day = 45
df.loc[outage_day, "total_transactions"] = int(df.loc[outage_day, "total_transactions"] * 0.35)
df.loc[outage_day, "success_rate"] = 62.0
df.loc[outage_day, "failure_rate"] = 36.5
df.loc[outage_day, "tpv"] = round(df.loc[outage_day, "total_transactions"] * df.loc[outage_day, "avg_ticket_size"] / 100000, 2)

# 2) Flash-sale / campaign spike: transactions & TPV spike, ticket size drops (day 80)
spike_day = 80
df.loc[spike_day, "total_transactions"] = int(df.loc[spike_day, "total_transactions"] * 1.8)
df.loc[spike_day, "avg_ticket_size"] = df.loc[spike_day, "avg_ticket_size"] * 0.7
df.loc[spike_day, "tpv"] = round(df.loc[spike_day, "total_transactions"] * df.loc[spike_day, "avg_ticket_size"] / 100000, 2)

# 3) Silent quality issue: success rate creeps down for a 5-day stretch, volume looks normal (days 110-114)
for d in range(110, 115):
    df.loc[d, "success_rate"] = df.loc[d, "success_rate"] - 4.5
    df.loc[d, "failure_rate"] = df.loc[d, "failure_rate"] + 4.5

# 4) Refund spike: possible fraud/merchant issue (day 130)
refund_spike_day = 130
df.loc[refund_spike_day, "refunds"] = int(df.loc[refund_spike_day, "refunds"] * 6)

out_path = "data/payments_daily.xlsx"
df.to_excel(out_path, index=False)
print(f"Saved {len(df)} rows to {out_path}")
print(f"Planted anomalies on day indices: {outage_day} (outage), {spike_day} (spike), 110-114 (quality dip), {refund_spike_day} (refund spike)")
print(df.iloc[[outage_day, spike_day, 130]])
