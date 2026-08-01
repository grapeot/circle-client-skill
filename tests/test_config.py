from __future__ import annotations

import stat
from pathlib import Path

import pytest

from circle_client_skill.config import (
    ConfigurationError,
    load_settings,
    parse_curl,
    save_settings,
)

SAMPLE_CURL = """curl 'https://community.example.com/internal_api/notifications?per_page=15&page=1' \\
  -H 'Accept: application/json' \\
  -H 'Authorization: Bearer fake.header.signature' \\
  -H 'Cookie: session=fake-cookie' \\
  -H 'User-Agent: Test Browser' \\
  -H 'Referer: https://community.example.com/home' \\
  -H 'X-Circle-Frontend-Version: fake-version'"""


def test_parse_browser_curl_extracts_only_required_configuration() -> None:
    settings = parse_curl(SAMPLE_CURL)

    assert settings.notifications_url.startswith("https://community.example.com/internal_api/")
    assert settings.count_url.endswith("new_notifications_count")
    assert settings.reset_count_url.endswith("mark_all_as_read")
    assert settings.authorization == "Bearer fake.header.signature"
    assert settings.cookie == "session=fake-cookie"
    assert settings.user_agent == "Test Browser"
    assert settings.frontend_version == "fake-version"


def test_parse_rejects_non_notification_endpoint() -> None:
    with pytest.raises(ConfigurationError, match="notifications"):
        parse_curl(
            "curl 'https://community.example.com/internal_api/profile' -H 'Authorization: Bearer x'"
        )


def test_count_curl_derives_list_and_count_urls() -> None:
    settings = parse_curl(
        "curl 'https://community.example.com/internal_api/notifications/"
        "new_notifications_count?community_id=123' -H 'Authorization: Bearer x'"
    )

    assert settings.notifications_url == "https://community.example.com/internal_api/notifications"
    assert settings.count_url.endswith("new_notifications_count?community_id=123")


def test_reset_count_curl_captures_mutation_headers() -> None:
    settings = parse_curl(
        "curl 'https://community.example.com/internal_api/notifications/mark_all_as_read?' "
        "-X POST -H 'Authorization: Bearer x' -H 'Cookie: session=fake' "
        "-H 'X-CSRF-Token: fake-csrf' -H 'Origin: https://community.example.com'"
    )

    assert settings.reset_count_url.endswith("mark_all_as_read")
    assert settings.csrf_token == "fake-csrf"
    assert settings.origin == "https://community.example.com"
    assert "X-CSRF-Token" not in settings.headers()
    assert settings.headers(mutation=True)["X-CSRF-Token"] == "fake-csrf"


def test_save_and_load_env_with_private_permissions(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    original = parse_curl(SAMPLE_CURL)

    save_settings(original, env_path)
    loaded = load_settings(env_path)

    assert loaded == original
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert "curl " not in env_path.read_text(encoding="utf-8")
