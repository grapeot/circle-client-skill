"""Validation and envelopes for the observed, unpaginated configuration reads."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .client import CircleClientError

PAYWALL_STATUSES = ("draft", "active", "inactive")
PAYWALL_TYPES = ("space", "event")
COUPON_STATUSES = ("active", "inactive")


def positive_id(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_record(record: Any, kind: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise CircleClientError(f"Circle {kind} response contained a non-object record")
    try:
        positive_id(record.get("id"), "id")
    except ValueError as exc:
        raise CircleClientError(f"Circle {kind} record has no valid id") from exc
    if not isinstance(record.get("status"), str):
        raise CircleClientError(f"Circle {kind} record has no status")
    if kind == "paywall":
        prices = record.get("prices")
        if not isinstance(prices, list):
            raise CircleClientError("Circle paywall record has no prices array")
        seen: set[int] = set()
        for price in prices:
            validate_record(price, "price")
            if price["id"] in seen or price.get("paywall_id", record["id"]) != record["id"]:
                raise CircleClientError("Circle returned duplicate or mismatched nested prices")
            seen.add(price["id"])
    if kind == "coupon":
        for flag in ("all_paywalls", "all_paid_events"):
            if type(record.get(flag)) is not bool:
                raise CircleClientError("Circle coupon scope flags are missing or invalid")
        for field in ("paywall_ids", "paywall_event_ids"):
            ids = record.get(field)
            if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids):
                raise CircleClientError("Circle coupon scope ids are missing or invalid")
        prices = record.get("paywall_prices")
        if not isinstance(prices, dict) or any(
            not isinstance(key, str) or not key.isdecimal() or int(key) <= 0
            or not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids)
            for key, ids in prices.items()
        ):
            raise CircleClientError("Circle coupon price scopes are missing or invalid")
    return record


def array_records(payload: Any, kind: str) -> list[dict[str, Any]]:
    # An envelope is a contract change, not an empty list or proof of completion.
    if not isinstance(payload, list):
        raise CircleClientError(f"Circle {kind} list did not return the observed JSON array")
    records = [validate_record(record, kind) for record in payload]
    if len({record["id"] for record in records}) != len(records):
        raise CircleClientError(f"Circle {kind} list returned duplicate ids")
    return records


def list_result(records: list[dict[str, Any]], *, endpoint: str,
                filters: dict[str, Any], received: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": {"endpoint": endpoint, "filters": filters},
        "count": len(records),
        "records": records,
        "pagination": {
            "pages_fetched": 1,
            "received_count": received,
            "complete": None,
            "stop_reason": "array_without_pagination_metadata",
        },
    }
