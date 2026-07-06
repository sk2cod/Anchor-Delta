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
