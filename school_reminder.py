"""
School Email Reminder Bot — Full Version
=========================================
PWA + Gmail Scanner + Instant Reminders + Daily Digest

SETUP:
------
1. pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client flask

2. Gmail API credentials:
   - console.cloud.google.com -> New Project -> Enable Gmail API
   - Credentials -> OAuth client ID -> Desktop app -> Download as credentials.json
   - Put credentials.json in this folder

3. Gmail App Password:
   - myaccount.google.com -> Security -> 2-Step Verification -> App passwords
   - Generate for Mail -> copy 16-char code

4. Fill in config below

5. python school_reminder.py

6. Open http://localhost:5000
   - Run ngrok (ngrok.com, free) to share with parents' phones:
     ngrok http 5000
   - Share the https URL -> parents open on phone -> Add to Home Screen
"""

import os, json, base64, re, time, pickle, threading, smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, jsonify, render_template_string, Response

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ═══════════════════════════════════════════════
#  FILL THESE IN BEFORE RUNNING
# ═══════════════════════════════════════════════

SENDER_EMAIL    = 'your.email@gmail.com'   # Gmail that SENDS reminders
SENDER_PASSWORD = 'xxxx xxxx xxxx xxxx'   # Gmail App Password (NOT real password)

PARENT_EMAILS = [
    'mum@gmail.com',   # Mum
    'dad@gmail.com',   # Dad (delete line if only one parent)
]

DIGEST_HOUR   = 8    # Hour to send daily digest (8 = 8:00am)
DIGEST_MINUTE = 0    # Minute (0 = on the hour)
CHECK_INTERVAL = 300 # Scan every 300 seconds (5 minutes)

# ═══════════════════════════════════════════════
#  KEYWORDS & SENDERS
# ═══════════════════════════════════════════════

SCHOOL_KEYWORDS = [
    'payment due','fee','invoice','outstanding balance','pay by',
    'payment required','tuition','school fees','trip payment',
    'permission form','permission slip','field trip','excursion',
    'sign and return','please sign','competition','tournament',
    'registration','register by','deadline','sign up by',
    'club registration','extracurricular','after school','tryouts',
    'parent meeting','interview','report card','progress report',
    'fundraiser','pizza day','hot lunch','spirit day','school photo',
    'volunteer','donation','emergency contact','bus','early dismissal',
    'pa day','march break','schedule change','substitute',
]

SCHOOL_SENDERS = ['hdsb.ca','school.ca','.edu','schoolmessenger','edsby','scholastic']

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# ═══════════════════════════════════════════════
#  GMAIL CONNECTION
# ═══════════════════════════════════════════════

def get_gmail_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle','rb') as f: creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("\nERROR: credentials.json not found! See setup instructions.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle','wb') as f: pickle.dump(creds, f)
    return build('gmail','v1',credentials=creds)

def get_body(message):
    body = ''
    if 'parts' in message['payload']:
        for part in message['payload']['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data','')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8',errors='ignore')
                    break
    elif 'body' in message['payload']:
        data = message['payload']['body'].get('data','')
        if data:
            body = base64.urlsafe_b64decode(data).decode('utf-8',errors='ignore')
    return body[:3000]

# ═══════════════════════════════════════════════
#  EMAIL CLASSIFICATION
# ═══════════════════════════════════════════════

def extract_deadline(text):
    for p in [
        r'due\s+(?:by\s+)?([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)',
        r'deadline[:\s]+([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)',
        r'by\s+((?:Monday|Tuesday|Wednesday|Thursday|Friday|January|February|March|April|May|June|July|August|September|October|November|December)\s*\d*)',
        r'before\s+([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)',
    ]:
        m = re.search(p, text, re.IGNORECASE)
        if m: return m.group(1).strip()
    return None

def extract_amount(text):
    m = re.search(r'\$\s*(\d+(?:\.\d{2})?)', text)
    return f"${m.group(1)}" if m else None

