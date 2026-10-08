"""Streamlit UI for the Jev demo tool (plan sections 5, 6 and 8).

Layout, form state and result rendering only. All API knowledge lives in
jev_client; the presets live in presets.

State model
-----------
Everything lives in ``st.session_state``:

- ``api_key``, ``model``, ``preset``: sidebar widgets. The key is held in
  session state only; it is never written, logged or put in a URL.
- ``situation``, ``<block>_enabled``, ``<block>_question``: form widgets.
- ``option_ids`` and ``level_ids``: ordered lists of row ids. Each row id is
  taken from the counter ``next_row_id`` and never reused, and the row's
  widgets are keyed ``opt_label_<id>``, ``opt_desc_<id>`` and ``lvl_<id>``.
  Removing a row deletes its id and its keys, so the other rows keep their
  own keys and values; nothing shifts.
- ``result`` / ``error``: what the result panel shows, from the last click.

Widget-backed keys may only be written before the widget is created in a
run, so preset loading, add row and remove row are ``on_click``/``on_change``
callbacks, which Streamlit runs before the script reruns.

No persistence, no logging, no query parameters. Unexpected exceptions go
to stderr only.
"""

from __future__ import annotations

import html
import os
import sys
import traceback
from typing import Any

import streamlit as st

import jev_client
from jev_client import (
    DEFAULT_MODEL,
    KEY_CHOICE,
    KEY_NOUL,
    KEY_SCORE,
    JevApiError,
    JevResponseError,
    build_request,
)
from presets import PRESETS

# --------------------------------------------------------------------------
# UI text (plan section 8, plus the messages in sections 6.1 and 6.3)
# --------------------------------------------------------------------------

TEXT = {
    "title": "Jev-demo",
    "sidebar_key": "API-nøgle",
    "sidebar_model": "Model",
    "sidebar_preset": "Scenarie",
    "preset_blank": "(tomt)",
    "situation": "Situation",
    "block_noul": "Ja/nej (Noul)",
    "block_choice": "Valg (Choice)",
    "block_score": "Skala (Score)",
    "enable": "Medtag",
    "question": "Spørgsmål",
    "option_label": "Svarmulighed",
    "option_desc": "Beskrivelse (valgfri)",
    "add_option": "Tilføj svarmulighed",
    "level": "Niveau",
    "add_level": "Tilføj niveau",
    "levels_hint": "Laveste niveau først",
    "remove": "Fjern",
    "ask": "Spørg Jev",
    "yes_probability": "Sandsynlighed for ja",
    "chosen": "Valgt svar",
    "top_probability": "Højeste sandsynlighed",
    "confidence": "Sikkerhed",
    "not_reported": "ikke oplyst",
    "latency": "Svartid",
    "cost": "Pris",
    "tokens": "Tokens (ind / ud)",
    "model_used": "Model",
    "show_json": "Vis forespørgsel og svar (JSON)",
    "request_json": "Forespørgsel",
    "response_json": "Svar",
    # Not in section 8; needed for the Skala headline ("1,8 af 0 til 2"),
    # the spinner and the error-body caption in the JSON expander.
    "score_range": "{score} af {low} til {high}",
    "asking": "Spørger Jev ...",
    "error_body_json": "Fejlsvar",
    # Section 6.1: validation before sending.
    "v_key_empty": "Indtast en API-nøgle i sidepanelet.",
    "v_situation_empty": "Skriv en situation først.",
    "v_no_block": "Vælg mindst ét spørgsmål.",
    "v_question_missing": "Spørgsmålet under {block} mangler.",
    "v_choice_too_few": "Valg kræver mindst to svarmuligheder.",
    "v_choice_not_unique": "Svarmulighederne skal være forskellige.",
    "v_score_too_few": "Skala kræver mindst to niveauer.",
    # Section 6.3: errors.
    "e_401": "API-nøglen blev afvist.",
    "e_402": "Der er ikke kredit på OpenRouter-kontoen.",
    "e_404": "Modellen blev ikke fundet: {model}.",
    "e_413": "Situationen er for lang.",
    "e_rejected": "OpenRouter afviste forespørgslen: {message}.",
    "e_rejected_no_message": "OpenRouter afviste forespørgslen.",
    "e_429": "For mange kald. Prøv igen om et øjeblik.",
    "e_timeout": "Jev svarede ikke inden for 30 sekunder.",
    "e_network": "Kunne ikke forbinde til OpenRouter.",
    "e_response_shape": "Uventet svar fra Jev. Se rådata nedenfor.",
    # Not in the table: any other HTTP status, and a bug in this tool.
    "e_http_other": "OpenRouter svarede med fejl {status}.",
    "e_unexpected": "Der opstod en uventet fejl i værktøjet. Se terminalen.",
}

