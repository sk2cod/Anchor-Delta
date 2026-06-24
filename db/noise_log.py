from datetime import datetime, timedelta, timezone

from db.client import supabase_client


def log_noise(headline, source_url, gate_failed, reason, rerouted_to=None):
    supabase_client.table("noise_log").insert(
        {
            "headline": headline,
            "source_url": source_url,
            "gate_failed": gate_failed,
            "reason": reason,
            "rerouted_to": rerouted_to,
        }
    ).execute()


def get_noise_log_since(hours=24):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    response = (
        supabase_client.table("noise_log")
        .select("*")
        .gte("logged_at", cutoff)
        .order("logged_at", desc=True)
        .execute()
    )
    return response.data
