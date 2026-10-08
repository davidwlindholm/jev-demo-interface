"""Client for TypeSafe's Jev decision model via OpenRouter's Decisions API.

This is the only module that knows the endpoint, the request shape and the
response shape. It has no Streamlit imports and does no logging; the API key
and the situation text are never logged or printed.

Public API
----------
build_request(model, situation, noul, choice, score) -> dict
    Builds the JSON request body.
call_jev(api_key, body) -> dict
    Sends the request and returns the parsed result (see its docstring).
parse_answers(response_json) -> dict
    Converts the ``answers`` object of a response into plain Python structures.
parse_usage(response_json) -> dict
    Reads ``usage`` from a response.

Errors
------
JevApiError
    HTTP error, timeout or network error. ``kind`` tells them apart.
JevResponseError
    The response did not have the expected shape.
"""

from __future__ import annotations

import math
import time
from typing import Any

import requests

API_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "~typesafe/jev-latest"
TIMEOUT_SECONDS = 30

# Fixed question keys in the request and response.
KEY_NOUL = "ja_nej"
KEY_CHOICE = "valg"
KEY_SCORE = "skala"


class JevApiError(Exception):
    """The HTTP call failed.

    Attributes:
        kind: ``"http"`` (non-2xx status), ``"timeout"`` (no answer within
            TIMEOUT_SECONDS) or ``"network"`` (connection failed, DNS etc.).
        status: HTTP status code for ``kind == "http"``, otherwise None.
        message: Error message extracted from the response body, or None if
            the body carried none (always None for timeout and network).
        body: Response body; the decoded JSON value if the body was JSON,
            otherwise the raw text. None if there was no response.
    """

    def __init__(
        self,
        status: int | None,
        message: str | None,
        body: Any = None,
        kind: str = "http",
    ) -> None:
        self.status = status
        self.message = message
        self.body = body
        self.kind = kind
        if kind == "http":
            text = f"HTTP {status}" + (f": {message}" if message else "")
        else:
            text = kind
        super().__init__(text)


class JevResponseError(Exception):
    """The response body did not have the expected shape.

    Attributes:
        body: The response body (decoded JSON, or raw text if it was not
            JSON). Set by call_jev; None when parse_answers is called directly.
    """

    def __init__(self, message: str, body: Any = None) -> None:
        super().__init__(message)
        self.body = body


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


def build_request(
    model: str,
    situation: str,
    noul: str | None,
    choice: dict | None,
    score: dict | None,
) -> dict:
    """Build the request body for the Decisions API.

    Args:
        model: Model id, for example ``"~typesafe/jev-latest"``.
        situation: Free text, sent as ``state.situation``.
        noul: Question text for the Ja/nej block, or None if disabled.
        choice: None if disabled, otherwise
            ``{"question": str, "options": [(label, description), ...]}``.
            Rows whose label is empty after trimming are dropped. A blank
            description falls back to the label.
        score: None if disabled, otherwise
            ``{"question": str, "levels": [str, ...]}`` in scale order,
            lowest first. Rows empty after trimming are dropped.

    Returns:
        The JSON-serialisable body. Only enabled blocks are included, under
        the fixed keys ``ja_nej``, ``valg`` and ``skala``. All strings are
        trimmed. No other validation is done; the caller checks the rules in
        plan section 6.1 before sending.
    """
    questions: dict[str, dict] = {}

    if noul is not None:
        questions[KEY_NOUL] = {"type": "noul", "instructions": noul.strip()}

    if choice is not None:
        criteria: dict[str, str] = {}
        for label, description in choice["options"]:
            label = (label or "").strip()
            if not label:
                continue
            criteria[label] = (description or "").strip() or label
        questions[KEY_CHOICE] = {
            "type": "choice",
            "instructions": choice["question"].strip(),
            "criteria": criteria,
        }

    if score is not None:
        levels = [lvl.strip() for lvl in score["levels"] if lvl and lvl.strip()]
        questions[KEY_SCORE] = {
            "type": "score",
            "instructions": score["question"].strip(),
            "criteria": levels,
        }

    return {
        "model": model.strip(),
        "state": {"situation": situation.strip()},
        "questions": questions,
    }


# --------------------------------------------------------------------------
# HTTP call
# --------------------------------------------------------------------------


def _decode_body(response: requests.Response) -> Any:
    """Return the body as decoded JSON if possible, else as text."""
    try:
        return response.json()
    except ValueError:
        return response.text


def _extract_error_message(body: Any) -> str | None:
    """Find a human-readable message in an error body, if there is one."""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"].strip() or None
        if isinstance(error, str):
            return error.strip() or None
        if isinstance(body.get("message"), str):
            return body["message"].strip() or None
    return None


