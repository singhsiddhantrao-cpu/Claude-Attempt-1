"""AI agent that answers questions about a country's census/demographic data.

Ask it about a country and it looks up official World Bank indicators
(population, growth rate, urban share, life expectancy, density, surface
area) and has Claude summarize them in plain language.

Run:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in ANTHROPIC_API_KEY
    python census_agent.py

Country-name resolution (e.g. "uk" -> United Kingdom, "south korea" -> Korea,
Republic of) runs fully offline via the bundled `pycountry` ISO-3166 database.
Only the actual data lookup needs network access, via the World Bank's public,
no-auth-required API (https://api.worldbank.org).
"""

import os

import httpx
import pycountry
from anthropic import Anthropic, beta_tool
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your "
        "own key, or export ANTHROPIC_API_KEY in your shell before running "
        "this script."
    )

WORLD_BANK_BASE = "https://api.worldbank.org/v2"

# World Bank indicator codes -- see https://data.worldbank.org/indicator
INDICATORS = {
    "population_total": "SP.POP.TOTL",
    "population_growth_pct_per_year": "SP.POP.GROW",
    "urban_population_pct": "SP.URB.TOTL.IN.ZS",
    "life_expectancy_years": "SP.DYN.LE00.IN",
    "population_density_per_sq_km": "EN.POP.DNST",
    "surface_area_sq_km": "AG.SRF.TOTL.K2",
}


def _resolve_country(name: str) -> tuple[str, str]:
    """Resolve a user-typed country name to (iso3_code, official_name). Offline."""
    try:
        match = pycountry.countries.lookup(name)
    except LookupError:
        matches = pycountry.countries.search_fuzzy(name)
        match = matches[0]
    return match.alpha_3, match.name


def _fetch_indicator(iso3: str, indicator_code: str) -> dict | None:
    """Fetch the most recent non-empty value for one World Bank indicator."""
    url = f"{WORLD_BANK_BASE}/country/{iso3}/indicator/{indicator_code}"
    params = {"format": "json", "per_page": 1, "mrnev": 1}
    response = httpx.get(url, params=params, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    if len(payload) < 2 or not payload[1]:
        return None
    record = payload[1][0]
    if record.get("value") is None:
        return None
    return {"year": record["date"], "value": record["value"]}


@beta_tool
def get_census_data(country: str) -> str:
    """Look up official World Bank census/demographic statistics for a country.

    Args:
        country: Country name as typed by the user, e.g. "France", "South Korea", "UK".
    """
    try:
        iso3, official_name = _resolve_country(country)
    except LookupError:
        return f"Could not find a country matching '{country}'. Please check the spelling."

    lines = [f"Country: {official_name} ({iso3})"]
    for label, code in INDICATORS.items():
        pretty_label = label.replace("_", " ").title()
        try:
            data = _fetch_indicator(iso3, code)
        except httpx.HTTPError as exc:
            lines.append(f"{pretty_label}: lookup failed ({exc})")
            continue
        if data is None:
            lines.append(f"{pretty_label}: data unavailable")
        else:
            lines.append(f"{pretty_label} ({data['year']}): {data['value']}")
    return "\n".join(lines)


def ask(country: str) -> str:
    """Run the agent for one country and return its final text response."""
    client = Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-opus-4-8",
        max_tokens=1024,
        tools=[get_census_data],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Give me the census and demographic data for {country}. "
                    "Present it as a short, readable summary."
                ),
            }
        ],
    )
    final_message = None
    for message in runner:
        final_message = message
    if final_message is None:
        return "No response from the agent."
    return next((b.text for b in final_message.content if b.type == "text"), "")


def main() -> None:
    country = input("Enter a country name: ").strip()
    if not country:
        print("No country entered.")
        return
    print(ask(country))


if __name__ == "__main__":
    main()
