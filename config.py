import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

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
        "Set them in your .env file."
    )

VALID_DOMAINS = [
    "world",
    "finance",
    "ai_tech",
    "australia",
    "india",
]

MAX_ACTIVE_CARDS = 15
ARCHIVE_AFTER_DAYS = 14
SYDNEY_TZ = "Australia/Sydney"

# Pipeline freshness window
# Set to 168 for initial bootstrap run (7 days of articles)
# Set back to 48 for daily upkeep runs
FRESHNESS_HOURS = 48