def classify(subject, body, sender):
    text = (subject+' '+body+' '+sender).lower()
    is_school = any(d in sender.lower() for d in SCHOOL_SENDERS)
    matched = [kw for kw in SCHOOL_KEYWORDS if kw in text]
    if not matched and not is_school: return None
    if any(k in text for k in ['payment','fee','invoice','pay','balance','$']):
        return {'category':'Payment Required','emoji':'💰','color':'#e07a5f','keywords':matched[:4]}
    if any(k in text for k in ['competition','tournament','register']):
        return {'category':'Competition / Registration','emoji':'🏆','color':'#3d405b','keywords':matched[:4]}
    if any(k in text for k in ['permission','trip','excursion']):
        return {'category':'Permission Form Required','emoji':'✏️','color':'#e9a800','keywords':matched[:4]}
    if any(k in text for k in ['club','extracurricular','tryouts']):
        return {'category':'Club / Activity Sign-Up','emoji':'⚽','color':'#2d6a4f','keywords':matched[:4]}
    if any(k in text for k in ['meeting','interview','report','pa day']):
        return {'category':'Meeting / Important Date','emoji':'📋','color':'#457b9d','keywords':matched[:4]}
    return {'category':'School Notice','emoji':'📢','color':'#6b705c','keywords':matched[:4]}

# ═══════════════════════════════════════════════
#  SEND EMAILS
# ═══════════════════════════════════════════════