# Danish block names used in "Spørgsmålet under <blokknavn> mangler."
BLOCK_NAMES = {
    KEY_NOUL: TEXT["block_noul"].partition(" (")[0],
    KEY_CHOICE: TEXT["block_choice"].partition(" (")[0],
    KEY_SCORE: TEXT["block_score"].partition(" (")[0],
}

BLANK_OPTION_ROWS = 4
BLANK_LEVEL_ROWS = 3


# --------------------------------------------------------------------------
# Session state: initialisation, rows, preset loading
# --------------------------------------------------------------------------


def _new_row_id() -> int:
    ss = st.session_state
    rid = ss["next_row_id"]
    ss["next_row_id"] = rid + 1
    return rid


def _set_option_rows(options: list[tuple[str, str]]) -> None:
    """Replace all option rows. Old row keys are dropped, new ids allocated."""
    ss = st.session_state
    for rid in ss.get("option_ids", []):
        ss.pop(f"opt_label_{rid}", None)
        ss.pop(f"opt_desc_{rid}", None)
    ids = []
    for label, desc in options:
        rid = _new_row_id()
        ss[f"opt_label_{rid}"] = label
        ss[f"opt_desc_{rid}"] = desc
        ids.append(rid)
    ss["option_ids"] = ids


def _set_level_rows(levels: list[str]) -> None:
    """Replace all level rows. Old row keys are dropped, new ids allocated."""
    ss = st.session_state
    for rid in ss.get("level_ids", []):
        ss.pop(f"lvl_{rid}", None)
    ids = []
    for text in levels:
        rid = _new_row_id()
        ss[f"lvl_{rid}"] = text
        ids.append(rid)
    ss["level_ids"] = ids


def _apply_form(
    situation: str, noul: dict, choice: dict, score: dict
) -> None:
    """Write a whole form (preset shape, see presets.py) into session state."""
    ss = st.session_state
    ss["situation"] = situation
    ss["noul_enabled"] = bool(noul["enabled"])
    ss["noul_question"] = noul["question"]
    ss["choice_enabled"] = bool(choice["enabled"])
    ss["choice_question"] = choice["question"]
    _set_option_rows([(lbl, desc) for lbl, desc in choice["options"]])
    ss["score_enabled"] = bool(score["enabled"])
    ss["score_question"] = score["question"]
    _set_level_rows(list(score["levels"]))


def _apply_blank_form() -> None:
    _apply_form(
        "",
        {"enabled": False, "question": ""},
        {
            "enabled": False,
            "question": "",
            "options": [("", "")] * BLANK_OPTION_ROWS,
        },
        {"enabled": False, "question": "", "levels": [""] * BLANK_LEVEL_ROWS},
    )


def _init_state() -> None:
    ss = st.session_state
    if ss.get("initialised"):
        return
    ss["initialised"] = True
    ss["next_row_id"] = 0
    # Pre-filled from the environment; lives in session state only.
    ss["api_key"] = os.environ.get("OPENROUTER_API_KEY", "")
    ss["model"] = DEFAULT_MODEL
    ss["preset"] = TEXT["preset_blank"]
    ss["result"] = None
    ss["error"] = None
    _apply_blank_form()


# Callbacks (run before the rerun, so widget-backed keys may be written).


def _on_preset_change() -> None:
    name = st.session_state["preset"]
    preset = PRESETS.get(name)
    if preset is None:
        _apply_blank_form()
    else:
        _apply_form(
            preset["situation"], preset["noul"], preset["choice"], preset["score"]
        )


def _add_option() -> None:
    ss = st.session_state
    rid = _new_row_id()
    ss[f"opt_label_{rid}"] = ""
    ss[f"opt_desc_{rid}"] = ""
    ss["option_ids"] = ss["option_ids"] + [rid]


