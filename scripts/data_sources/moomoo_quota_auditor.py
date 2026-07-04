"""Moomoo historical K-line quota auditor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.data_sources.moomoo_client import MoomooQuoteClient


def audit_quota(client: MoomooQuoteClient) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "timestamp": timestamp,
        "quota_status": "FAIL",
        "used_quota": None,
        "remain_quota": None,
        "detail_list": [],
        "error": "",
    }
    try:
        data = client.checked_call("get_history_kl_quota", get_detail=True)
        if isinstance(data, dict):
            payload.update({
                "quota_status": "PASS",
                "used_quota": data.get("used_quota"),
                "remain_quota": data.get("remain_quota"),
                "detail_list": data.get("detail_list", []),
            })
        else:
            payload["quota_status"] = "PASS"
            payload["detail_list"] = data.to_dict("records") if hasattr(data, "to_dict") else data
    except TypeError:
        data = client.checked_call("get_history_kl_quota")
        payload["quota_status"] = "PASS"
        payload["detail_list"] = data.to_dict("records") if hasattr(data, "to_dict") else data
    except Exception as exc:
        payload["error"] = str(exc)
    return payload
