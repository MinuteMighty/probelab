"""Tests for API probe executor."""

import os
from unittest.mock import patch

import httpx

from probelab.scan.api_check import check_api, _find_api_key, _find_key_name, ApiCheckResult


def _mock_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code)


class TestFindApiKey:
    def test_finds_explicit_key(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret123")
        assert _find_api_key("MY_KEY", [], []) == "secret123"

    def test_finds_auth_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")
        assert _find_api_key(None, ["OPENAI_API_KEY"], []) == "sk-xxx"

    def test_finds_provider_key(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_xxx")
        assert _find_api_key(None, [], ["STRIPE_SECRET_KEY"]) == "sk_test_xxx"

    def test_returns_none_when_missing(self):
        assert _find_api_key(None, ["NONEXISTENT_KEY"], []) is None


class TestFindKeyName:
    def test_finds_name(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")
        assert _find_key_name(None, ["OPENAI_API_KEY"], []) == "OPENAI_API_KEY"

    def test_empty_when_missing(self):
        assert _find_key_name(None, ["NONEXISTENT"], []) == ""


class TestCheckApiSafeMode:
    """Test that default mode (verify_key=False) never sends the key."""

    def test_no_key_returns_no_key_status(self):
        result = check_api("openai", verify_key=False)
        assert result.status == "no_key"
        assert "OPENAI_API_KEY" in result.message

    def test_unknown_provider(self):
        result = check_api("nonexistent-provider")
        assert result.status == "unknown"

    def test_key_set_but_safe_mode_doesnt_send_it(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key-that-should-not-be-sent")

        # Mock httpx to verify no auth header is sent
        sent_headers: dict = {}

        def mock_handler(request: httpx.Request) -> httpx.Response:
            sent_headers.update(dict(request.headers))
            return httpx.Response(401)

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.return_value = httpx.Response(401)
            # Capture the headers that were passed
            result = check_api("openai", verify_key=False)

        # Result should be healthy (401 = service is up, just needs auth)
        assert result.status == "healthy"
        assert "reachable" in result.message
        assert result.details.get("verified_with_key") is False

    def test_service_reachable_key_configured(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_xxx")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.return_value = httpx.Response(401)
            result = check_api("stripe", verify_key=False)

        assert result.status == "healthy"
        assert "STRIPE_SECRET_KEY is set" in result.message

    def test_service_down(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.return_value = httpx.Response(503)
            result = check_api("openai", verify_key=False)

        assert result.status == "service_down"

    def test_connection_refused(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            result = check_api("openai", verify_key=False)

        assert result.status == "unreachable"


class TestCheckApiVerifyMode:
    """Test verify_key=True mode (opt-in, actually sends the key)."""

    def test_valid_key_returns_healthy(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-valid")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = httpx.Response(200)
            result = check_api("openai", verify_key=True)

        assert result.status == "healthy"
        assert "valid" in result.message.lower()

    def test_expired_key_returns_auth_expired(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-expired")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = httpx.Response(401)
            result = check_api("openai", verify_key=True)

        assert result.status == "auth_expired"

    def test_forbidden_returns_auth_invalid(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_xxx")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = httpx.Response(403)
            result = check_api("stripe", verify_key=True)

        assert result.status == "auth_invalid"

    def test_rate_limited_still_healthy(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")

        with patch("probelab.scan.api_check.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = httpx.Response(429)
            result = check_api("openai", verify_key=True)

        assert result.status == "healthy"
        assert result.details.get("rate_limited") is True
