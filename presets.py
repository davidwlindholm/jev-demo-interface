"""Demo scenarios for the Jev demo tool (plan section 7).

PRESETS maps a display name to a scenario:

    {
        "situation": str,
        "noul":   {"enabled": bool, "question": str},
        "choice": {"enabled": bool, "question": str,
                   "options": [(label, description), ...]},
        "score":  {"enabled": bool, "question": str,
                   "levels": [str, ...]},   # lowest level first
    }

Without the ``enabled`` flag, each block has the shape jev_client.build_request
expects. Callers should copy a preset before editing it. All names are
fictional.
"""

import copy

_STUCK_NOUL = {"enabled": True, "question": "Er gruppen kommet væk fra opgaven?"}
_STUCK_CHOICE = {
    "enabled": True,
    "question": "Hvad bør moderatoren gøre nu?",
    "options": [
        ("Lyt videre", "Diskussionen er produktiv og kræver ingen indgriben"),
        (
            "Vejledende spørgsmål",
            "Stil et spørgsmål, der hjælper gruppen forbi det nuværende stridspunkt",
        ),
        ("Tilbage til opgaven", "Før gruppen tilbage til den egentlige opgave"),
        (
            "Inviter den stille",
            "Inviter den studerende, der ikke har sagt noget, til at bidrage",
        ),
    ],
}
_STUCK_SCORE = {
    "enabled": True,
    "question": "Hvor ophedet er tonen?",
    "levels": [
        "Rolig og saglig",
        "Lidt anspændt",
        "Skarp, med afbrydelser",
        "Åben konflikt",
    ],
}

PRESETS: dict[str, dict] = {
    "Den stille studerende": {
        "situation": (
            "Fire studerende (Anna, Jonas, Mette og Sofie) arbejder i en "
            "gruppechat med at udvikle en markedsføringsplan for en lokal café. "
            "De har arbejdet i 12 minutter. Anna og Jonas har skrevet det meste "
            "og diskuterer lige nu målgrupper. Mette har bidraget med to korte "
            "kommentarer. Sofie har ikke skrevet noget endnu."
        ),
        "noul": {"enabled": True, "question": "Bør moderatoren gribe ind nu?"},
        "choice": {
            "enabled": True,
            "question": (
                "Hvilken studerende bør moderatoren invitere til at bidrage "
                "næste gang?"
            ),
            "options": [
                ("Anna", "Inviter Anna til at bidrage"),
                ("Jonas", "Inviter Jonas til at bidrage"),
                ("Mette", "Inviter Mette til at bidrage"),
                ("Sofie", "Inviter Sofie til at bidrage"),
            ],
        },
        "score": {
            "enabled": True,
            "question": "Hvor produktiv er diskussionen lige nu?",
            "levels": [
                "Uproduktiv: gruppen er gået i stå eller taler om noget andet",
                "Delvist produktiv: der er fremdrift, men ikke alle deltager",
                "Produktiv: gruppen arbejder målrettet, og alle bidrager",
            ],
        },
    },
    "Fastlåst diskussion": {
        "situation": (
            "Fire studerende arbejder med en strategi for at komme ind på et "
            "nyt marked. Anna og Jonas har i fem minutter diskuteret den samme "
            "antagelse om prissætning uden at nå til enighed, og tonen er "
            "blevet skarp. Mette har to gange forsøgt at foreslå et kompromis, "
            "men bliver overhørt. Sofie har ikke sagt noget i ti minutter. "
            "Opgaven er at blive enige om en strategi inden for de næste 15 "
            "minutter."
        ),
        "noul": copy.deepcopy(_STUCK_NOUL),
        "choice": copy.deepcopy(_STUCK_CHOICE),
        "score": copy.deepcopy(_STUCK_SCORE),
    },
    # Same questions as "Fastlåst diskussion"; only the situation changes.
    "Opgaven er løst": {
        "situation": (
            "Gruppen er blevet enige om en strategi og har skrevet den ned i "
            "det fælles dokument. De sidste tre minutter har de talt om, hvor "
            "de skal spise frokost, og om en serie, de har set."
        ),
        "noul": copy.deepcopy(_STUCK_NOUL),
        "choice": copy.deepcopy(_STUCK_CHOICE),
        "score": copy.deepcopy(_STUCK_SCORE),
    },
}