def send_email(subject, html_body):
    """Core email sender used by both instant reminders and digest."""
    if SENDER_EMAIL == 'your.email@gmail.com':
        print(f"  [DEMO] Would send: {subject}")
        return True
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = SENDER_EMAIL
        msg['To']      = ', '.join(PARENT_EMAILS)
        msg.attach(MIMEText(html_body,'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com',465) as s:
            s.login(SENDER_EMAIL, SENDER_PASSWORD)
            s.sendmail(SENDER_EMAIL, PARENT_EMAILS, msg.as_string())
        print(f"  Email sent: {subject[:60]}")
        return True
    except Exception as e:
        print(f"  Email failed: {e}")
        return False

def build_email_card(ed, show_preview=True):
    """Builds one email card block for use in both instant and digest emails."""
    deadline_block = f'<div style="background:#fff8e1;border-left:4px solid #f9a825;padding:10px 14px;border-radius:6px;margin:8px 0;font-size:13px"><strong>Deadline:</strong> {ed["deadline"]}</div>' if ed.get('deadline') else ''
    amount_block   = f'<div style="background:#fce4ec;border-left:4px solid #e07a5f;padding:10px 14px;border-radius:6px;margin:8px 0;font-size:13px"><strong>Amount Due:</strong> {ed["amount"]}</div>' if ed.get('amount') else ''
    kw_html = ''.join(f'<span style="background:#f0f0f0;padding:2px 9px;border-radius:20px;font-size:11px;margin:2px;display:inline-block">{k}</span>' for k in ed.get('keywords',[]))
    preview = f'<div style="background:#f9f9f9;border-radius:8px;padding:12px;margin-top:10px;font-size:12px;color:#666;line-height:1.6;border:1px solid #eee">{ed["body_preview"][:300].replace(chr(10),"<br>")}...</div>' if show_preview and ed.get('body_preview') else ''
    return f"""
    <div style="border:1px solid #e8e0d5;border-radius:10px;margin:12px 0;overflow:hidden">
      <div style="background:{ed.get('color','#457b9d')};padding:12px 16px;color:white;font-size:13px">
        <strong>{ed['emoji']} {ed['category']}</strong>
      </div>
      <div style="padding:14px 16px">
        <div style="font-size:15px;font-weight:600;color:#1a1510;margin-bottom:3px">{ed['subject']}</div>
        <div style="font-size:11px;color:#999;margin-bottom:8px">From: {ed['sender_name']} · {ed['date']}</div>
        {amount_block}{deadline_block}
        {f'<div style="margin-top:8px">{kw_html}</div>' if kw_html else ''}
        {preview}
      </div>
    </div>"""

def send_instant_reminder(ed):
    """Sends an email the moment a school email is detected."""
    subject = f"⚠️ School: {ed['emoji']} {ed['category']} — {ed['subject'][:45]}"
    html = f"""<html><body style="font-family:sans-serif;background:#f5f5f5;padding:20px;margin:0">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.08)">
  <div style="background:{ed.get('color','#2d6a4f')};padding:24px 28px;color:white">
    <div style="font-size:10px;letter-spacing:2px;opacity:0.7;margin-bottom:4px">SCHOOL REMINDER BOT · INSTANT ALERT</div>
    <div style="font-size:22px;font-weight:700">{ed['emoji']} {ed['category']}</div>
  </div>
  <div style="padding:24px 28px">
    {build_email_card(ed, show_preview=True)}
    <p style="margin-top:18px;color:#999;font-size:11px">Check your email for the full message and take action as needed.</p>
  </div>
  <div style="background:#f9f9f9;padding:12px 28px;border-top:1px solid #eee;font-size:10px;color:#bbb;text-align:center">
    School Reminder Bot · Built by your kid 😄
  </div>
</div></body></html>"""
    return send_email(subject, html)

def send_daily_digest(all_alerts):
    """Sends one summary email at the configured digest time."""
    today = datetime.now().strftime('%A, %B %d %Y')
    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')
    recent = [a for a in all_alerts if a.get('detected_at','') >= cutoff]
    subject = f"🏫 School Digest — {today}"

    if not recent:
        html = f"""<html><body style="font-family:sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.08)">
  <div style="background:#2d6a4f;padding:24px 28px;color:white">
    <div style="font-size:10px;letter-spacing:2px;opacity:0.7;margin-bottom:4px">DAILY DIGEST · {today.upper()}</div>
    <div style="font-size:22px;font-weight:700">✅ All Clear Today</div>
  </div>
  <div style="padding:24px 28px;font-size:14px;color:#555;line-height:1.7">
    <p>No school emails were detected in the last 24 hours. Nothing to action today!</p>
    <p style="margin-top:12px;font-size:11px;color:#999">School Reminder Bot is running and monitoring Gmail. 🤖</p>
  </div>
  <div style="background:#f9f9f9;padding:12px 28px;border-top:1px solid #eee;font-size:10px;color:#bbb;text-align:center">School Reminder Bot · Built by your kid 😄</div>
</div></body></html>"""
    else:
        # Group by category
        cats = {}
        for a in recent:
            cats.setdefault(a['category'],[]).append(a)

        payments  = [a for a in recent if a.get('amount')]
        deadlines = [a for a in recent if a.get('deadline')]

        summary_rows = ''.join(f'<tr><td style="padding:6px 10px">{a["emoji"]} {a["category"]}</td><td style="padding:6px 10px;font-weight:600">{len(v)}</td></tr>' for a,(v) in [(k,v) for k,v in cats.items()])
        cards_html = ''.join(build_email_card(a, show_preview=False) for a in recent)

        urgent_banner = ''
        if payments or deadlines:
            items = []
            if payments:  items.append(f"{len(payments)} payment(s) due")
            if deadlines: items.append(f"{len(deadlines)} deadline(s) coming up")
            urgent_banner = f'<div style="background:#fce4ec;border-left:4px solid #e07a5f;padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:13px;color:#c62828"><strong>⚠️ Action needed:</strong> {" · ".join(items)}</div>'

        html = f"""<html><body style="font-family:sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.08)">
  <div style="background:#2d6a4f;padding:24px 28px;color:white">
    <div style="font-size:10px;letter-spacing:2px;opacity:0.7;margin-bottom:4px">DAILY DIGEST · {today.upper()}</div>
    <div style="font-size:22px;font-weight:700">🏫 {len(recent)} School Email{'s' if len(recent)>1 else ''} Today</div>
  </div>
  <div style="padding:24px 28px">
    {urgent_banner}
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:13px;background:#f9f9f9;border-radius:8px;overflow:hidden">
      <tr style="background:#2d6a4f;color:white"><td style="padding:8px 10px"><strong>Category</strong></td><td style="padding:8px 10px"><strong>Count</strong></td></tr>
      {summary_rows}
    </table>
    <div style="font-size:13px;font-weight:600;color:#1a1510;margin-bottom:10px">Full Details:</div>
    {cards_html}
    <p style="margin-top:18px;color:#999;font-size:11px">Check your email for the full original messages.</p>
  </div>
  <div style="background:#f9f9f9;padding:12px 28px;border-top:1px solid #eee;font-size:10px;color:#bbb;text-align:center">School Reminder Bot · Built by your kid 😄</div>
</div></body></html>"""

    return send_email(subject, html)

# ═══════════════════════════════════════════════
#  GMAIL SCANNER
# ═══════════════════════════════════════════════

PROC_FILE = 'processed_emails.json'

def load_proc():
    return set(json.load(open(PROC_FILE))) if os.path.exists(PROC_FILE) else set()

def save_proc(ids):
    json.dump(list(ids), open(PROC_FILE,'w'))

def run_scan(service, processed):
    new_alerts = []
    try:
        after = (datetime.now()-timedelta(days=7)).strftime('%Y/%m/%d')
        msgs = service.users().messages().list(userId='me',q=f'after:{after} -from:me',maxResults=50).execute().get('messages',[])
        print(f"  Checking {len(msgs)} recent emails...")
        for m in msgs:
            mid = m['id']
            if mid in processed: continue
            full = service.users().messages().get(userId='me',id=mid,format='full').execute()
            hdrs = {h['name']:h['value'] for h in full['payload']['headers']}
            subject     = hdrs.get('Subject','(no subject)')
            sender      = hdrs.get('From','')
            date        = hdrs.get('Date','')[:16]
            sender_name = sender.split('<')[0].strip().strip('"') or sender
            body        = get_body(full)
            result      = classify(subject, body, sender)
            if result:
                ed = {
                    'id': mid, 'subject': subject[:80],
                    'sender': sender, 'sender_name': sender_name[:40],
                    'date': date, 'category': result['category'],
                    'emoji': result['emoji'], 'color': result['color'],
                    'keywords': result['keywords'],
                    'deadline': extract_deadline(subject+' '+body),
                    'amount':   extract_amount(subject+' '+body),
                    'body_preview': body[:500],
                    'email_sent': False, 'done': False,
                    'detected_at': datetime.now().strftime('%Y-%m-%d %H:%M')
                }
                ed['email_sent'] = send_instant_reminder(ed)
                new_alerts.append(ed)
                print(f"  School email detected: {subject[:50]}")
            processed.add(mid)
        save_proc(processed)
    except Exception as e:
        print(f"  Scan error: {e}")
    return new_alerts

# ═══════════════════════════════════════════════
#  FLASK APP + DASHBOARD
# ═══════════════════════════════════════════════

app = Flask(__name__)
alerts_store  = []
last_scan     = 'Never'
scan_status   = 'Ready'
digest_status = 'Not sent yet'
svc           = None

DASH = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover">
<title>School Reminder Bot</title>
<meta name="theme-color" content="#2d6a4f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="School Bot">
<link rel="manifest" href="/manifest.json">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Serif+Display&display=swap" rel="stylesheet">
<style>
:root{--bg:#f5f0eb;--s:#fff;--b:#e8e0d5;--a:#2d6a4f;--a2:#52b788;--w:#e07a5f;--t:#1a1510;--t2:#6b5f52;--t3:#9e9082}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--t);font-family:'DM Sans',sans-serif;min-height:100vh;padding-bottom:env(safe-area-inset-bottom)}

/* App header */
.appbar{background:var(--a);color:#fff;padding:16px 18px 14px;padding-top:calc(16px + env(safe-area-inset-top));display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.appbar-title{font-family:'DM Serif Display',serif;font-size:20px;letter-spacing:-.3px}
.appbar-sub{font-size:10px;opacity:.7;margin-top:1px}
.appbar-icon{font-size:28px}

/* Main content */
.page{padding:16px}

/* Status bar */
.sbar{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:12px 15px;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--a2);box-shadow:0 0 7px var(--a2);animation:pulse 2s infinite;flex-shrink:0}
.dot.idle{background:var(--t3);box-shadow:none;animation:none}
@keyframes pulse{50%{opacity:.4;transform:scale(.8)}}
.st{font-size:12px;color:var(--t2);flex:1}
.sm{font-size:10px;color:var(--t3)}

/* Stats row */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.sc{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:13px 14px;text-align:center}
.sn{font-family:'DM Serif Display',serif;font-size:26px;color:var(--a)}
.sl{font-size:9px;color:var(--t3);letter-spacing:.5px;text-transform:uppercase;margin-top:2px}

/* Action buttons */
.btns{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
.btn{border:none;border-radius:12px;padding:13px 10px;font-family:'DM Sans',sans-serif;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:6px}
.btn-primary{background:var(--a);color:#fff}
.btn-primary:hover{background:#235c42}
.btn-secondary{background:var(--s);border:1px solid var(--b);color:var(--t2)}
.btn-secondary:hover{border-color:var(--a);color:var(--a)}
.btn:disabled{opacity:.5;cursor:not-allowed}

/* Digest info box */
.digest-box{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:13px 15px;margin-bottom:14px;display:flex;align-items:center;gap:12px}
.digest-icon{font-size:24px;flex-shrink:0}
.digest-title{font-size:13px;font-weight:600;color:var(--t);margin-bottom:2px}
.digest-sub{font-size:11px;color:var(--t3)}

/* Section title */
.sec{font-family:'DM Serif Display',serif;font-size:17px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between}
.badge{background:var(--w);color:#fff;font-family:'DM Sans',sans-serif;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}

/* Empty state */
.empty{text-align:center;padding:36px 16px;color:var(--t3);background:var(--s);border:1px solid var(--b);border-radius:12px}
.empty-icon{font-size:32px;margin-bottom:8px}

/* Email cards */
.card{background:var(--s);border:1px solid var(--b);border-radius:12px;margin-bottom:10px;overflow:hidden}
.card-header{padding:10px 14px;color:#fff;display:flex;align-items:center;justify-content:space-between}
.card-cat{font-size:11px;font-weight:600;letter-spacing:.5px}
.card-date{font-size:10px;opacity:.8}
.card-body{padding:13px 14px}
.card-subj{font-size:14px;font-weight:500;margin-bottom:3px;color:var(--t)}
.card-from{font-size:11px;color:var(--t3);margin-bottom:10px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.chip{font-size:10px;padding:2px 9px;border-radius:20px;border:1px solid var(--b);color:var(--t2)}
.chip.am{background:rgba(224,122,95,.1);border-color:rgba(224,122,95,.3);color:var(--w);font-weight:600}
.chip.dl{background:rgba(255,180,0,.1);border-color:rgba(255,180,0,.3);color:#b87c00;font-weight:600}
.chip.ok{background:rgba(82,183,136,.1);border-color:rgba(82,183,136,.3);color:var(--a2)}
.chip.no{background:rgba(224,122,95,.1);border-color:rgba(224,122,95,.3);color:var(--w)}
.chip.done{background:rgba(150,150,150,.1);border-color:#ccc;color:#999}
.preview{font-size:11px;color:var(--t3);padding:9px;background:rgba(0,0,0,.02);border-radius:7px;line-height:1.6;border-left:3px solid var(--b)}
.done-btn{width:100%;margin-top:10px;padding:8px;background:none;border:1px dashed var(--b);border-radius:8px;font-size:11px;color:var(--t3);cursor:pointer;font-family:'DM Sans',sans-serif;transition:all .2s}
.done-btn:hover{border-color:var(--a2);color:var(--a2)}
.card.is-done{opacity:.5}

/* Footer */
.footer{text-align:center;padding:20px 0 8px;font-size:10px;color:var(--t3)}
</style>
</head>
<body>

<div class="appbar">
  <div>
    <div class="appbar-title">School Reminder Bot</div>
    <div class="appbar-sub">Monitoring Gmail for school emails</div>
  </div>
  <div class="appbar-icon">🏫</div>
</div>

<div class="page">

  <!-- Status -->
  <div class="sbar">
    <div class="dot" id="dot"></div>
    <div class="st" id="st">Loading...</div>
    <div class="sm" id="sm"></div>
  </div>

  <!-- Stats -->
  <div class="stats">
    <div class="sc"><div class="sn" id="tot">0</div><div class="sl">Detected</div></div>
    <div class="sc"><div class="sn" id="sen">0</div><div class="sl">Sent</div></div>
    <div class="sc"><div class="sn" id="pen">0</div><div class="sl">Action Needed</div></div>
  </div>

  <!-- Action buttons -->
  <div class="btns">
    <button class="btn btn-primary" id="sb" onclick="doScan()">🔍 Scan Now</button>
    <button class="btn btn-secondary" id="db" onclick="doDigest()">📰 Send Digest</button>
  </div>

  <!-- Daily digest info -->
  <div class="digest-box">
    <div class="digest-icon">📅</div>
    <div>
      <div class="digest-title">Daily Digest</div>
      <div class="digest-sub" id="digestSub">Sent every morning at 8:00am · <span id="digestStatus">Not sent yet today</span></div>
    </div>
  </div>

  <!-- Email list -->
  <div class="sec">
    School Emails
    <span class="badge" id="newBadge" style="display:none">NEW</span>
  </div>
  <div id="list">
    <div class="empty"><div class="empty-icon">📭</div><p>No school emails yet.</p><p style="font-size:11px;margin-top:6px">Tap Scan Now to check Gmail.</p></div>
  </div>

  <div class="footer">Checks every 5 min · 100% free · Built by your kid 😄</div>
</div>

<script>
const CAT_COLORS = {
  'Payment Required':'#e07a5f',
  'Competition / Registration':'#3d405b',
  'Permission Form Required':'#e9a800',
  'Club / Activity Sign-Up':'#2d6a4f',
  'Meeting / Important Date':'#457b9d',
  'School Notice':'#6b705c'
};

function markDone(id){
  fetch('/done/'+id, {method:'POST'}).then(()=>poll());
}

function render(alerts){
  const el = document.getElementById('list');
  if(!alerts.length){
    el.innerHTML='<div class="empty"><div class="empty-icon">📭</div><p>No school emails yet.</p><p style="font-size:11px;margin-top:6px">Tap Scan Now to check Gmail.</p></div>';
    return;
  }
  const undone = alerts.filter(a=>!a.done).length;
  document.getElementById('newBadge').style.display = undone > 0 ? 'inline' : 'none';
  el.innerHTML = alerts.slice().reverse().map(a=>`
    <div class="card ${a.done?'is-done':''}">
      <div class="card-header" style="background:${CAT_COLORS[a.category]||'#457b9d'}">
        <span class="card-cat">${a.emoji} ${a.category}</span>
        <span class="card-date">${a.date}</span>
      </div>
      <div class="card-body">
        <div class="card-subj">${a.subject}</div>
        <div class="card-from">From: ${a.sender_name}</div>
        <div class="chips">
          ${a.amount?`<span class="chip am">💵 ${a.amount}</span>`:''}
          ${a.deadline?`<span class="chip dl">⏰ ${a.deadline}</span>`:''}
          ${a.keywords.map(k=>`<span class="chip">${k}</span>`).join('')}
          <span class="chip ${a.email_sent?'ok':'no'}">${a.email_sent?'✓ Reminder sent':'✗ Reminder failed'}</span>
          ${a.done?'<span class="chip done">✓ Done</span>':''}
        </div>
        ${a.body_preview?`<div class="preview">${a.body_preview.substring(0,200)}...</div>`:''}
        ${!a.done?`<button class="done-btn" onclick="markDone('${a.id}')">✓ Mark as done</button>`:''}
      </div>
    </div>`).join('');
}

function update(d){
  document.getElementById('st').textContent = d.status;
  document.getElementById('sm').textContent = 'Last scan: '+d.last_scan;
  document.getElementById('tot').textContent = d.total;
  document.getElementById('sen').textContent = d.sent;
  document.getElementById('pen').textContent = d.pending;
  document.getElementById('dot').className = 'dot'+(d.scanning?'':' idle');
  document.getElementById('digestStatus').textContent = d.digest_status;
  render(d.alerts);
}

function doScan(){
  const b=document.getElementById('sb');
  b.disabled=true; b.textContent='⏳ Scanning...';
  fetch('/scan',{method:'POST'}).then(r=>r.json()).then(d=>{update(d);b.disabled=false;b.textContent='🔍 Scan Now';}).catch(()=>{b.disabled=false;b.textContent='🔍 Scan Now';});
}

function doDigest(){
  const b=document.getElementById('db');
  b.disabled=true; b.textContent='⏳ Sending...';
  fetch('/digest',{method:'POST'}).then(r=>r.json()).then(d=>{update(d);b.disabled=false;b.textContent='📰 Send Digest';alert('Daily digest sent!');}).catch(()=>{b.disabled=false;b.textContent='📰 Send Digest';});
}

function poll(){ fetch('/status').then(r=>r.json()).then(update).catch(console.error); }
poll(); setInterval(poll, 15000);

// Register service worker for PWA
if('serviceWorker' in navigator){ navigator.serviceWorker.register('/sw.js'); }
</script>
</body>
</html>'''

# ═══════════════════════════════════════════════
#  PWA ROUTES
# ═══════════════════════════════════════════════

@app.route('/manifest.json')
def manifest():
    return Response(json.dumps({
        "name": "School Reminder Bot",
        "short_name": "School Bot",
        "description": "Monitors Gmail for school emails and reminds parents",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f5f0eb",
        "theme_color": "#2d6a4f",
        "orientation": "portrait",
        "icons": [{"src":"/icon.svg","sizes":"any","type":"image/svg+xml"}]
    }), mimetype='application/json')

@app.route('/icon.svg')
def icon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="192" height="192"><rect width="192" height="192" rx="40" fill="#2d6a4f"/><text x="96" y="135" font-size="110" text-anchor="middle">&#127983;</text></svg>'
    return Response(svg, mimetype='image/svg+xml')

@app.route('/sw.js')
def sw():
    code = """
const C = 'school-bot-v1';
const ASSETS = ['/', '/status', '/manifest.json', '/icon.svg'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(C).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k=>k!==C).map(k=>caches.delete(k)))));
});
self.addEventListener('fetch', e => {
  e.respondWith(
    fetch(e.request).then(r => {
      const clone = r.clone();
      caches.open(C).then(c => c.put(e.request, clone));
      return r;
    }).catch(() => caches.match(e.request))
  );
});
"""
    return Response(code, mimetype='application/javascript')

# ═══════════════════════════════════════════════
#  API ROUTES
# ═══════════════════════════════════════════════

def build_status():
    return {
        'status': scan_status,
        'last_scan': last_scan,
        'total': len(alerts_store),
        'sent': sum(1 for a in alerts_store if a.get('email_sent')),
        'pending': sum(1 for a in alerts_store if (a.get('amount') or a.get('deadline')) and not a.get('done')),
        'scanning': False,
        'digest_status': digest_status,
        'alerts': alerts_store
    }

@app.route('/')
def home(): return render_template_string(DASH)

@app.route('/status')
def status(): return jsonify(build_status())

@app.route('/scan', methods=['POST'])
def manual_scan():
    global alerts_store, last_scan, scan_status, svc
    if svc:
        scan_status = 'Scanning Gmail...'
        new = run_scan(svc, load_proc())
        alerts_store.extend(new)
        last_scan = datetime.now().strftime('%H:%M:%S')
        scan_status = f'Found {len(new)} new email(s)' if new else 'No new school emails'
    else:
        scan_status = 'Gmail not connected'
    return jsonify(build_status())

@app.route('/digest', methods=['POST'])
def manual_digest():
    global digest_status
    send_daily_digest(alerts_store)
    digest_status = f'Sent manually at {datetime.now().strftime("%H:%M")}'
    return jsonify(build_status())

@app.route('/done/<email_id>', methods=['POST'])
def mark_done(email_id):
    for a in alerts_store:
        if a['id'] == email_id:
            a['done'] = True
            break
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════
#  BACKGROUND THREADS
# ═══════════════════════════════════════════════

def scanner_thread():
    global alerts_store, last_scan, scan_status, svc
    while True:
        if svc:
            new = run_scan(svc, load_proc())
            alerts_store.extend(new)
            last_scan = datetime.now().strftime('%H:%M:%S')
            scan_status = f'Idle · {len(alerts_store)} school emails total'
        time.sleep(CHECK_INTERVAL)

def digest_thread():
    """Sends the daily digest at the configured time every day."""
    global digest_status
    last_digest_day = None
    while True:
        now = datetime.now()
        if (now.hour == DIGEST_HOUR and
            now.minute == DIGEST_MINUTE and
            now.date() != last_digest_day):
            print(f"\n Sending daily digest at {now.strftime('%H:%M')}...")
            send_daily_digest(alerts_store)
            digest_status = f'Sent today at {now.strftime("%H:%M")}'
            last_digest_day = now.date()
        time.sleep(30)  # check every 30 seconds

# ═══════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    print("\n" + "="*50)
    print("  SCHOOL REMINDER BOT")
    print("="*50)
    print(f"  Gmail scan: every {CHECK_INTERVAL//60} minutes")
    print(f"  Daily digest: {DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d} every morning")
    print(f"  Sending to: {len(PARENT_EMAILS)} parent(s)")
    print(f"  Dashboard: http://localhost:5000")
    print("="*50 + "\n")

    print("Connecting to Gmail...")
    svc = get_gmail_service()
    print("Gmail connected!\n" if svc else "Add credentials.json to connect Gmail\n")

    threading.Thread(target=scanner_thread, daemon=True).start()
    threading.Thread(target=digest_thread, daemon=True).start()
    print("Scanner and digest threads running")
    print("Open http://localhost:5000 in your browser\n")

    app.run(debug=False, port=5000, host='0.0.0.0')
