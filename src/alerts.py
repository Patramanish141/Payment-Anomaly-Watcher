"""
alerts.py
Day 3: sends an email alert when anomalies are detected, and keeps a
persistent log of every alert ever sent (so there's history to show,
and so we don't spam the same alert twice).

Credentials are read from environment variables -- NEVER hardcode them,
and never commit a .env file to git.

Setup (Gmail example):
  1. Enable 2-Step Verification on the sending Gmail account.
  2. Create an "App Password" (Google Account -> Security -> App Passwords).
  3. Set environment variables before running:
       Windows (PowerShell):
         $env:ALERT_EMAIL_FROM="youraddress@gmail.com"
         $env:ALERT_EMAIL_APP_PASSWORD="16-char-app-password"
         $env:ALERT_EMAIL_TO="youraddress@gmail.com"
       Mac/Linux:
         export ALERT_EMAIL_FROM="youraddress@gmail.com"
         export ALERT_EMAIL_APP_PASSWORD="16-char-app-password"
         export ALERT_EMAIL_TO="youraddress@gmail.com"
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads .env file in the current directory, if present
except ImportError:
    pass  # dotenv not installed -- env vars can still be set manually in the shell

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

ALERT_LOG_PATH = "data/alert_log.csv"


def send_email_alert(subject: str, body: str) -> bool:
    """
    Sends an email using credentials from environment variables.
    Returns True if sent successfully, False otherwise (never crashes
    the pipeline just because email failed).
    """
    sender = os.environ.get("ALERT_EMAIL_FROM")
    password = os.environ.get("ALERT_EMAIL_APP_PASSWORD")
    recipient = os.environ.get("ALERT_EMAIL_TO")

    if not all([sender, password, recipient]):
        print("Email not sent: missing ALERT_EMAIL_FROM / ALERT_EMAIL_APP_PASSWORD / ALERT_EMAIL_TO env vars.")
        print("(This is expected if you haven't set them up yet -- see alerts.py docstring.)")
        return False

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"Email alert sent to {recipient}")
        return True
    except Exception as e:
        print(f"Email failed to send: {e}")
        return False


def load_alert_log() -> pd.DataFrame:
    """Load existing alert log, or create an empty one if it doesn't exist yet."""
    if os.path.exists(ALERT_LOG_PATH):
        return pd.read_csv(ALERT_LOG_PATH, parse_dates=["anomaly_date", "alert_sent_at"])
    return pd.DataFrame(columns=["anomaly_date", "summary", "alert_sent_at", "email_sent"])


def already_alerted(anomaly_date: str, log: pd.DataFrame) -> bool:
    """Check if we've already logged an alert for this date, so we don't spam duplicates."""
    if log.empty:
        return False
    return (log["anomaly_date"].dt.strftime("%Y-%m-%d") == anomaly_date).any()


def process_alerts(summaries: dict, send_email: bool = True) -> pd.DataFrame:
    """
    Given the {date: summary_text} dict from watcher.summarize(), send an
    email for any NEW anomaly day (not already logged) and append it to
    the persistent alert log.
    """
    log = load_alert_log()
    new_rows = []

    for date, summary_text in summaries.items():
        if already_alerted(date, log):
            continue  # already alerted on this day before, skip

        email_sent = False
        if send_email:
            subject = f"[Payments Watcher] Anomaly detected - {date}"
            email_sent = send_email_alert(subject, summary_text)

        new_rows.append({
            "anomaly_date": date,
            "summary": summary_text,
            "alert_sent_at": datetime.now(),
            "email_sent": email_sent,
        })

    if new_rows:
        new_log = pd.concat([log, pd.DataFrame(new_rows)], ignore_index=True)
        new_log.to_csv(ALERT_LOG_PATH, index=False)
        print(f"\nLogged {len(new_rows)} new alert(s) to {ALERT_LOG_PATH}")
    else:
        print("\nNo new anomalies to alert on (all already logged).")

    return load_alert_log()


if __name__ == "__main__":
    from watcher import load_data, compute_movement, detect_anomalies, summarize

    df = load_data("data/payments_daily.xlsx")
    df_movement = compute_movement(df)
    anomalies = detect_anomalies(df_movement)
    summaries = summarize(anomalies)

    print(f"Processing {len(summaries)} anomaly day(s)...\n")
    log = process_alerts(summaries, send_email=True)

    print("\n=== Full Alert Log ===")
    print(log.to_string(index=False))