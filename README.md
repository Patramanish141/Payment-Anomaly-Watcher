# Payments Anomaly Watcher

An automated agent that monitors daily payments metrics, detects unusual
movement, explains what changed in plain English, and emails an alert —
so an ops/analytics team doesn't have to manually check dashboards every
morning to catch problems.

Built around a payments/UPI-style domain (transactions, TPV, success rate,
failure rate, refunds, merchants) but the logic generalizes to any daily
business metrics feed.

## Why this project

Most beginner data projects stop at an EDA notebook — charts and
observations. This goes a step further: it behaves like a monitoring tool
a real ops team could run daily. It reads data, evaluates it against
recent history, explains anomalies in business language, and proactively
alerts — turning analysis into an automated system.

## Project structure

```
payments-anomaly-watcher/
├── src/
│   ├── generate_data.py
│   ├── watcher.py
│   └── alerts.py
├── data/
│   └── payments_daily.xlsx
├── .env                  # not committed -- holds email credentials
├── .gitignore
└── README.md
```

## How it works

1. **`src/generate_data.py`** — generates a synthetic 150-day daily payments
   dataset with realistic trend + weekly seasonality, plus 4 deliberately
   planted anomalies (an outage, a promotional spike, a slow quality
   decay, a refund spike) used to validate the detection logic.

2. **`src/watcher.py`**
   - `load_data()` — reads and validates the Excel file
   - `compute_movement()` — for every metric, computes % change vs a
     trailing 7-day and 30-day **median** baseline (median rather than
     mean so one extreme day doesn't distort the following week's
     comparisons)
   - `detect_anomalies()` — flags anomalies using two different rules
     depending on metric type:
     - **Rate metrics** (success rate, failure rate) are flagged on
       **absolute percentage-point movement**, since these are naturally
       small numbers where relative % change is misleading
     - **Volume metrics** (transactions, TPV, refunds, etc.) are flagged
       on **relative % change**, since these scale naturally
   - `group_into_episodes()` / `merge_into_incidents()` — collapse
     consecutive anomalous days, and multiple metrics anomalous on
     overlapping dates, into a single real-world incident (so a 5-day
     quality dip or a 4-metric outage produces one alert, not several)
   - `summarize()` — converts each incident into a plain-English
     business summary, with a light interpretive hint (e.g. "consistent
     with a service outage" when volume and success rate drop together)

3. **`src/alerts.py`**
   - Sends an email alert for any newly detected incident (via SMTP,
     credentials read from a `.env` file / environment variables — never
     hardcoded). Tries port 465 (SSL) first, falls back to 587
     (STARTTLS) if the network blocks it.
   - Keeps a persistent alert log (`data/alert_log.csv`) so the same
     incident is never alerted twice, and there's a full history of past
     alerts

## Running it

```bash
pip install pandas openpyxl numpy python-dotenv

python src/generate_data.py   # generates data/payments_daily.xlsx
python src/watcher.py         # computes movement, detects anomalies, prints summaries
python src/alerts.py          # sends email alerts + logs them
```

Run these from the project root (not from inside `src/`), since the
scripts read/write paths like `data/...` relative to where you run them.

To enable real email alerts, create a `.env` file in the project root
(see docstring in `src/alerts.py` for Gmail App Password setup):

```
ALERT_EMAIL_FROM=you@gmail.com
ALERT_EMAIL_APP_PASSWORD=your-16-char-app-password
ALERT_EMAIL_TO=you@gmail.com
```

Without this set, the pipeline still runs and logs anomalies — it just
skips sending the email, so it's safe to run and demo without setup.

## Known limitations

- A trailing baseline is still sensitive to unusual weeks even with a
  median; a production version would likely use a longer history or an
  explicit seasonality model.
- SMTP on ports 465/587 can be blocked by restrictive networks (seen on
  a college network during testing) — worked fine over a mobile
  hotspot. A production deployment would run from a server/cloud
  environment with reliable outbound access, or use an email API
  (e.g. SendGrid) instead of raw SMTP.

## Possible extensions

- Swap the rule-based summary for an LLM call to generate richer,
  more varied summaries
- Add a simple Streamlit dashboard to visualize metrics + flagged
  anomalies over time
- Support multiple recipients / Slack alerts instead of just email