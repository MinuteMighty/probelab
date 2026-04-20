"""Pattern definitions for dependency scanning.

Detects external web pages, API SDKs, and API endpoints in source code.
Each pattern maps to a dependency type and provides enough context to
auto-generate a probe YAML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Dependency:
    """A discovered external dependency."""

    kind: Literal["web", "api"]
    url: str | None = None
    source_file: str = ""
    source_line: int = 0
    provider: str = ""          # e.g., "openai", "stripe", "replicate"
    env_key: str = ""           # e.g., "OPENAI_API_KEY"
    selectors: list[str] = field(default_factory=list)
    description: str = ""
    confidence: float = 1.0     # 0.0-1.0, how sure we are this is real


# ─────────────────────────────────────────────────────────────────────
# Known API providers
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ApiProvider:
    """Known API provider pattern."""

    name: str
    import_patterns: list[str]          # Python import strings
    js_import_patterns: list[str]       # JS/TS import strings
    env_keys: list[str]                 # Common env var names
    health_url: str                     # URL to probe for availability
    description: str = ""


KNOWN_PROVIDERS: list[ApiProvider] = [
    ApiProvider(
        name="openai",
        import_patterns=["import openai", "from openai"],
        js_import_patterns=["from 'openai'", 'from "openai"', "require('openai')"],
        env_keys=["OPENAI_API_KEY", "OPENAI_KEY"],
        health_url="https://api.openai.com/v1/models",
        description="OpenAI API (GPT, DALL-E, Whisper)",
    ),
    ApiProvider(
        name="anthropic",
        import_patterns=["import anthropic", "from anthropic"],
        js_import_patterns=["from '@anthropic-ai/sdk'", "require('@anthropic-ai/sdk')"],
        env_keys=["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        health_url="https://api.anthropic.com/v1/messages",
        description="Anthropic API (Claude)",
    ),
    ApiProvider(
        name="google-gemini",
        import_patterns=["import google.generativeai", "from google.generativeai", "import google.genai", "from google.genai"],
        js_import_patterns=["from '@google/generative-ai'", "require('@google/generative-ai')"],
        env_keys=["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"],
        health_url="https://generativelanguage.googleapis.com/v1beta/models",
        description="Google Gemini API",
    ),
    ApiProvider(
        name="replicate",
        import_patterns=["import replicate", "from replicate"],
        js_import_patterns=["from 'replicate'", "require('replicate')"],
        env_keys=["REPLICATE_API_TOKEN"],
        health_url="https://api.replicate.com/v1/models",
        description="Replicate API (ML models)",
    ),
    ApiProvider(
        name="stripe",
        import_patterns=["import stripe", "from stripe"],
        js_import_patterns=["from 'stripe'", "require('stripe')"],
        env_keys=["STRIPE_SECRET_KEY", "STRIPE_API_KEY", "STRIPE_KEY"],
        health_url="https://api.stripe.com/v1/charges",
        description="Stripe payments API",
    ),
    ApiProvider(
        name="aws",
        import_patterns=["import boto3", "from boto3"],
        js_import_patterns=["from '@aws-sdk'", "require('@aws-sdk')"],
        env_keys=["AWS_ACCESS_KEY_ID"],
        health_url="https://sts.amazonaws.com",
        description="Amazon Web Services",
    ),
    ApiProvider(
        name="twilio",
        import_patterns=["from twilio", "import twilio"],
        js_import_patterns=["from 'twilio'", "require('twilio')"],
        env_keys=["TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID"],
        health_url="https://api.twilio.com/2010-04-01",
        description="Twilio messaging/voice API",
    ),
    ApiProvider(
        name="sendgrid",
        import_patterns=["import sendgrid", "from sendgrid"],
        js_import_patterns=["from '@sendgrid/mail'", "require('@sendgrid/mail')"],
        env_keys=["SENDGRID_API_KEY"],
        health_url="https://api.sendgrid.com/v3/mail/send",
        description="SendGrid email API",
    ),
    ApiProvider(
        name="supabase",
        import_patterns=["from supabase", "import supabase"],
        js_import_patterns=["from '@supabase/supabase-js'", "require('@supabase/supabase-js')"],
        env_keys=["SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_ANON_KEY"],
        health_url="",  # URL is project-specific
        description="Supabase (Postgres + Auth + Storage)",
    ),
    ApiProvider(
        name="firebase",
        import_patterns=["from firebase_admin", "import firebase_admin"],
        js_import_patterns=["from 'firebase'", "from 'firebase/app'"],
        env_keys=["FIREBASE_API_KEY", "FIREBASE_PROJECT_ID"],
        health_url="",  # Project-specific
        description="Google Firebase",
    ),
    ApiProvider(
        name="huggingface",
        import_patterns=["from huggingface_hub", "import huggingface_hub", "from transformers"],
        js_import_patterns=["from '@huggingface/inference'"],
        env_keys=["HF_TOKEN", "HUGGINGFACE_TOKEN", "HF_API_KEY"],
        health_url="https://huggingface.co/api/models",
        description="Hugging Face API (models, datasets)",
    ),
    ApiProvider(
        name="cohere",
        import_patterns=["import cohere", "from cohere"],
        js_import_patterns=["from 'cohere-ai'"],
        env_keys=["COHERE_API_KEY", "CO_API_KEY"],
        health_url="https://api.cohere.ai/v1/models",
        description="Cohere NLP API",
    ),
    ApiProvider(
        name="mistral",
        import_patterns=["from mistralai", "import mistralai"],
        js_import_patterns=["from '@mistralai/mistralai'"],
        env_keys=["MISTRAL_API_KEY"],
        health_url="https://api.mistral.ai/v1/models",
        description="Mistral AI API",
    ),
]

_PROVIDER_BY_NAME: dict[str, ApiProvider] = {p.name: p for p in KNOWN_PROVIDERS}


def get_provider(name: str) -> ApiProvider | None:
    return _PROVIDER_BY_NAME.get(name)


# ─────────────────────────────────────────────────────────────────────
# URL extraction patterns
# ─────────────────────────────────────────────────────────────────────

# Matches http/https URLs in source code (quotes, backticks, or bare)
URL_PATTERN = re.compile(
    r"""(?:["'`])?(https?://[^\s"'`<>,;)\]}{]+)(?:["'`])?""",
    re.IGNORECASE,
)

# Markdown link pattern
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")

# CSS selector patterns in Python
PY_SELECTOR_PATTERNS = [
    re.compile(r"""\.select\(\s*["']([^"']+)["']\s*\)"""),           # bs4 .select()
    re.compile(r"""\.select_one\(\s*["']([^"']+)["']\s*\)"""),       # bs4 .select_one()
    re.compile(r"""\.css\(\s*["']([^"']+)["']\s*\)"""),              # selectolax/parsel
    re.compile(r"""querySelector\(\s*["']([^"']+)["']\s*\)"""),      # JS in Python strings
    re.compile(r"""querySelectorAll\(\s*["']([^"']+)["']\s*\)"""),
]

# CSS selector patterns in JavaScript
JS_SELECTOR_PATTERNS = [
    re.compile(r"""querySelector\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""querySelectorAll\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""\.\$\(\s*["']([^"']+)["']\s*\)"""),              # page.$()
    re.compile(r"""\.\$\$\(\s*["']([^"']+)["']\s*\)"""),            # page.$$()
    re.compile(r"""waitForSelector\(\s*["']([^"']+)["']\s*\)"""),
]

# Environment variable patterns
ENV_KEY_PATTERN = re.compile(
    r"""(?:^|\s)([A-Z][A-Z0-9_]*(?:_API_KEY|_KEY|_TOKEN|_SECRET|_API_TOKEN|_AUTH_TOKEN))\s*=""",
)

# URLs to skip (internal, localhost, example, etc.)
SKIP_URL_PATTERNS = re.compile(
    r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|example\.com|"
    r"test\.com|placeholder|schema\.org|www\.w3\.org|"
    r"schemas\.openxmlformats\.org|schemas\.microsoft\.com|purl\.org|"
    r"www\.ecma-international\.org|tc39\.es|"
    r"fonts\.googleapis\.com|fonts\.gstatic\.com|"
    r"cdn\.|unpkg\.com|cdnjs\.|jsdelivr\.net|"
    r"registry\.npmjs\.org|registry\.yarnpkg\.com|"
    r"img\.shields\.io|badge|"
    r"playwright\.dev|"
    r".*\.svg$|.*\.png$|.*\.jpg$|.*\.gif$|.*\.ico$|.*\.webp$|"
    r".*\.css$|.*\.js$|.*\.mjs$|.*\.woff2?$|.*\.ttf$|.*\.eot$|"
    r".*\.map$|.*\.tgz$)",
    re.IGNORECASE,
)

# File extensions to scan
SCAN_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json",
    ".env", ".env.example", ".env.local",
    ".md", ".mdx", ".rst",
}

# Directories to skip
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "dist", "build", ".eggs", "*.egg-info",
    ".probelab", ".vercel", ".next", ".nuxt", ".output",
    "coverage", ".nyc_output", ".turbo",
}

# Files to skip entirely (lock files, generated code)
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "composer.lock",
    "Gemfile.lock", "Cargo.lock", "go.sum",
}
