from __future__ import annotations

from scheduler.db_runtime import probe_database_health


def test_probe_database_health_reports_core_metrics(app_context):
    health = probe_database_health()

    assert health["status"] == "ok"
    assert health["database_name"]
    assert health["application_name"]
    assert health["server_time_utc"]
    assert isinstance(health["active_connection_count"], int)
    assert isinstance(health["lock_wait_count"], int)
    assert isinstance(health["idle_in_transaction_count"], int)
    assert health["latency_ms"] >= 0


def test_health_db_route_is_public_and_returns_json(client):
    response = client.get("/health/db")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"status": "ok", "database": "reachable"}
    assert response.headers.get("Content-Type", "").startswith("application/json")
