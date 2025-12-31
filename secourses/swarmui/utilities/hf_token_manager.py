from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal
import os

import requests

# Public endpoint used by Hugging Face web + hub clients.
# - 200 => token valid
# - 401/403 => token invalid or lacks auth
_WHOAMI_URL = "https://huggingface.co/api/whoami-v2"

TokenStatus = Literal["valid", "invalid", "unknown", "missing"]


def _normalize_token(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip()
    return token or None


@lru_cache(maxsize=64)
def _check_token_cached(token: str) -> TokenStatus:
    """
    Cached token validity check.

    IMPORTANT: This uses a short timeout and treats network failures as "unknown"
    (not "invalid") so we don't discard tokens just because HF is temporarily
    unreachable.
    """
    try:
        resp = requests.get(
            _WHOAMI_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except requests.RequestException:
        return "unknown"

    if resp.status_code == 200:
        return "valid"
    if resp.status_code in (401, 403):
        return "invalid"
    return "unknown"


def check_hf_token(token: str | None) -> TokenStatus:
    token = _normalize_token(token)
    if not token:
        return "missing"
    return _check_token_cached(token)


def get_env_hf_token(env_var: str = "HUGGING_FACE_HUB_TOKEN") -> str | None:
    """Read the preferred env-var token (your app-level token)."""
    return _normalize_token(os.environ.get(env_var))


def get_system_hf_token() -> str | None:
    """
    Read the user's "system-wide" Hugging Face token if available.

    This covers tokens created via `huggingface-cli login` and common env vars
    used by `huggingface_hub` itself (HF_TOKEN / HUGGINGFACE_HUB_TOKEN).
    """
    # 1) System-wide env vars (do NOT include HUGGING_FACE_HUB_TOKEN here, because that is the
    #    app-preferred env var and must NOT override the user's stored login token when invalid).
    for env_name in ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        token = _normalize_token(os.environ.get(env_name))
        if token:
            return token

    # 2) Token stored on disk by `hf auth login` / `huggingface_hub.login`
    #    Use huggingface_hub constants path if available, otherwise fall back to a reasonable default.
    try:
        import huggingface_hub.constants as hf_constants  # type: ignore

        token_path = Path(hf_constants.HF_TOKEN_PATH)
        if token_path.exists():
            token = _normalize_token(token_path.read_text(encoding="utf-8", errors="ignore"))
            if token:
                return token
    except Exception:
        pass

    # 3) Stored tokens file (may contain multiple named tokens)
    try:
        from huggingface_hub.utils import get_stored_tokens  # type: ignore

        stored = get_stored_tokens() or {}
        if isinstance(stored, dict) and stored:
            if "default" in stored:
                token = _normalize_token(stored.get("default"))
                if token:
                    return token
            # Otherwise, return any token
            for _name, tok in stored.items():
                token = _normalize_token(tok)
                if token:
                    return token
    except Exception:
        pass
    return None


def _mask_token(token: str | None) -> str:
    if not token:
        return "<none>"
    if len(token) < 12:
        return "<hidden>"
    return f"{token[:6]}...{token[-4:]}"


@dataclass(frozen=True)
class ResolvedHfToken:
    """
    Result of token resolution.

    - `token`: string token to use, or None if we should proceed without auth
    - `hub_token`: a value suitable for huggingface_hub APIs (string or False)
    """

    token: str | None
    source: Literal["env", "system", "none"]
    env_status: TokenStatus
    system_status: TokenStatus

    @property
    def hub_token(self) -> str | bool:
        # False forces huggingface_hub to NOT use any cached/stored token.
        return self.token if self.token else False

    @property
    def masked(self) -> str:
        return _mask_token(self.token)

    def summary(self) -> str:
        if self.source == "env":
            return f"HuggingFace token: using env `HUGGING_FACE_HUB_TOKEN` ({self.env_status})"
        if self.source == "system":
            return f"HuggingFace token: using system token ({self.system_status})"
        # none
        details = []
        if self.env_status != "missing":
            details.append(f"env={self.env_status}")
        if self.system_status != "missing":
            details.append(f"system={self.system_status}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"HuggingFace token: proceeding WITHOUT token{suffix}"


def resolve_hf_token(
    *,
    preferred_env_var: str = "HUGGING_FACE_HUB_TOKEN",
) -> ResolvedHfToken:
    """
    Resolve token in the requested order:
    1) preferred app env var (HUGGING_FACE_HUB_TOKEN)
    2) user's system-wide HF token (huggingface-cli login / HF_TOKEN / HUGGINGFACE_HUB_TOKEN)
    3) none (force no-token)
    """
    env_token = get_env_hf_token(preferred_env_var)
    env_status = check_hf_token(env_token)

    if env_token and env_status != "invalid":
        return ResolvedHfToken(
            token=env_token,
            source="env",
            env_status=env_status,
            system_status="missing",
        )

    system_token = get_system_hf_token()
    system_status = check_hf_token(system_token)

    if system_token and system_status != "invalid":
        return ResolvedHfToken(
            token=system_token,
            source="system",
            env_status=env_status,
            system_status=system_status,
        )

    return ResolvedHfToken(
        token=None,
        source="none",
        env_status=env_status,
        system_status=system_status,
    )



