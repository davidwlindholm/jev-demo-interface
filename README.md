# Jev demo

A small local Streamlit tool for demonstrating TypeSafe's Jev decision model, called through OpenRouter's Decisions API. You describe a situation, ask up to three questions about it, and see the answers with their probabilities. The interface and the built-in scenarios are in Danish.

You need an [OpenRouter](https://openrouter.ai) API key with credit on the account.

## Install

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.10 or newer.

## Run

```
streamlit run app.py
```

Run this from the repository root. The API key is read from the `OPENROUTER_API_KEY` environment variable and used to pre-fill the sidebar field; otherwise, type it into the sidebar. The key is never saved to disk. `.streamlit/config.toml` keeps the server on localhost only, since Streamlit would otherwise listen on all network interfaces.

To run the tests: `pytest`. They use a recorded response and make no network calls.

## Question types

Jev answers three kinds of questions. Ja/nej (Noul) returns the probability that the answer is "yes". Valg (Choice) returns the winning option along with a probability for each option and a chance-corrected confidence value. Skala (Score) returns a probability-weighted position on an ordered scale, which may be non-integer, along with a probability for each level and a confidence equal to the peak probability.

## Files

- `app.py`: the Streamlit interface, form state and result rendering.
- `jev_client.py`: builds the request, calls the API and parses the response.
- `presets.py`: the three built-in scenarios. All names in them are fictional.
- `tests/`: unit tests for `jev_client.py`.

## Demo-day checklist

- Confirm OpenRouter balance the day before.
- Start `streamlit run app.py` before the meeting; the key is picked up from the environment so nothing is typed on screen.
- Full-screen the browser tab and share only that window, not the terminal.
- Run the "Den stille studerende" scenario once before the meeting to warm up and to check the API is up.
- Keep https://openrouter.ai/labs/jev open in another tab as a backup if the tool fails.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
