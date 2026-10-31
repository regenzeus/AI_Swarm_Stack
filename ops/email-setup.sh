#!/usr/bin/env bash
# One-time e-mail setup for Mission Control's report e-mails (Gmail SMTP). Run it yourself in a terminal:
#   make email-setup
# You need a Gmail app password: Google account -> Security -> 2-Step Verification -> App passwords
# (https://myaccount.google.com/apppasswords), name it "ai-stack". It is stored encrypted in the sops secrets
# and never printed. Then it sends you a test e-mail.
set -euo pipefail
cd "$(dirname "$0")/.."
S=secrets/secrets.enc.yaml
default=$(sops -d --extract '["SEC_CONTACT"]' "$S" 2>/dev/null | grep -oE '[[:alnum:]._%+-]+@[[:alnum:].-]+' || true)
read -r -p "Gmail address that sends the reports [${default}]: " from; from=${from:-$default}
read -r -p "Send reports to [${from}]: " to; to=${to:-$from}
read -r -s -p "Gmail app password (16 letters, hidden): " pw; echo
pw=${pw// /}
[ ${#pw} -ge 16 ] || { echo "That does not look like an app password (16 letters)."; exit 1; }
sops set "$S" '["GMAIL_ADDRESS"]' "\"$from\""
sops set "$S" '["MAIL_TO"]' "\"$to\""
sops set "$S" '["GMAIL_APP_PASSWORD"]' "\"$pw\""
unset pw
echo "Stored (encrypted). Sending a test e-mail..."
sops exec-env "$S" 'python3 - <<EOF
import os, smtplib
from email.mime.text import MIMEText
m = MIMEText("Mission Control can send you report e-mails now. Turn on E-mail per mission under Settings.")
m["Subject"], m["From"], m["To"] = "Mission Control: e-mail works", os.environ["GMAIL_ADDRESS"], os.environ["MAIL_TO"]
with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"]); s.send_message(m)
print("Test e-mail sent to", os.environ["MAIL_TO"])
EOF'
systemctl --user restart missions.service && echo "Mission Control restarted with e-mail on."
