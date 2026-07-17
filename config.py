import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import streamlit as st
    if hasattr(st, 'secrets'):
        os.environ.setdefault('ANTHROPIC_API_KEY', st.secrets.get('ANTHROPIC_API_KEY', ''))
        os.environ.setdefault('TAVILY_API_KEY', st.secrets.get('TAVILY_API_KEY', ''))
        os.environ.setdefault('SUPABASE_URL', st.secrets.get('SUPABASE_URL', ''))
        os.environ.setdefault('SUPABASE_ANON_KEY', st.secrets.get('SUPABASE_KEY', ''))
        os.environ.setdefault('GEMINI_API_KEY', st.secrets.get('GEMINI_API_KEY', ''))
except Exception:
    pass

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

_required = {
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "TAVILY_API_KEY": TAVILY_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_ANON_KEY": SUPABASE_ANON_KEY,
}

_missing = [name for name, value in _required.items() if not value]

if _missing:
    raise RuntimeError(
        f"Missing required environment variable(s): {', '.join(_missing)}. "
        "Set them in your .env file or Streamlit secrets."
    )

VALID_DOMAINS = [
    "world",
    "finance",
    "ai_tech",
    "australia",
    "india",
]

# The three domains the carousel engine supports (Australia/India have no
# carousel path) — run together from one button since they're the ones
# actually used for carousel generation, while Australia/India stay
# individually-run-only.
CAROUSEL_DOMAINS = ("world", "finance", "ai_tech")

MAX_ACTIVE_CARDS = 20
ARCHIVE_AFTER_DAYS = 14
STALE_CARD_DAYS = 7
DOMAIN_COST_GUARD_USD = 0.50
ALL_DOMAINS_COST_GUARD_USD = 0.80
SYDNEY_TZ = "Australia/Sydney"

# Pipeline freshness window
# Set to 168 for initial bootstrap run (7 days of articles)
# Set back to 48 for daily upkeep runs
FRESHNESS_HOURS = 48

# Carousel "Approve & Sync" export destination (Decision #52). Point this at
# a Google Drive / iCloud synced folder so approving a carousel syncs it to
# phone without a manual copy step. carousel/assembler.py falls back to the
# local outputs/bundles/ folder if this is left empty.
CAROUSEL_SYNC_DIR = os.getenv("CAROUSEL_SYNC_DIR", r"G:\My Drive\Anchor & Delta\Outbox")

# Google Drive upload for Approve & Sync (Stage 3 — INFRA_DECISIONS.md #02).
# All optional: carousel/assembler.py and carousel/drive_sync.py read these
# directly from the environment (same "soft dependency, never crash" pattern
# as OPENAI_API_KEY in carousel/image_generator.py) and fall back to the
# existing local outputs/bundles/ write when any of the three OAuth vars is
# missing — so these are deliberately absent from `_required` above. Get
# GOOGLE_OAUTH_REFRESH_TOKEN via scripts/get_drive_refresh_token.py.
# GOOGLE_DRIVE_FOLDER_ID is auto-created and logged on first run if unset.
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REFRESH_TOKEN = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN", "")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# Password gate for public Railway deployment (Stage 4). ui/app.py reads
# APP_PASSWORD directly via os.getenv() at the top of the script (same
# "soft/optional env var" pattern as GOOGLE_OAUTH_* above), so this constant
# is tracked here for documentation/discoverability only. Deliberately left
# out of `_required` above: unset means the gate is skipped entirely, the
# correct default for local dev where the app was never reachable by anyone
# else in the first place.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
