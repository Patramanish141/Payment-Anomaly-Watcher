"""
watcher.py
Step 2: load the payments Excel file, clean it, and compute how each metric
is moving today vs. its recent trailing baseline (7-day and 30-day average).

This is the foundation the anomaly detector (Day 2) will build on top of.
"""

import pandas as pd

METRICS = [
    "total_transactions",
    "tpv",
    "success_rate",
    "failure_rate",
    "avg_ticket_size",
    "refunds",
    "unique_merchants",
]

SHORT_WINDOW = 7   # trailing days for "recent" baseline
LONG_WINDOW = 30    # trailing days for "normal" baseline


def load_data(path: str) -> pd.DataFrame:
    """Read the Excel file and do basic cleaning/validation."""
    df = pd.read_excel(path)

    # Basic validation
    required_cols = {"date", *METRICS}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing expected columns: {missing}")

    # Ensure correct dtype and sort chronologically
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Handle missing values: forward-fill small gaps, flag if too many
    null_counts = df[list(METRICS)].isnull().sum()
    if null_counts.sum() > 0:
        print(f"Warning: found nulls, forward-filling -> {null_counts[null_counts > 0].to_dict()}")
        df[list(METRICS)] = df[list(METRICS)].ffill()

    return df


def compute_movement(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each metric, compute trailing 7-day and 30-day rolling averages
    (excluding the current day, so we're comparing "today vs recent normal")
    and the % change of today's value against each baseline.
    """
    df = df.copy()

    for metric in METRICS:
        # shift(1) so the rolling window is the days BEFORE today, not including today.
        # median (not mean) so a single extreme day doesn't drag the baseline off course
        # for the following week.
        roll_short = df[metric].shift(1).rolling(window=SHORT_WINDOW, min_periods=3).median()
        roll_long = df[metric].shift(1).rolling(window=LONG_WINDOW, min_periods=10).median()

        df[f"{metric}_baseline_7d"] = roll_short
        df[f"{metric}_baseline_30d"] = roll_long

        df[f"{metric}_pct_change_7d"] = ((df[metric] - roll_short) / roll_short) * 100
        df[f"{metric}_pct_change_30d"] = ((df[metric] - roll_long) / roll_long) * 100

    return df


# =========================================================
# Day 2: anomaly detection + plain-English summaries
# =========================================================

# Metrics fall into two families that need different anomaly rules:
#
# 1) "Rate" metrics (success_rate, failure_rate) are small numbers (~1-2%).
#    % change of a small number is unstable -- a move from 1.5% to 1.9% is a
#    harmless wobble but shows up as +27% relative change. For these we flag
#    based on ABSOLUTE percentage-point movement instead.
RATE_METRICS_ABS_THRESHOLD = {
    "success_rate": 3.0,   # flag if success_rate moves 3+ points vs baseline
    "failure_rate": 3.0,   # flag if failure_rate moves 3+ points vs baseline
}

# 2) "Volume" metrics -- flagged using relative % change vs 7-day baseline,
#    since these naturally scale and a % move is meaningful.
THRESHOLDS = {
    "total_transactions": 25,
    "tpv": 25,
    "avg_ticket_size": 15,
    "refunds": 50,
    "unique_merchants": 15,
}

# Human-readable labels + direction hints, used when building the summary sentence
METRIC_LABELS = {
    "total_transactions": "transaction volume",
    "tpv": "total payment value (TPV)",
    "success_rate": "success rate",
    "failure_rate": "failure rate",
    "avg_ticket_size": "average ticket size",
    "refunds": "refunds",
    "unique_merchants": "unique merchants transacting",
}


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scan every day and flag which metrics moved beyond their threshold
    vs the 7-day baseline. Returns one row per (date, metric) anomaly found.
    """
    records = []

    for _, row in df.iterrows():
        # --- rate metrics: absolute percentage-point move vs 7-day baseline ---
        for metric, abs_threshold in RATE_METRICS_ABS_THRESHOLD.items():
            baseline = row.get(f"{metric}_baseline_7d")
            if pd.isna(baseline):
                continue
            point_change = row[metric] - baseline
            if abs(point_change) >= abs_threshold:
                pct_change = row.get(f"{metric}_pct_change_7d")
                records.append({
                    "date": row["date"],
                    "metric": metric,
                    "value": row[metric],
                    "baseline_7d": baseline,
                    "pct_change_7d": round(pct_change, 2) if pd.notna(pct_change) else None,
                    "point_change_7d": round(point_change, 2),
                    "direction": "up" if point_change > 0 else "down",
                    "severity": round(abs(point_change) / abs_threshold, 2),
                })

        # --- volume metrics: relative % change vs 7-day baseline ---
        for metric, threshold in THRESHOLDS.items():
            pct_change = row.get(f"{metric}_pct_change_7d")
            if pd.isna(pct_change):
                continue  # not enough history yet (early rows)

            if abs(pct_change) >= threshold:
                records.append({
                    "date": row["date"],
                    "metric": metric,
                    "value": row[metric],
                    "baseline_7d": row[f"{metric}_baseline_7d"],
                    "pct_change_7d": round(pct_change, 2),
                    "point_change_7d": None,
                    "direction": "up" if pct_change > 0 else "down",
                    "severity": round(abs(pct_change) / threshold, 2),  # >1 = beyond threshold, higher = worse
                })

    anomalies = pd.DataFrame(records)
    if not anomalies.empty:
        anomalies = anomalies.sort_values(["date", "severity"], ascending=[True, False]).reset_index(drop=True)
    return anomalies


def group_into_episodes(anomalies: pd.DataFrame, gap_days: int = 2) -> pd.DataFrame:
    """
    Collapse consecutive/near-consecutive anomaly days for the SAME metric
    into a single episode, so one real event (e.g. a multi-day quality dip)
    produces one alert instead of one per day. Two flagged days for the
    same metric are merged if they're within `gap_days` of each other.
    """
    if anomalies.empty:
        return anomalies

    anomalies = anomalies.sort_values(["metric", "date"]).reset_index(drop=True)
    episode_id = 0
    episode_ids = []
    prev_metric = None
    prev_date = None

    for _, row in anomalies.iterrows():
        if row["metric"] != prev_metric or (row["date"] - prev_date).days > gap_days:
            episode_id += 1
        episode_ids.append(episode_id)
        prev_metric = row["metric"]
        prev_date = row["date"]

    anomalies = anomalies.copy()
    anomalies["episode_id"] = episode_ids

    # Represent each episode by its most severe day, but keep the date range too
    reps = []
    for _, group in anomalies.groupby("episode_id"):
        top = group.loc[group["severity"].idxmax()].copy()
        top["episode_start"] = group["date"].min()
        top["episode_end"] = group["date"].max()
        reps.append(top)

    result = pd.DataFrame(reps).sort_values("date").reset_index(drop=True)
    return result


    result = pd.DataFrame(reps).sort_values("date").reset_index(drop=True)
    return result


def merge_into_incidents(episodes: pd.DataFrame, gap_days: int = 2) -> list:
    """
    Merge per-metric episodes into incidents: if two episodes (possibly on
    different metrics) overlap in time or are within `gap_days` of each
    other, treat them as the same real-world event (e.g. an outage hitting
    transactions, TPV, success rate and failure rate all at once). Returns
    a list of DataFrames, one per incident.
    """
    if episodes.empty:
        return []

    episodes = episodes.sort_values("episode_start").reset_index(drop=True)
    incidents = []
    current = [episodes.iloc[0]]
    current_end = episodes.iloc[0]["episode_end"]

    for i in range(1, len(episodes)):
        row = episodes.iloc[i]
        if (row["episode_start"] - current_end).days <= gap_days:
            current.append(row)
            current_end = max(current_end, row["episode_end"])
        else:
            incidents.append(pd.DataFrame(current))
            current = [row]
            current_end = row["episode_end"]

    incidents.append(pd.DataFrame(current))
    return incidents


def summarize(anomalies: pd.DataFrame) -> dict:
    """
    Group anomalies into real-world incidents (merging consecutive days AND
    overlapping metrics into one event) and turn each incident into a
    plain-English business summary. Returns {representative_date: summary_text}.
    """
    episodes = group_into_episodes(anomalies)
    incidents = merge_into_incidents(episodes)

    summaries = {}
    for group in incidents:
        group = group.sort_values("severity", ascending=False)
        parts = []
        for _, r in group.iterrows():
            label = METRIC_LABELS[r["metric"]]
            verb = "rose" if r["direction"] == "up" else "dropped"
            if r["metric"] in RATE_METRICS_ABS_THRESHOLD:
                parts.append(f"{label} {verb} sharply "
                             f"({r['point_change_7d']:+.1f} points vs recent average)")
            else:
                parts.append(f"{label} {verb} sharply "
                             f"({r['pct_change_7d']:+.1f}% vs recent average)")

        sentence = "; ".join(parts)

        # Add a light interpretive hint based on which combination of metrics moved
        metrics_hit = set(group["metric"])
        hint = ""
        if {"total_transactions", "success_rate"}.issubset(metrics_hit) and \
           group.loc[group["metric"] == "total_transactions", "direction"].iloc[0] == "down" and \
           group.loc[group["metric"] == "success_rate", "direction"].iloc[0] == "down":
            hint = " This pattern is consistent with a service outage or payment gateway issue."
        elif {"total_transactions", "avg_ticket_size"}.issubset(metrics_hit) and \
             group.loc[group["metric"] == "total_transactions", "direction"].iloc[0] == "up":
            hint = " This looks like a promotional spike (higher volume, smaller average transactions)."
        elif metrics_hit == {"failure_rate"} or metrics_hit == {"success_rate"} or \
             metrics_hit == {"success_rate", "failure_rate"}:
            hint = " Volume looks normal, so this may be a quieter quality issue worth investigating before it grows."
        elif metrics_hit == {"refunds"}:
            hint = " Worth checking if this is tied to a specific merchant or a fraud pattern."

        start = pd.Timestamp(group["episode_start"].min()).strftime("%Y-%m-%d")
        end = pd.Timestamp(group["episode_end"].max()).strftime("%Y-%m-%d")
        date_range = start if start == end else f"{start} to {end}"

        date_str = start  # used as the dict key / representative date
        summaries[date_str] = f"On {date_range}: {sentence}.{hint}"

    return summaries


if __name__ == "__main__":
    df = load_data("data/payments_daily.xlsx")
    print(f"Loaded {len(df)} rows from {df['date'].min().date()} to {df['date'].max().date()}")

    df_movement = compute_movement(df)

    # quick sanity check: print movement on our known anomaly days
    check_days = [45, 80, 112, 130]
    pct_cols = [f"{m}_pct_change_7d" for m in METRICS]
    print("\nSample movement (% change vs trailing 7-day avg) on known anomaly days:")
    preview = df_movement.loc[check_days, ["date"] + pct_cols].copy()
    preview[pct_cols] = preview[pct_cols].round(2)
    print(preview.to_string(index=False))

    df_movement.to_csv("data/payments_with_movement.csv", index=False)
    print("\nSaved full movement table to data/payments_with_movement.csv")

    # ---- Day 2: detect anomalies + summarize ----
    anomalies = detect_anomalies(df_movement)
    print(f"\nDetected {len(anomalies)} metric-level anomalies across {anomalies['date'].nunique()} days")
    print(anomalies.to_string(index=False))

    anomalies.to_csv("data/anomalies_detected.csv", index=False)
    print("\nSaved anomaly log to data/anomalies_detected.csv")

    summaries = summarize(anomalies)
    print("\n=== Business Summaries ===")
    for date, text in summaries.items():
        print(f"\n{text}")