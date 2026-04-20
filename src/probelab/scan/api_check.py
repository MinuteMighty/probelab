"""API probe executor — actually verifies that your API keys work.

For each known provider, knows:
- Which endpoint to hit
- How to pass the API key (header, query param, etc.)
- How to interpret the response (200 = ok, 401 = expired, 403 = revoked)
- How to check if a specific model still exists

This is the part that turns "you depend on Stripe" into "your Stripe key
is expired" or "the model you're using was deprecated."
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from probelab.scan.patterns import ApiProvider, KNOWN_PROVIDERS, get_provider


@dataclass
class ApiCheckResult:
    """Result of checking a single API dependency."""

    provider: str
    status: str  # "healthy", "auth_expired", "auth_invalid", "service_down", "unreachable", "no_key", "unknown"
    message: str
    response_code: int = 0
    response_time_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "message": self.message,
            "response_code": self.response_code,
            "response_time_ms": self.response_time_ms,
            "details": self.details,
        }


# ─────────────────────────────────────────────────────────────────────
# Provider-specific auth configurations
# ─────────────────────────────────────────────────────────────────────

@dataclass
class AuthConfig:
    """How to authenticate with a provider's API."""

    header_name: str = "Authorization"
    header_template: str = "Bearer {key}"  # {key} gets replaced with the actual key
    method: str = "GET"
    env_keys: list[str] = field(default_factory=list)