def _remove_option(rid: int) -> None:
    ss = st.session_state
    ss["option_ids"] = [i for i in ss["option_ids"] if i != rid]
    ss.pop(f"opt_label_{rid}", None)
    ss.pop(f"opt_desc_{rid}", None)


def _add_level() -> None:
    ss = st.session_state
    rid = _new_row_id()
    ss[f"lvl_{rid}"] = ""
    ss["level_ids"] = ss["level_ids"] + [rid]


def _remove_level(rid: int) -> None:
    ss = st.session_state
    ss["level_ids"] = [i for i in ss["level_ids"] if i != rid]
    ss.pop(f"lvl_{rid}", None)


# --------------------------------------------------------------------------
# Reading and validating the form
# --------------------------------------------------------------------------


def _read_form() -> dict:
    """Snapshot of the form from session state (untrimmed)."""
    ss = st.session_state
    return {
        "situation": ss["situation"],
        "noul": {"enabled": ss["noul_enabled"], "question": ss["noul_question"]},
        "choice": {
            "enabled": ss["choice_enabled"],
            "question": ss["choice_question"],
            "options": [
                (ss[f"opt_label_{rid}"], ss[f"opt_desc_{rid}"])
                for rid in ss["option_ids"]
            ],
        },
        "score": {
            "enabled": ss["score_enabled"],
            "question": ss["score_question"],
            "levels": [ss[f"lvl_{rid}"] for rid in ss["level_ids"]],
        },
    }


def _validate(api_key: str, form: dict) -> list[str]:
    """Section 6.1 rules. Returns all applicable messages, in table order."""
    errors: list[str] = []
    if not api_key.strip():
        errors.append(TEXT["v_key_empty"])
    if not form["situation"].strip():
        errors.append(TEXT["v_situation_empty"])

    noul, choice, score = form["noul"], form["choice"], form["score"]
    if not (noul["enabled"] or choice["enabled"] or score["enabled"]):
        errors.append(TEXT["v_no_block"])

    for key, block in ((KEY_NOUL, noul), (KEY_CHOICE, choice), (KEY_SCORE, score)):
        if block["enabled"] and not block["question"].strip():
            errors.append(TEXT["v_question_missing"].format(block=BLOCK_NAMES[key]))

    if choice["enabled"]:
        labels = [lbl.strip() for lbl, _ in choice["options"] if lbl.strip()]
        if len(labels) < 2:
            errors.append(TEXT["v_choice_too_few"])
        elif len(set(labels)) != len(labels):
            errors.append(TEXT["v_choice_not_unique"])

    if score["enabled"]:
        levels = [lvl.strip() for lvl in score["levels"] if lvl.strip()]
        if len(levels) < 2:
            errors.append(TEXT["v_score_too_few"])

    return errors


def _api_error_message(exc: JevApiError, model: str) -> str:
    """Map a JevApiError to the section 6.3 table."""
    if exc.kind == "timeout":
        return TEXT["e_timeout"]
    if exc.kind == "network":
        return TEXT["e_network"]
    status = exc.status
    if status == 401:
        return TEXT["e_401"]
    if status == 402:
        return TEXT["e_402"]
    if status == 404:
        return TEXT["e_404"].format(model=model)
    if status == 413:
        return TEXT["e_413"]
    if status in (400, 422):
        message = (exc.message or "").strip().rstrip(".")
        if message:
            return TEXT["e_rejected"].format(message=message)
        return TEXT["e_rejected_no_message"]
    if status == 429:
        return TEXT["e_429"]
    return TEXT["e_http_other"].format(status=status)


def _ask(api_key: str, form: dict) -> None:
    """Build, send and store the outcome in session state."""
    ss = st.session_state
    noul = form["noul"]["question"] if form["noul"]["enabled"] else None
    choice = (
        {"question": form["choice"]["question"], "options": form["choice"]["options"]}
        if form["choice"]["enabled"]
        else None
    )
    score = (
        {"question": form["score"]["question"], "levels": form["score"]["levels"]}
        if form["score"]["enabled"]
        else None
    )
    body = build_request(ss["model"], form["situation"], noul, choice, score)

    try:
        with st.spinner(TEXT["asking"]):
            outcome = jev_client.call_jev(api_key.strip(), body)
    except JevApiError as exc:
        ss["error"] = {
            "message": _api_error_message(exc, body["model"]),
            "request": body,
            "body": exc.body,
        }
    except JevResponseError as exc:
        ss["error"] = {
            "message": TEXT["e_response_shape"],
            "request": body,
            "body": exc.body,
        }
    except Exception:  # noqa: BLE001 - a bug must not show a stack trace on screen
        traceback.print_exc(file=sys.stderr)
        ss["error"] = {"message": TEXT["e_unexpected"], "request": body, "body": None}
    else:
        ss["result"] = {"request": body, **outcome}


