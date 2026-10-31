"""Bounded unambiguous JSON and privacy-safe fixture export."""
import json
import os

from pydantic import BaseModel

MAX_WIRE_BYTES = 16384


class ContractError(ValueError):
    """Safe error codes only: never echo untrusted values or provider exceptions."""
    def __init__(self, code, stage="validation"):
        self.code, self.stage = code, stage
        super().__init__(code)

    def report(self):
        return dict(schema_version="banking-error-v1", code=self.code, stage=self.stage,
                    retryable=False, fixture_only=True)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ContractError("duplicate_json_key", "parse")
        value[key] = item
    return value


def _nonfinite(_):
    raise ContractError("nonfinite_json_number", "parse")


def parse_object(body):
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_WIRE_BYTES:
        raise ContractError("invalid_body_size", "parse")
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
        if not isinstance(value, dict):
            raise ContractError("expected_json_object", "parse")
        canonical_bytes(value)  # rejects overflowed JSON floats, surrogates and nesting failures
        return value
    except ContractError:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        raise ContractError("invalid_json", "parse") from None


def canonical_bytes(value, limit=MAX_WIRE_BYTES):
    """Sorted UTF-8 JSON; no Unicode/path normalization, exponent or float coercion."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        raise ContractError("noncanonical_value", "binding") from None
    if len(encoded) > limit:
        raise ContractError("canonical_value_too_large", "binding")
    return encoded


def public_view(value):
    """Explicit fixture exports, not a universal arbitrary-secret detector.

    Full intent text is withheld. Binding commitments are keyed, so exporting them
    does not publish a plain password fingerprint. No fixture key is serialized.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: "[WITHHELD]" if key.lower() in {"password", "user_request", "api_key", "secret", "token"}
                else public_view(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_view(item) for item in value]
    if isinstance(value, str):
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
            if os.getenv(key): value = value.replace(os.environ[key], "[WITHHELD]")
    return value
