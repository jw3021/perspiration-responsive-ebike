# =============================================================================
# credentials.example.py — Credentials template
# =============================================================================
# Copy this file to credentials.py and fill in your real values.
# credentials.py is gitignored and will never be committed to the repository.
#
# Usage:
#   cp credentials.example.py credentials.py
#   # then edit credentials.py with your credentials
# =============================================================================

# --- Supabase (cloud database) ---
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_KEY = "your-supabase-anon-key"

# --- Gmail notification (optional) ---
# Generate an App Password at: myaccount.google.com → Security → App Passwords
GMAIL_ADDRESS = "your-email@gmail.com"
GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"
NOTIFICATION_EMAIL = "your-notification-email@gmail.com"