# --------------------------------------------------------------------------
# Formatting helpers (Danish)
# --------------------------------------------------------------------------


def _percent(p: float) -> str:
    """0.78 -> '78 %'."""
    return f"{round(p * 100)} %"


def _clamp01(p: float) -> float:
    return min(1.0, max(0.0, float(p)))


def _decimal(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _confidence_text(confidence: float | None) -> str:
    return TEXT["not_reported"] if confidence is None else _percent(confidence)


def _cost_text(cost: float | None) -> str:
    """USD with enough decimals to be non-zero (two significant digits)."""
    if cost is None:
        return TEXT["not_reported"]
    if cost <= 0:
        return "0,00 USD"
    decimals = 2
    while decimals < 12 and round(cost, decimals) == 0:
        decimals += 1
    # One more decimal so the first non-zero digit is not the only one.
    return f"{_decimal(cost, min(decimals + 1, 12))} USD"


def _tokens_text(usage: dict) -> str:
    def one(value: int | None) -> str:
        return TEXT["not_reported"] if value is None else str(value)

    return f"{one(usage.get('input_tokens'))} / {one(usage.get('output_tokens'))}"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _block_title(text: str) -> None:
    """'Valg (Choice)' -> heading 'Valg' with a smaller '(Choice)'."""
    name, sep, rest = text.partition(" (")
    if not sep:
        st.subheader(text)
        return
    st.markdown(
        f'<h3 style="margin-bottom:0.25rem">{html.escape(name)} '
        f'<span style="font-size:0.6em;font-weight:400;opacity:0.65">'
        f"({html.escape(rest)}</span></h3>",
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.text_input(TEXT["sidebar_key"], type="password", key="api_key")
        st.text_input(TEXT["sidebar_model"], key="model")
        st.selectbox(
            TEXT["sidebar_preset"],
            [TEXT["preset_blank"]] + list(PRESETS),
            key="preset",
            on_change=_on_preset_change,
        )


def _render_option_rows() -> None:
    ss = st.session_state
    for i, rid in enumerate(ss["option_ids"]):
        c_label, c_desc, c_remove = st.columns([3, 5, 1], vertical_alignment="bottom")
        visibility = "visible" if i == 0 else "collapsed"
        c_label.text_input(
            TEXT["option_label"], key=f"opt_label_{rid}", label_visibility=visibility
        )
        c_desc.text_input(
            TEXT["option_desc"], key=f"opt_desc_{rid}", label_visibility=visibility
        )
        c_remove.button(
            TEXT["remove"], key=f"opt_remove_{rid}", on_click=_remove_option, args=(rid,)
        )
    st.button(TEXT["add_option"], key="add_option", on_click=_add_option)


def _render_level_rows() -> None:
    ss = st.session_state
    st.caption(TEXT["levels_hint"])
    for i, rid in enumerate(ss["level_ids"]):
        c_text, c_remove = st.columns([8, 1], vertical_alignment="bottom")
        c_text.text_input(f"{TEXT['level']} {i + 1}", key=f"lvl_{rid}")
        c_remove.button(
            TEXT["remove"], key=f"lvl_remove_{rid}", on_click=_remove_level, args=(rid,)
        )
    st.button(TEXT["add_level"], key="add_level", on_click=_add_level)


def _render_form() -> None:
    st.text_area(TEXT["situation"], key="situation", height=160)

    _block_title(TEXT["block_noul"])
    st.checkbox(TEXT["enable"], key="noul_enabled")
    st.text_input(
        TEXT["question"],
        key="noul_question",
        disabled=not st.session_state["noul_enabled"],
    )

    _block_title(TEXT["block_choice"])
    st.checkbox(TEXT["enable"], key="choice_enabled")
    st.text_input(
        TEXT["question"],
        key="choice_question",
        disabled=not st.session_state["choice_enabled"],
    )
    _render_option_rows()

    _block_title(TEXT["block_score"])
    st.checkbox(TEXT["enable"], key="score_enabled")
    st.text_input(
        TEXT["question"],
        key="score_question",
        disabled=not st.session_state["score_enabled"],
    )
    _render_level_rows()


def _render_noul_card(answer: dict) -> None:
    with st.container(border=True):
        _block_title(TEXT["block_noul"])
        p = answer["yes_probability"]
        st.markdown(f"## {_percent(p)}")
        st.progress(_clamp01(p), text=TEXT["yes_probability"])


def _render_choice_card(answer: dict) -> None:
    with st.container(border=True):
        _block_title(TEXT["block_choice"])
        st.caption(TEXT["chosen"])
        st.markdown(f"## {answer['choice']}")
        probs: dict[str, float] = answer["probabilities"]
        for label, p in sorted(probs.items(), key=lambda kv: kv[1], reverse=True):
            st.progress(_clamp01(p), text=f"{label}: {_percent(p)}")
        top = max(probs.values()) if probs else None
        c1, c2 = st.columns(2)
        c1.metric(TEXT["top_probability"], _confidence_text(top))
        c2.metric(TEXT["confidence"], _confidence_text(answer["confidence"]))


def _render_score_card(answer: dict) -> None:
    with st.container(border=True):
        _block_title(TEXT["block_score"])
        legend: dict[int, str] = answer["legend"]
        probs: dict[int, float] = answer["probabilities"]
        score = answer["score"]
        indexes = sorted(set(legend) | set(probs))
        low, high = (indexes[0], indexes[-1]) if indexes else (0, 0)
        headline = legend.get(int(round(score)))
        range_text = TEXT["score_range"].format(
            score=_decimal(score, 1), low=low, high=high
        )
        if headline is not None:
            st.markdown(f"## {headline}")
            st.caption(range_text)
        else:
            st.markdown(f"## {range_text}")
        for idx in indexes:
            label = legend.get(idx, str(idx))
            p = probs.get(idx, 0.0)
            st.progress(_clamp01(p), text=f"{label}: {_percent(p)}")
        st.metric(TEXT["confidence"], _confidence_text(answer["confidence"]))


_CARDS = {
    "noul": _render_noul_card,
    "choice": _render_choice_card,
    "score": _render_score_card,
}


def _render_json(request: dict, label: str, body: Any) -> None:
    """The exact request body sent, and a response body, pretty-printed.

    The API key travels in the Authorization header, not in the body, so
    there is nothing to redact here.
    """
    with st.expander(TEXT["show_json"]):
        st.caption(TEXT["request_json"])
        st.json(request)
        if body is not None:
            st.caption(label)
            if isinstance(body, (dict, list)):
                st.json(body)
            else:
                st.code(str(body))


def _render_result() -> None:
    ss = st.session_state
    error = ss.get("error")
    if error is not None:
        st.error(error["message"])
        _render_json(error["request"], TEXT["error_body_json"], error["body"])
        return

    result = ss.get("result")
    if result is None:
        return

    answers = result["answers"]
    for key in (KEY_NOUL, KEY_CHOICE, KEY_SCORE):
        answer = answers.get(key)
        if answer is None:
            continue
        renderer = _CARDS.get(answer.get("type"))
        if renderer is not None:
            renderer(answer)

    usage = result["usage"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(TEXT["latency"], f"{result['latency_ms']} ms")
    c2.metric(TEXT["cost"], _cost_text(usage.get("cost")))
    c3.metric(TEXT["tokens"], _tokens_text(usage))
    c4.metric(TEXT["model_used"], result["model"] or TEXT["not_reported"])

    _render_json(result["request"], TEXT["response_json"], result["raw"])


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title=TEXT["title"], layout="centered")
    _init_state()
    st.title(TEXT["title"])
    _render_sidebar()
    _render_form()

    # Validation messages go here, above the button.
    errors_box = st.container()
    clicked = st.button(TEXT["ask"], key="ask", type="primary")

    if clicked:
        ss = st.session_state
        # A new call clears the previous result panel.
        ss["result"] = None
        ss["error"] = None
        form = _read_form()
        errors = _validate(ss["api_key"], form)
        if errors:
            for message in errors:
                errors_box.error(message)
        else:
            _ask(ss["api_key"], form)

    _render_result()


main()
