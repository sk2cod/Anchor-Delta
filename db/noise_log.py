from datetime import datetime, timedelta, timezone

from db.client import supabase_client


def log_noise(headline, source_url, gate_failed, reason, rerouted_to=None, run_id=None):
    supabase_client.table("noise_log").insert(
        {
            "headline": headline,
            "source_url": source_url,
            "gate_failed": gate_failed,
            "reason": reason,
            "rerouted_to": rerouted_to,
            "run_id": run_id,
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


def get_noise_log_by_run_id(run_id: str):
    response = (
        supabase_client.table("noise_log")
        .select("*")
        .eq("run_id", run_id)
        .order("logged_at", desc=True)
        .execute()
    )
    return response.data