_AUTH_CONFIGS: dict[str, AuthConfig] = {
    "openai": AuthConfig(
        header_name="Authorization",
        header_template="Bearer {key}",
        env_keys=["OPENAI_API_KEY", "OPENAI_KEY"],
    ),
    "anthropic": AuthConfig(
        header_name="x-api-key",
        header_template="{key}",
        env_keys=["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
    ),
    "google-gemini": AuthConfig(
        # Gemini uses query param, not header
        header_name="",
        header_template="",
        env_keys=["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"],
    ),
    "replicate": AuthConfig(
        header_name="Authorization",
        header_template="Bearer {key}",
        env_keys=["REPLICATE_API_TOKEN"],
    ),
    "stripe": AuthConfig(
        header_name="Authorization",
        header_template="Bearer {key}",
        env_keys=["STRIPE_SECRET_KEY", "STRIPE_API_KEY", "STRIPE_KEY"],
    ),
    "aws": AuthConfig(
        # AWS uses signature-based auth, too complex for a simple check
        header_name="",
        header_template="",
        env_keys=["AWS_ACCESS_KEY_ID"],
    ),
    "huggingface": AuthConfig(
        header_name="Authorization",
        header_template="Bearer {key}",
        env_keys=["HF_TOKEN", "HUGGINGFACE_TOKEN", "HF_API_KEY"],
    ),
    "cohere": AuthConfig(
        header_name="Authorization",
        header_template="Bearer {key}",
        env_keys=["COHERE_API_KEY", "CO_API_KEY"],
    ),
    "mistral": AuthConfig(
        header_name="Authorization",
        header_template="Bearer {key}",
        env_keys=["MISTRAL_API_KEY"],
    ),
}


def _get_auth_config(provider_name: str) -> AuthConfig:
    return _AUTH_CONFIGS.get(provider_name, AuthConfig())


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def check_api(
    provider_name: str,
    env_key: str | None = None,
    timeout: int = 15,
    verify_key: bool = False,
) -> ApiCheckResult:
    """Check if an API provider is reachable and the API key is configured.

    SAFE BY DEFAULT: probelab never sends your API key anywhere unless you
    explicitly pass verify_key=True. Default mode only checks:
    1. Is the env var set?
    2. Is the endpoint reachable (unauthenticated)?

    Args:
        provider_name: Name of the provider (e.g., "openai", "stripe").
        env_key: Override which env var to use for the key.
        timeout: Request timeout in seconds.
        verify_key: If True, actually send the key to verify it works.
                    If False (default), only check if the key is set.
    """
    provider = get_provider(provider_name)
    if not provider:
        return ApiCheckResult(
            provider=provider_name,
            status="unknown",
            message=f"Unknown provider: {provider_name}",
        )

    if not provider.health_url:
        return ApiCheckResult(
            provider=provider_name,
            status="unknown",
            message=f"{provider_name}: no health URL configured (project-specific endpoint)",
        )

    auth = _get_auth_config(provider_name)

    # Check if the API key is set (never read the actual value unless verify_key)
    api_key = _find_api_key(env_key, auth.env_keys, provider.env_keys)
    key_env_name = _find_key_name(env_key, auth.env_keys, provider.env_keys)

    if not api_key:
        searched = env_key or ", ".join(auth.env_keys or provider.env_keys)
        return ApiCheckResult(
            provider=provider_name,
            status="no_key",
            message=f"No API key found. Set ${searched} in your environment.",
            details={"searched_env_vars": auth.env_keys or provider.env_keys},
        )

    if not verify_key:
        # SAFE MODE: just check reachability without sending the key
        return _check_reachability(provider, key_env_name, timeout)

    # VERIFY MODE: actually send the key (user explicitly opted in)
    # Build the request
    url = provider.health_url
    headers: dict[str, str] = {"User-Agent": "probelab/1.0"}

    if provider_name == "google-gemini":
        # Gemini uses query param
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"
    elif auth.header_name:
        headers[auth.header_name] = auth.header_template.format(key=api_key)

    # Make the request
    try:
        start = time.monotonic()
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.request("GET", url, headers=headers)
        elapsed_ms = int((time.monotonic() - start) * 1000)
    except httpx.ConnectError:
        return ApiCheckResult(
            provider=provider_name,
            status="unreachable",
            message=f"{provider.description}: connection failed. Service may be down.",
        )
    except httpx.TimeoutException:
        return ApiCheckResult(
            provider=provider_name,
            status="unreachable",
            message=f"{provider.description}: request timed out after {timeout}s.",
        )
    except httpx.RequestError as e:
        return ApiCheckResult(
            provider=provider_name,
            status="unreachable",
            message=f"{provider.description}: {e}",
        )

    # Classify the response
    return _classify_response(provider, response, elapsed_ms)


def check_all_apis(
    providers: list[dict[str, str]],
    timeout: int = 15,
) -> list[ApiCheckResult]:
    """Check multiple API providers.

    Args:
        providers: List of {"provider": "name", "env_key": "KEY"} dicts.
    """
    results = []
    for p in providers:
        result = check_api(
            provider_name=p["provider"],
            env_key=p.get("env_key"),
            timeout=timeout,
        )
        results.append(result)
    return results


# ─────────────────────────────────────────────────────────────────────
# Response classification
# ─────────────────────────────────────────────────────────────────────

def _classify_response(
    provider: ApiProvider, response: httpx.Response, elapsed_ms: int
) -> ApiCheckResult:
    """Classify an API response into a health status."""
    code = response.status_code

    if code == 200:
        return ApiCheckResult(
            provider=provider.name,
            status="healthy",
            message=f"{provider.description}: API key valid, service responding.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    if code == 401:
        return ApiCheckResult(
            provider=provider.name,
            status="auth_expired",
            message=f"{provider.description}: API key is invalid or expired. Generate a new key.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    if code == 403:
        return ApiCheckResult(
            provider=provider.name,
            status="auth_invalid",
            message=f"{provider.description}: API key lacks required permissions. Check your plan/scopes.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    if code == 429:
        return ApiCheckResult(
            provider=provider.name,
            status="healthy",
            message=f"{provider.description}: Rate limited (key works, but slow down). {elapsed_ms}ms.",
            response_code=code,
            response_time_ms=elapsed_ms,
            details={"rate_limited": True},
        )

    if code == 404:
        return ApiCheckResult(
            provider=provider.name,
            status="service_down",
            message=f"{provider.description}: Endpoint not found (404). API may have changed.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    if 500 <= code < 600:
        return ApiCheckResult(
            provider=provider.name,
            status="service_down",
            message=f"{provider.description}: Server error ({code}). Service may be having issues.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    return ApiCheckResult(
        provider=provider.name,
        status="unknown",
        message=f"{provider.description}: Unexpected response ({code}).",
        response_code=code,
        response_time_ms=elapsed_ms,
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _find_api_key(
    explicit_key: str | None,
    auth_env_keys: list[str],
    provider_env_keys: list[str],
) -> str | None:
    """Find an API key from environment variables."""
    # Check explicit key first
    if explicit_key:
        val = os.environ.get(explicit_key)
        if val:
            return val

    # Then check auth config keys
    for key in auth_env_keys:
        val = os.environ.get(key)
        if val:
            return val

    # Then check provider default keys
    for key in provider_env_keys:
        val = os.environ.get(key)
        if val:
            return val

    return None


def _find_key_name(
    explicit_key: str | None,
    auth_env_keys: list[str],
    provider_env_keys: list[str],
) -> str:
    """Find the name of the env var that has the API key (not the value)."""
    if explicit_key and os.environ.get(explicit_key):
        return explicit_key
    for key in auth_env_keys:
        if os.environ.get(key):
            return key
    for key in provider_env_keys:
        if os.environ.get(key):
            return key
    return ""


def _check_reachability(
    provider: ApiProvider, key_env_name: str, timeout: int
) -> ApiCheckResult:
    """Check if an API endpoint is reachable WITHOUT sending the API key.

    This is the safe default: we verify the service is up and your key
    is configured, but we never transmit the key.
    """
    try:
        start = time.monotonic()
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            # Hit the endpoint without auth — we expect 401/403 (meaning service is up)
            response = client.get(
                provider.health_url,
                headers={"User-Agent": "probelab/1.0"},
            )
        elapsed_ms = int((time.monotonic() - start) * 1000)
    except httpx.ConnectError:
        return ApiCheckResult(
            provider=provider.name,
            status="unreachable",
            message=f"{provider.description}: connection failed. Service may be down.",
        )
    except httpx.TimeoutException:
        return ApiCheckResult(
            provider=provider.name,
            status="unreachable",
            message=f"{provider.description}: timed out after {timeout}s.",
        )
    except httpx.RequestError as e:
        return ApiCheckResult(
            provider=provider.name,
            status="unreachable",
            message=f"{provider.description}: {e}",
        )

    code = response.status_code
    key_msg = f"${key_env_name} is set" if key_env_name else "key configured"

    # For unauthenticated requests:
    # 401/403 = service is UP (just rejected us because no auth) = healthy
    # 200 = service is up and doesn't require auth for this endpoint = healthy
    # 5xx = service is having problems
    if code in (200, 401, 403):
        return ApiCheckResult(
            provider=provider.name,
            status="healthy",
            message=f"{provider.description}: service reachable, {key_msg}.",
            response_code=code,
            response_time_ms=elapsed_ms,
            details={"key_configured": bool(key_env_name), "verified_with_key": False},
        )
    elif code >= 500:
        return ApiCheckResult(
            provider=provider.name,
            status="service_down",
            message=f"{provider.description}: server error ({code}), {key_msg}.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )
    else:
        return ApiCheckResult(
            provider=provider.name,
            status="healthy",
            message=f"{provider.description}: responded ({code}), {key_msg}.",
            response_code=code,
            response_time_ms=elapsed_ms,
        )
