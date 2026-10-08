"""Unit tests for jev_client. No network access."""

import copy
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jev_client  # noqa: E402
from jev_client import (  # noqa: E402
    JevApiError,
    JevResponseError,
    build_request,
    call_jev,
    parse_answers,
    parse_usage,
)

FIXTURE = Path(__file__).parent / "fixtures" / "response_all_three.json"


@pytest.fixture
def response():
    """The recorded real response, freshly loaded for each test."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# build_request
# --------------------------------------------------------------------------

CHOICE = {"question": "Hvem?", "options": [("Anna", "Spørg Anna"), ("Jonas", "")]}
SCORE = {"question": "Hvor meget?", "levels": ["Lav", "Mellem", "Høj"]}


def test_build_request_all_blocks():
    body = build_request("~typesafe/jev-latest", "Situation", "Ja?", CHOICE, SCORE)
    assert body["model"] == "~typesafe/jev-latest"
    assert body["state"] == {"situation": "Situation"}
    assert body["questions"] == {
        "ja_nej": {"type": "noul", "instructions": "Ja?"},
        "valg": {
            "type": "choice",
            "instructions": "Hvem?",
            "criteria": {"Anna": "Spørg Anna", "Jonas": "Jonas"},
        },
        "skala": {
            "type": "score",
            "instructions": "Hvor meget?",
            "criteria": ["Lav", "Mellem", "Høj"],
        },
    }


@pytest.mark.parametrize(
    "noul, choice, score, expected",
    [
        ("Ja?", None, None, ["ja_nej"]),
        (None, CHOICE, None, ["valg"]),
        (None, None, SCORE, ["skala"]),
        ("Ja?", None, SCORE, ["ja_nej", "skala"]),
    ],
)
def test_build_request_only_enabled_blocks(noul, choice, score, expected):
    body = build_request("m", "s", noul, choice, score)
    assert list(body["questions"]) == expected


def test_build_request_blank_description_falls_back_to_label():
    choice = {"question": "q", "options": [("Æble", ""), ("Pære", "   "), ("Kiwi", None)]}
    criteria = build_request("m", "s", None, choice, None)["questions"]["valg"]["criteria"]
    assert criteria == {"Æble": "Æble", "Pære": "Pære", "Kiwi": "Kiwi"}


def test_build_request_drops_empty_rows_and_trims():
    choice = {
        "question": " q ",
        "options": [("", "orphan description"), ("  A  ", " desc "), ("   ", ""), ("B", "b")],
    }
    score = {"question": "q", "levels": ["", " Lav ", "   ", "Høj", None]}
    questions = build_request("m", "s", None, choice, score)["questions"]
    assert questions["valg"]["instructions"] == "q"
    assert questions["valg"]["criteria"] == {"A": "desc", "B": "b"}
    assert questions["skala"]["criteria"] == ["Lav", "Høj"]


def test_build_request_keeps_score_order():
    score = {"question": "q", "levels": ["3", "1", "2"]}
    assert build_request("m", "s", None, None, score)["questions"]["skala"]["criteria"] == [
        "3",
        "1",
        "2",
    ]


# --------------------------------------------------------------------------
# parse_answers
# --------------------------------------------------------------------------


def test_parse_fixture_all_three_types(response):
    answers = parse_answers(response)
    assert list(answers) == ["ja_nej", "valg", "skala"]

    noul = answers["ja_nej"]
    assert noul == {"type": "noul", "yes_probability": pytest.approx(0.39)}
    assert "confidence" not in noul

    choice = answers["valg"]
    assert choice["type"] == "choice"
    assert choice["choice"] == "Vejledende spørgsmål"
    assert choice["confidence"] == pytest.approx(0.34)
    assert set(choice["probabilities"]) == {
        "Lyt videre",
        "Vejledende spørgsmål",
        "Tilbage til opgaven",
        "Inviter den stille",
    }
    assert all(isinstance(p, float) for p in choice["probabilities"].values())
    assert max(choice["probabilities"], key=choice["probabilities"].get) == choice["choice"]

    score = answers["skala"]
    assert score["type"] == "score"
    assert score["score"] == pytest.approx(2.01)
    assert score["confidence"] == pytest.approx(0.99)
    assert list(score["legend"]) == [0, 1, 2, 3]
    assert score["legend"][3] == "Åben konflikt"
    assert list(score["probabilities"]) == [0, 1, 2, 3]
    assert sum(score["probabilities"].values()) == pytest.approx(1.0)


def test_parse_usage_from_fixture(response):
    usage = parse_usage(response)
    assert usage["input_tokens"] == 612
    assert usage["output_tokens"] == 96
    assert usage["cost"] > 0


def test_parse_usage_cost_optional(response):
    del response["usage"]["cost"]
    assert parse_usage(response)["cost"] is None
    del response["usage"]
    assert parse_usage(response) == {"input_tokens": None, "output_tokens": None, "cost": None}


@pytest.mark.parametrize("key", ["valg", "skala"])
def test_missing_confidence_is_none_not_zero(response, key):
    del response["answers"][key]["confidence"]
    assert parse_answers(response)[key]["confidence"] is None


@pytest.mark.parametrize("key", ["valg", "skala"])
def test_missing_probabilities_is_empty_map(response, key):
    del response["answers"][key]["probabilities"]
    assert parse_answers(response)[key]["probabilities"] == {}


def test_non_integer_score(response):
    response["answers"]["skala"]["score"] = 1.84
    assert parse_answers(response)["skala"]["score"] == pytest.approx(1.84)


def test_integer_score_becomes_float(response):
    response["answers"]["skala"]["score"] = 2
    score = parse_answers(response)["skala"]["score"]
    assert score == 2.0 and isinstance(score, float)


def _break(response, path, value):
    """Set response[path...] = value, or delete it if value is ... ."""
    target = response
    for part in path[:-1]:
        target = target[part]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value


@pytest.mark.parametrize(
    "path, value",
    [
        (["answers"], ...),
        (["answers"], []),
        (["answers"], {}),
        (["answers", "ja_nej"], "0.5"),
        (["answers", "ja_nej", "type"], "ranking"),
        (["answers", "ja_nej", "type"], ...),
        (["answers", "ja_nej", "noul"], ...),
        (["answers", "ja_nej", "noul"], "0.9"),
        (["answers", "ja_nej", "noul"], True),
        (["answers", "valg", "choice"], ...),
        (["answers", "valg", "probabilities"], [0.5, 0.5]),
        (["answers", "valg", "confidence"], "high"),
        (["answers", "skala", "score"], ...),
        (["answers", "skala", "legend"], ...),
        (["answers", "skala", "legend", "0"], 7),
        (["answers", "skala", "probabilities"], {"low": 0.5}),
    ],
)
def test_unknown_shape_raises(response, path, value):
    _break(response, path, value)
    with pytest.raises(JevResponseError):
        parse_answers(response)


@pytest.mark.parametrize("not_a_response", [None, [], "text", 42])
def test_non_object_response_raises(not_a_response):
    with pytest.raises(JevResponseError):
        parse_answers(not_a_response)


# --------------------------------------------------------------------------
# call_jev with a mocked requests.post
# --------------------------------------------------------------------------


def _fake_response(status, payload):
    resp = requests.Response()
    resp.status_code = status
    resp._content = (
        payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
    )
    return resp


def test_call_jev_success(response):
    with mock.patch.object(jev_client.requests, "post", return_value=_fake_response(200, response)) as post:
        result = call_jev("sk-test", {"model": "m"})
    args, kwargs = post.call_args
    assert args[0] == jev_client.API_URL
    assert kwargs["timeout"] == 30
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert result["model"] == "typesafe/jev-1.13-20260917"
    assert result["answers"]["valg"]["choice"] == "Vejledende spørgsmål"
    assert result["usage"]["input_tokens"] == 612
    assert isinstance(result["latency_ms"], int)
    assert result["raw"] == response


def test_call_jev_http_error_extracts_message():
    body = {"error": {"code": 401, "message": "No auth credentials found"}}
    with mock.patch.object(jev_client.requests, "post", return_value=_fake_response(401, body)):
        with pytest.raises(JevApiError) as info:
            call_jev("bad", {})
    err = info.value
    assert (err.kind, err.status, err.message, err.body) == ("http", 401, "No auth credentials found", body)


def test_call_jev_http_error_without_message():
    with mock.patch.object(jev_client.requests, "post", return_value=_fake_response(502, "Bad gateway")):
        with pytest.raises(JevApiError) as info:
            call_jev("k", {})
    assert (info.value.status, info.value.message, info.value.body) == (502, None, "Bad gateway")


@pytest.mark.parametrize(
    "exc, kind",
    [
        (requests.exceptions.ReadTimeout(), "timeout"),
        (requests.exceptions.ConnectTimeout(), "timeout"),
        (requests.exceptions.ConnectionError(), "network"),
    ],
)
def test_call_jev_timeout_and_network(exc, kind):
    with mock.patch.object(jev_client.requests, "post", side_effect=exc):
        with pytest.raises(JevApiError) as info:
            call_jev("k", {})
    assert (info.value.kind, info.value.status, info.value.body) == (kind, None, None)


def test_call_jev_bad_shape_carries_body(response):
    bad = copy.deepcopy(response)
    bad["answers"]["valg"]["type"] = "ranking"
    with mock.patch.object(jev_client.requests, "post", return_value=_fake_response(200, bad)):
        with pytest.raises(JevResponseError) as info:
            call_jev("k", {})
    assert info.value.body == bad
