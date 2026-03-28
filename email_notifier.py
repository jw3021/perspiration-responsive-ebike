import smtplib
from email.message import EmailMessage
import threading
import time

# =========================================================================
# FILL THESE IN WITH YOUR ACTUAL EMAIL CREDENTIALS
# =========================================================================
# To use Gmail, you MUST generate an "App Password" in your Google Account Security settings.
# Regular passwords will be blocked by Google automatically!

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "williamsjosh0402@gmail.com"
SENDER_APP_PASSWORD = "lkni qcmq nehx bmiv"

# Put the email address of the phone in your pocket here!
RECEIVER_EMAIL = "williamsjosh0402@gmail.com"

# =========================================================================

def _send_email_async(subject, body):
    """Internal blocking function that actually connects to the server."""
    if not SENDER_EMAIL or SENDER_EMAIL == "your_pi_email@gmail.com":
        print("[Email Alert] Error: Email credentials not configured in email_notifier.py!")
        return

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL

        # Fast SSL connection (forces secure connection immediately)
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[Email Alert] Successfully sent to pocket phone: '{subject}'")

    except Exception as e:
        print(f"[Email Alert] Failed to send email: {e}")

def fire_alert(subject, body):
    """
    Non-blocking wrapper that throws the email onto a background thread.
    This guarantees the eBike motor logic NEVER freezes while waiting for Google's servers to respond!
    """
    t = threading.Thread(target=_send_email_async, args=(subject, body), daemon=True)
    t.start()