def call_jev(api_key: str, body: dict) -> dict:
    """Send one request to Jev. One attempt, TIMEOUT_SECONDS timeout.

    Args:
        api_key: OpenRouter API key; sent only in the Authorization header.
        body: Request body from build_request.

    Returns:
        ``{"answers": ..., "model": str | None, "usage": ...,
        "latency_ms": int, "raw": dict}`` where ``answers`` is the result of
        parse_answers, ``usage`` the result of parse_usage, ``model`` the
        concrete model that served the request, ``latency_ms`` the wall-clock
        time around the HTTP call and ``raw`` the decoded response body.

    Raises:
        JevApiError: non-2xx status, timeout or network error.
        JevResponseError: 2xx status but unexpected body; ``body`` attribute
            holds the raw body.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    start = time.perf_counter()
    try:
        response = requests.post(
            API_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS
        )
    except requests.exceptions.Timeout:
        raise JevApiError(None, None, None, kind="timeout") from None
    except requests.exceptions.RequestException:
        raise JevApiError(None, None, None, kind="network") from None
    latency_ms = round((time.perf_counter() - start) * 1000)

    raw = _decode_body(response)
    if not response.ok:
        raise JevApiError(
            response.status_code, _extract_error_message(raw), raw, kind="http"
        )
    if not isinstance(raw, dict):
        raise JevResponseError("Response body is not a JSON object", raw)

    try:
        answers = parse_answers(raw)
        usage = parse_usage(raw)
    except JevResponseError as exc:
        exc.body = raw
        raise

    model = raw.get("model")
    return {
        "answers": answers,
        "model": model if isinstance(model, str) else None,
        "usage": usage,
        "latency_ms": latency_ms,
        "raw": raw,
    }


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def _number(value: Any, what: str) -> float:
    """Return value as float, or raise JevResponseError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevResponseError(f"{what} is not a number")
    result = float(value)
    if not math.isfinite(result):
        raise JevResponseError(f"{what} is not finite")
    return result


def _optional_number(value: Any, what: str) -> float | None:
    return None if value is None else _number(value, what)


def _mapping(value: Any, what: str) -> dict:
    """Return value if it is a dict; a missing value (None) becomes {}."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise JevResponseError(f"{what} is not an object")
    return value


def _index(key: Any, what: str) -> int:
    try:
        return int(key)
    except (TypeError, ValueError):
        raise JevResponseError(f"{what} key {key!r} is not an index") from None


def _parse_noul(key: str, data: dict) -> dict:
    return {
        "type": "noul",
        "yes_probability": _number(data.get("noul"), f"{key}.noul"),
    }


def _parse_choice(key: str, data: dict) -> dict:
    chosen = data.get("choice")
    if not isinstance(chosen, str):
        raise JevResponseError(f"{key}.choice is not a string")
    probs = _mapping(data.get("probabilities"), f"{key}.probabilities")
    return {
        "type": "choice",
        "choice": chosen,
        "confidence": _optional_number(data.get("confidence"), f"{key}.confidence"),
        "probabilities": {
            str(label): _number(p, f"{key}.probabilities[{label!r}]")
            for label, p in probs.items()
        },
    }


def _parse_score(key: str, data: dict) -> dict:
    if "legend" not in data:
        raise JevResponseError(f"{key}.legend is missing")
    legend_raw = _mapping(data["legend"], f"{key}.legend")
    probs_raw = _mapping(data.get("probabilities"), f"{key}.probabilities")
    legend = {}
    for k, text in legend_raw.items():
        if not isinstance(text, str):
            raise JevResponseError(f"{key}.legend[{k!r}] is not a string")
        legend[_index(k, f"{key}.legend")] = text
    probabilities = {
        _index(k, f"{key}.probabilities"): _number(p, f"{key}.probabilities[{k!r}]")
        for k, p in probs_raw.items()
    }
    return {
        "type": "score",
        "score": _number(data.get("score"), f"{key}.score"),
        "confidence": _optional_number(data.get("confidence"), f"{key}.confidence"),
        "legend": dict(sorted(legend.items())),
        "probabilities": dict(sorted(probabilities.items())),
    }


_PARSERS = {"noul": _parse_noul, "choice": _parse_choice, "score": _parse_score}


def parse_answers(response_json: Any) -> dict[str, dict]:
    """Convert the ``answers`` of a response into plain Python structures.

    Returns a dict keyed by question key (``ja_nej``, ``valg``, ``skala``, or
    whatever keys the response carries), in response order. Each value is one
    of:

    - ``{"type": "noul", "yes_probability": float}`` (no confidence exists
      for Noul)
    - ``{"type": "choice", "choice": str, "confidence": float | None,
      "probabilities": {label: float}}``
    - ``{"type": "score", "score": float, "confidence": float | None,
      "legend": {int: str}, "probabilities": {int: float}}``; legend and
      probabilities have integer level indexes, sorted ascending, and
      ``score`` may be non-integer.

    ``confidence`` None means "not reported". A missing ``probabilities``
    becomes an empty dict. Probabilities are floats in 0..1.

    Raises:
        JevResponseError: missing or malformed ``answers``, an unknown answer
            type, or a required field missing or of the wrong type.
    """
    if not isinstance(response_json, dict):
        raise JevResponseError("Response is not a JSON object")
    answers = response_json.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise JevResponseError("Response has no answers object")

    parsed: dict[str, dict] = {}
    for key, data in answers.items():
        if not isinstance(data, dict):
            raise JevResponseError(f"Answer {key!r} is not an object")
        parser = _PARSERS.get(data.get("type"))
        if parser is None:
            raise JevResponseError(f"Answer {key!r} has unknown type {data.get('type')!r}")
        parsed[key] = parser(key, data)
    return parsed


def parse_usage(response_json: dict) -> dict:
    """Read token counts and cost from a response.

    Returns ``{"input_tokens": int | None, "output_tokens": int | None,
    "cost": float | None}``. Any missing field (or a missing ``usage``) is
    None; ``cost`` is in USD.

    Raises:
        JevResponseError: ``usage`` or one of its fields has the wrong type.
    """
    usage = _mapping(response_json.get("usage"), "usage")

    def tokens(name: str) -> int | None:
        value = _optional_number(usage.get(name), f"usage.{name}")
        return None if value is None else int(value)

    return {
        "input_tokens": tokens("input_tokens"),
        "output_tokens": tokens("output_tokens"),
        "cost": _optional_number(usage.get("cost"), "usage.cost"),
    }
