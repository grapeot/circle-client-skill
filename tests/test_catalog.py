from __future__ import annotations

import copy
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from circle_client_skill import cli
from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings


def paywall():
    return {"id": 501, "status": "inactive", "currency": {"code": "usd"},
            "prices": [{"id": 9001, "paywall_id": 501, "status": "active", "amount": 100},
                       {"id": 9002, "paywall_id": 501, "status": "draft", "amount": 200}]}


def coupon():
    return {"id": 1001, "status": "inactive", "active": False, "code": "EXAMPLE10",
            "type": "PaywallCoupons::Percent", "amount": "10.0", "duration": "forever",
            "all_paywalls": False, "paywall_ids": [501], "paywall_prices": {"501": [9001]},
            "all_paid_events": False, "paywall_event_ids": [], "redemptions_count": 0}


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.text = "private upstream body, never show"

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def client(payload, status=200):
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        cookie="session=fake", csrf_token="fake-csrf",
    )
    session = Session(Response(payload, status))
    return CircleClient(settings, session=session), session


def test_paywalls_all_statuses_nested_prices_and_unknown_completeness():
    c, s = client([paywall()])
    result = c.list_paywalls()
    assert result["records"] == [paywall()]
    assert result["pagination"]["complete"] is None
    params = parse_qs(urlsplit(s.calls[0][0]).query)
    assert params == {"status[]": ["draft", "active", "inactive"], "type[]": ["space", "event"]}
    assert s.calls[0][1]["allow_redirects"] is False
    assert s.calls[0][1]["headers"]["Cookie"] == "session=fake"


def test_status_filter_is_not_applied_to_nested_prices():
    c, _ = client([paywall(), {"id": 502, "status": "active", "prices": []}])
    result = c.list_paywalls(statuses=("inactive",), types=("space",))
    assert result["records"] == [paywall()]
    assert result["pagination"]["received_count"] == 2


def test_coupon_array_is_one_request_without_page_parameters():
    c, s = client([coupon(), dict(coupon(), id=1002, status="active", active=True)])
    result = c.list_coupons(statuses=("inactive",))
    assert len(s.calls) == 1 and "?" not in s.calls[0][0]
    assert result["records"] == [coupon()]
    assert result["records"][0]["paywall_prices"] == {"501": [9001]}
    assert result["pagination"]["complete"] is None
    assert result["pagination"]["received_count"] == 2


def test_get_exact_coupon_and_paywall_from_list():
    c, s = client(coupon())
    assert c.get_coupon(1001)["record"] == coupon()
    assert urlsplit(s.calls[0][0]).path == "/internal_api/paywalls/coupons/1001"
    c, s = client([paywall()])
    assert c.get_paywall(501)["record"] == paywall()
    assert urlsplit(s.calls[0][0]).path == "/internal_api/paywalls"
    with pytest.raises(CircleClientError, match="absence is not proof"):
        c.get_paywall(502)


@pytest.mark.parametrize("value", [0, -1, True, "../coupons", "https://elsewhere.example"])
def test_ids_fail_before_network(value):
    c, s = client({})
    for method in (c.get_coupon, c.get_paywall):
        with pytest.raises(ValueError):
            method(value)
    assert not s.calls


@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
def test_http_errors_preserve_status_without_private_body(status):
    c, s = client(None, status)
    with pytest.raises(CircleClientError) as exc:
        c.list_coupons()
    assert exc.value.status_code == status
    assert "private" not in str(exc.value)
    assert len(s.calls) == 1


@pytest.mark.parametrize("payload", [{"records": [], "has_next_page": True}, None, [None],
                                     [coupon(), coupon()]])
def test_contract_changes_fail_not_empty_or_complete(payload):
    c, _ = client(payload)
    with pytest.raises(CircleClientError):
        c.list_coupons()


def test_empty_array_still_has_unknown_completeness():
    c, _ = client([])
    assert c.list_paywalls()["pagination"]["complete"] is None


def test_raw_units_dates_and_inactive_price_are_not_reinterpreted():
    fixed = dict(coupon(), type="PaywallCoupons::Fixed", amount="12.50",
                 starts_at="2030-01-01T00:00:00Z", ends_at=None, max_redemptions=9)
    c, _ = client([fixed])
    assert c.list_coupons()["records"] == [fixed]
    record = paywall()
    record["prices"][0]["status"] = "inactive"
    c, _ = client([record])
    assert c.list_paywalls()["records"] == [record]


def test_invalid_filters_are_rejected_before_request():
    c, s = client([])
    with pytest.raises(ValueError):
        c.list_paywalls(statuses=("deleted",))
    with pytest.raises(ValueError):
        c.list_paywalls(types=("../coupons",))
    with pytest.raises(ValueError):
        c.list_coupons(statuses=("draft",))
    assert not s.calls


def test_malformed_scopes_and_mismatched_ids_are_rejected():
    bad = copy.deepcopy(coupon())
    bad["paywall_prices"] = {"501": "9001"}
    c, _ = client([bad])
    with pytest.raises(CircleClientError, match="price scopes"):
        c.list_coupons()
    c, _ = client(dict(coupon(), id=1002))
    with pytest.raises(CircleClientError, match="did not match"):
        c.get_coupon(1001)
    bad = paywall()
    bad["prices"][0]["paywall_id"] = 502
    c, _ = client([bad])
    with pytest.raises(CircleClientError, match="mismatched"):
        c.list_paywalls()


def test_non_json_and_network_errors_do_not_leak_body():
    c, _ = client(requests.JSONDecodeError("bad", "private", 0))
    with pytest.raises(CircleClientError, match="non-JSON"):
        c.list_coupons()
    c, s = client(None)

    def fail(*args, **kwargs):
        raise requests.Timeout("private cookie value")

    s.get = fail
    with pytest.raises(CircleClientError) as exc:
        c.list_coupons()
    assert str(exc.value).endswith("Timeout")


def test_cli_output_is_private_and_get_and_list_parse(tmp_path, monkeypatch, capsys):
    c, _ = client([coupon()])
    monkeypatch.setattr(cli, "load_settings", lambda _: object())
    monkeypatch.setattr(cli, "CircleClient", lambda *a, **kw: c)
    target = tmp_path / "coupons.json"
    args = cli.build_parser().parse_args([
        "coupons", "list", "--status", "inactive", "--output", str(target), "--json",
    ])
    args.handler(args)
    assert json.loads(capsys.readouterr().out)["records"] == [coupon()]
    assert json.loads(target.read_text())["pagination"]["complete"] is None
    assert target.stat().st_mode & 0o777 == 0o600
    for resource in ("paywalls", "coupons"):
        args = cli.build_parser().parse_args([resource, "get", "501", "--env-file", "fake.env"])
        assert args.id == 501 and args.env_file == "fake.env"
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args([resource, "delete", "501"])
