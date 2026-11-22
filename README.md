# School Reminder Bot — Setup Guide

Scans your parents' Gmail for school emails and sends them a nicely formatted reminder email automatically. 100% free.

---

## Step 1 — Install Python libraries

```
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client flask
```

---

## Step 2 — Gmail API Setup

1. Go to https://console.cloud.google.com
2. Click **New Project** → name it "School Reminder" → Create
3. Go to **APIs & Services → Library**
4. Search **Gmail API** → click it → Enable
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → OAuth client ID → Desktop app** → Create
7. Click **Download JSON** → rename it **credentials.json** → put it in the same folder as school_reminder.py

First time you run it, a browser window opens asking you to log into Gmail. Sign in with your parents' account. It saves a token.pickle file so it only asks once.

---

## Step 3 — Gmail App Password

You need this to SEND the reminder emails. It is NOT your real Gmail password.

1. Go to myaccount.google.com
2. Security → 2-Step Verification (turn this on if not already)
3. Security → App passwords
4. Select Mail → Generate
5. Copy the 16-character code (looks like: xxxx xxxx xxxx xxxx)

---

## Step 4 — Fill in school_reminder.py

Open school_reminder.py and fill in:

```python
SENDER_EMAIL    = 'your.email@gmail.com'      # the Gmail sending reminders
SENDER_PASSWORD = 'xxxx xxxx xxxx xxxx'       # the App Password from Step 3

PARENT_EMAILS = [
    'mum@gmail.com',
    'dad@gmail.com',
]
```

---

## Step 5 — Run it

```
python school_reminder.py
```

Open your browser at **http://localhost:5000**

Click **Scan Now** to do an instant scan, or wait 5 minutes for it to auto-scan.

---

## What the reminder email looks like

Your parents will get a clear, colour-coded email like:

```
⚠️ School Action Needed: 💰 Payment Required — Trip to Science Centre

From: HDSB Communications · Mon 18 Mar

Amount Due: $45
Deadline: March 22

[Preview of the original email...]

Check your email inbox for the full message.
```

---

## What it detects

- 💰 Payments and fees
- 🏆 Competition registrations
- ✏️ Permission forms
- ⚽ Club sign-ups
- 📋 Parent meetings and report cards
- 📢 General school notices

---

## GitHub

New repo called: school-reminder-bot

Add a .gitignore file with:
```
credentials.json
token.pickle
processed_emails.json
__pycache__/
```

Never upload credentials.json or token.pickle — they contain private login info!
