"""
Player Database
---------------
Fetches and caches Basketball Reference data for each decade/team combo.
Builds PlayerStats objects ready for the scoring engine.

Data flow:
  1. For a given (team, decade) spin, fetch all season totals for each year
     in that decade that the team existed.
  2. For each player who appeared on that team, find their single best season
     (by Win Shares) within that decade.
  3. Merge in advanced stats (TS%, WS/48, AST%, STL%, BLK%, USG%).
  4. Attach the best award they won that decade.
  5. Return top 4 players per position slot (PG, SG, SF, PF, C).
"""

import json
import time
import os
from dataclasses import dataclass
from typing import Optional

from basketball_reference_web_scraper import client
from basketball_reference_web_scraper.data import Position, Team

from scoring_engine import PlayerStats, get_eligible_positions

# ---------------------------------------------------------------------------
# Cache — avoid hammering Basketball Reference on every run
# ---------------------------------------------------------------------------
CACHE_FILE = "player_cache.json"

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}

def _save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

# ---------------------------------------------------------------------------
# Decade → list of season_end_years
# ---------------------------------------------------------------------------
DECADE_YEARS = {
    "1960s": list(range(1961, 1970)),
    "1970s": list(range(1970, 1980)),
    "1980s": list(range(1980, 1990)),
    "1990s": list(range(1990, 2000)),
    "2000s": list(range(2000, 2010)),
    "2010s": list(range(2010, 2020)),
    "2020s": list(range(2020, 2026)),
}

# ---------------------------------------------------------------------------
# Award data (manually curated — Basketball Reference doesn't expose awards
# via the scraper, and the pre-1974 era lacks STL/BLK anyway)
# Format: {player_slug: {decade: best_award}}
# ---------------------------------------------------------------------------
AWARD_DATA: dict[str, dict[str, str]] = {
    # MVPs
    "chambwi01": {"1960s": "MVP", "1970s": "MVP"},
    "russebi01": {"1960s": "MVP"},
    "abdulka01": {"1970s": "MVP", "1980s": "MVP"},
    "johnsma02": {"1980s": "MVP"},
    "birdla01":  {"1980s": "MVP"},
    "jordami01": {"1990s": "MVP"},
    "maloneka01": {"1990s": "MVP"},
    "robinda01": {"1990s": "Defensive Player of the Year"},
    "onealsh01": {"2000s": "MVP"},
    "duncanti01": {"2000s": "MVP"},
    "nashs01":   {"2000s": "1st Team All-NBA"},
    "bryanko01": {"2000s": "MVP"},
    "jamesle01": {"2010s": "MVP", "2020s": "1st Team All-NBA"},
    "duranke01": {"2010s": "MVP"},
    "curryst01": {"2010s": "MVP"},
    "westbru01": {"2010s": "MVP"},
    "hardeja01": {"2010s": "MVP"},
    "antetgi01": {"2020s": "MVP", "2010s": "MVP"},
    "jokicni01": {"2020s": "MVP"},
    "embiijo01": {"2020s": "MVP"},
    # Defensive POY
    "olajuha01": {"1990s": "Defensive Player of the Year"},
    "mourala01": {"1990s": "Defensive Player of the Year"},
    "mutomdi01": {"1990s": "Defensive Player of the Year"},
    "garneke01": {"2000s": "Defensive Player of the Year"},
    "howardw01": {"2000s": "Defensive Player of the Year"},
    "leonaka01": {"2010s": "Defensive Player of the Year"},
    "goberru01": {"2010s": "Defensive Player of the Year", "2020s": "Defensive Player of the Year"},
    # Finals MVPs / All-Stars (catch important players not listed above)
    "piercpa01": {"2000s": "Finals MVP"},
    "gibsotat01": {"2000s": "All-Star"},
    "wadedw01":  {"2000s": "Finals MVP"},
    "paulch01":  {"2000s": "1st Team All-NBA"},
    "arenagi01": {"2000s": "All-Star"},
    "mcgratr01": {"2000s": "1st Team All-NBA"},
    "iveral01":  {"2000s": "1st Team All-NBA"},
    "nowitdi01": {"2000s": "MVP", "2010s": "1st Team All-NBA"},
    "thomale01": {"1980s": "Finals MVP"},
    "drexlcl01": {"1990s": "Finals MVP"},
    "hakeemol01": {"1990s": "Finals MVP"},
    "paytoga01": {"1990s": "1st Team All-Defense"},
    "piippsc01": {"1990s": "1st Team All-Defense"},
    "stoudam01": {"2000s": "All-Star"},
    "paulch01":  {"2000s": "1st Team All-NBA", "2010s": "1st Team All-NBA"},
    "thompkl01": {"2010s": "1st Team All-Defense"},
    "greendr01": {"2010s": "Defensive Player of the Year"},
    "lillada01": {"2010s": "1st Team All-NBA", "2020s": "1st Team All-NBA"},
    "butliji01": {"2020s": "1st Team All-NBA"},
    "tatumja01": {"2020s": "1st Team All-NBA"},
    "bookede01": {"2020s": "All-Star"},
    "youngtr01": {"2020s": "All-Star"},
    "morantja01": {"2020s": "All-Star"},
}

def _get_award(slug: str, decade: str) -> str:
    return AWARD_DATA.get(slug, {}).get(decade, "None")

# ---------------------------------------------------------------------------
# Position mapping
# ---------------------------------------------------------------------------
POSITION_MAP = {
    # Enum keys (live fetch, not yet serialized)
    Position.POINT_GUARD:       "PG",
    Position.SHOOTING_GUARD:    "SG",
    Position.SMALL_FORWARD:     "SF",
    Position.POWER_FORWARD:     "PF",
    Position.CENTER:            "C",
    # String keys (from JSON cache — enums serialised to their .value strings)
    "POINT GUARD":    "PG",
    "SHOOTING GUARD": "SG",
    "SMALL FORWARD":  "SF",
    "POWER FORWARD":  "PF",
    "CENTER":         "C",
}

# Manual position overrides for players the scraper miscategorizes
POSITION_OVERRIDES: dict[str, str] = {
    "abdulka01": "C",   # Kareem Abdul-Jabbar
    "chambwi01": "C",   # Wilt Chamberlain
    "russebi01": "C",   # Bill Russell
    "onealsh01": "C",   # Shaquille O'Neal
    "olajuha01": "C",   # Hakeem Olajuwon
    "ewingpa01": "C",   # Patrick Ewing
    "mourala01": "C",   # Alonzo Mourning
    "mutomdi01": "C",   # Dikembe Mutombo
    "duncanti01": "PF", # Tim Duncan
    "garneke01": "PF",  # Kevin Garnett
    "maloneka01": "PF", # Karl Malone
    "barkcha01": "PF",  # Charles Barkley
    "nowitdi01": "PF",  # Dirk Nowitzki
    "johnsma02": "PG",  # Magic Johnson
    "stockjo01": "PG",  # John Stockton
    "isiaht01":  "PG",  # Isiah Thomas
    "hardeja01": "PG",  # James Harden (primary PG era)
    "paulch01":  "PG",  # Chris Paul
    "nashst01":  "PG",  # Steve Nash
    "kiddja01":  "PG",  # Jason Kidd
    "jordami01": "SG",  # Michael Jordan
    "drexlcl01": "SG",  # Clyde Drexler
    "bryanko01": "SG",  # Kobe Bryant
    "wadedw01":  "SG",  # Dwyane Wade
    "millerem01":"SG",  # Reggie Miller
    "piercpa01": "SG",  # Paul Pierce (scraper sometimes SF)
    "piippsc01": "SF",  # Scottie Pippen
    "duranke01": "SF",  # Kevin Durant
    "jamesle01": "SF",  # LeBron James
    "leonaka01": "SF",  # Kawhi Leonard
}

def _primary_position(positions: list, slug: str = "") -> str:
    if slug and slug in POSITION_OVERRIDES:
        return POSITION_OVERRIDES[slug]
    if not positions:
        return "SF"
    return POSITION_MAP.get(positions[0], "SF")

# ---------------------------------------------------------------------------
# Team name normalisation (the scraper uses enum values like "CHICAGO BULLS")
# ---------------------------------------------------------------------------
def _team_name(team) -> str:
    if hasattr(team, "value"):
        return team.value.title()
    return str(team).title()

# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

def _fetch_with_retry(fn, label: str, max_retries: int = 5) -> list:
    """Call a Basketball Reference fetch function with exponential backoff on 429."""
    import requests
    delay = 4.0
    for attempt in range(max_retries):
        try:
            result = fn()
            time.sleep(3.0)   # polite inter-request gap
            return result
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                wait = delay * (2 ** attempt)
                print(f"  Rate limited fetching {label}. Waiting {wait:.0f}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Failed to fetch {label} after {max_retries} retries.")


def _fetch_total_rebounds_patch(year: int) -> dict:
    """
    Scrape total rebounds from BBRef HTML for pre-1974 seasons where the
    library returns 0 for offensive/defensive rebounds (not tracked separately).
    Returns {slug: total_rebounds}.
    """
    import requests
    from bs4 import BeautifulSoup
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    url = f"https://www.basketball-reference.com/leagues/NBA_{year}_totals.html"
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", {"id": "totals_stats"})
    if not table:
        return {}
    patch = {}
    for tr in table.find_all("tr"):
        slug_td = tr.find("td", {"data-stat": "name_display"})
        reb_td  = tr.find("td", {"data-stat": "trb"})
        if not slug_td or not reb_td:
            continue
        a = slug_td.find("a")
        if not a:
            continue
        href = a.get("href", "")
        # href like /players/r/russebi01.html
        slug = href.split("/")[-1].replace(".html", "")
        try:
            patch[slug] = int(reb_td.get_text(strip=True))
        except ValueError:
            pass
    return patch


def _fetch_season(year: int, cache: dict) -> tuple[list, list]:
    """Return (totals_rows, advanced_rows) for a season, using cache."""
    key_t = f"totals_{year}"
    key_a = f"advanced_{year}"
    key_r = f"reb_patch_{year}"

    if key_t not in cache:
        print(f"  Fetching {year} season totals...", flush=True)
        cache[key_t] = _serialize_rows(
            _fetch_with_retry(
                lambda: client.players_season_totals(season_end_year=year),
                f"{year} totals"
            )
        )
        _save_cache(cache)   # save after each fetch so progress survives crashes

    if key_a not in cache:
        print(f"  Fetching {year} advanced stats...", flush=True)
        cache[key_a] = _serialize_rows(
            _fetch_with_retry(
                lambda: client.players_advanced_season_totals(season_end_year=year),
                f"{year} advanced"
            )
        )
        _save_cache(cache)

    # Pre-1974: o/d rebounds not tracked — fetch total rebound patch from HTML
    if year < 1974 and key_r not in cache:
        print(f"  Fetching {year} rebound patch...", flush=True)
        try:
            cache[key_r] = _fetch_total_rebounds_patch(year)
            _save_cache(cache)
            time.sleep(3.0)
        except Exception as e:
            print(f"  Warning: could not fetch rebound patch for {year}: {e}", flush=True)
            cache[key_r] = {}

    return cache[key_t], cache[key_a]


def _serialize_rows(rows: list) -> list:
    """Convert enum values to strings so rows can be JSON-cached."""
    out = []
    for row in rows:
        r = {}
        for k, v in row.items():
            if hasattr(v, "value"):
                r[k] = v.value
            elif isinstance(v, list):
                r[k] = [x.value if hasattr(x, "value") else x for x in v]
            else:
                r[k] = v
        out.append(r)
    return out


def _per_game(row: dict, games: int, reb_patch: dict = None) -> dict:
    """Convert season totals row to per-game stats."""
    g = max(games, 1)
    reb_o = row.get("offensive_rebounds", 0) or 0
    reb_d = row.get("defensive_rebounds", 0) or 0
    total_reb = reb_o + reb_d
    # Pre-1974: o/d splits not tracked — use HTML-scraped total if available
    if total_reb == 0 and reb_patch:
        slug = row.get("slug", "")
        total_reb = reb_patch.get(slug, 0)
    return {
        "ppg": round(row.get("points", 0) / g, 1),
        "rpg": round(total_reb / g, 1),
        "apg": round(row.get("assists", 0) / g, 1),
        "spg": round(row.get("steals", 0) / g, 1),
        "bpg": round(row.get("blocks", 0) / g, 1),
    }


def _win_shares(adv_row: dict) -> float:
    return adv_row.get("win_shares", 0.0) or 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class PlayerOption:
    """A selectable player shown to the user for a given team/decade spin."""
    stats: PlayerStats
    win_shares: float   # used for sorting / tiebreaking
    games_played: int


def get_players_for_spin(
    team_name: str,
    decade: str,
    top_n_per_position: int = 4,
) -> dict[str, list[PlayerOption]]:
    """
    Return the top N players per position from a given team/decade.

    Args:
        team_name:  Friendly team name, e.g. "Chicago Bulls"
        decade:     One of "1960s" … "2020s"
        top_n_per_position: How many options to show per position slot

    Returns:
        {
            "PG": [PlayerOption, ...],
            "SG": [PlayerOption, ...],
            "SF": [PlayerOption, ...],
            "PF": [PlayerOption, ...],
            "C":  [PlayerOption, ...],
        }
    """
    cache = _load_cache()
    years = DECADE_YEARS.get(decade, [])
    team_upper = team_name.upper()

    # Collect best season per player-slug across the decade
    # best_by_slug: {slug: {year, totals_row, adv_row, win_shares}}
    best_by_slug: dict[str, dict] = {}

    for year in years:
        totals, advanced = _fetch_season(year, cache)

        # Build slug → advanced row lookup
        adv_lookup: dict[str, dict] = {}
        for row in advanced:
            if row.get("is_combined_totals"):
                continue
            slug = row.get("slug", "")
            row_team = row.get("team") or ""
            if row_team.upper() == team_upper:
                adv_lookup[slug] = row

        for row in totals:
            if row.get("is_combined_totals"):
                continue
            row_team = row.get("team") or ""
            if row_team.upper() != team_upper:
                continue
            slug = row.get("slug", "")
            if not slug:
                continue

            games = row.get("games_played", 1) or 1
            # Must have played meaningful minutes to qualify
            if games < 20:
                continue

            adv = adv_lookup.get(slug, {})
            ws = _win_shares(adv)

            if slug not in best_by_slug or ws > best_by_slug[slug]["win_shares"]:
                best_by_slug[slug] = {
                    "year": year,
                    "totals": row,
                    "adv": adv,
                    "win_shares": ws,
                    "games": games,
                }

    _save_cache(cache)

    # Build PlayerOption objects
    all_options: list[PlayerOption] = []
    for slug, data in best_by_slug.items():
        row = data["totals"]
        adv = data["adv"]
        year = data["year"]
        games = data["games"]

        reb_patch = cache.get(f"reb_patch_{year}", {}) if year < 1974 else {}
        pg = _per_game(row, games, reb_patch)
        positions = row.get("positions", [])
        primary_pos = _primary_position(positions, slug)

        stats = PlayerStats(
            name=row.get("name", slug),
            team=_team_name(row.get("team", team_name)),
            decade=decade,
            primary_position=primary_pos,
            best_season_year=year,
            ppg=pg["ppg"],
            rpg=pg["rpg"],
            apg=pg["apg"],
            spg=pg["spg"],
            bpg=pg["bpg"],
            best_award=_get_award(slug, decade),
            ts_pct=adv.get("true_shooting_percentage"),
            ws_per_48=adv.get("win_shares_per_48_minutes"),
            ast_pct=adv.get("assist_percentage"),
            stl_pct=adv.get("steal_percentage"),
            blk_pct=adv.get("block_percentage"),
            usg_pct=adv.get("usage_percentage"),
        )

        all_options.append(PlayerOption(
            stats=stats,
            win_shares=data["win_shares"],
            games_played=games,
        ))

    # Bucket by PRIMARY position only for display purposes.
    # Position flexibility (eligible_positions) is used at lineup-selection time,
    # not here — otherwise positionless players flood every bucket.
    buckets: dict[str, list[PlayerOption]] = {
        "PG": [], "SG": [], "SF": [], "PF": [], "C": []
    }

    for opt in all_options:
        pos = opt.stats.primary_position
        if pos in buckets:
            buckets[pos].append(opt)

    # Sort each bucket by win shares descending, dedupe names, take top N
    result: dict[str, list[PlayerOption]] = {}
    for pos, opts in buckets.items():
        seen_names = set()
        unique = []
        for opt in sorted(opts, key=lambda x: x.win_shares, reverse=True):
            if opt.stats.name not in seen_names:
                seen_names.add(opt.stats.name)
                unique.append(opt)
        result[pos] = unique[:top_n_per_position]

    return result


def display_spin_options(
    team_name: str,
    decade: str,
    advanced: bool = False,
) -> None:
    """Print player options for a spin to the terminal."""
    print(f"\n{'='*60}")
    print(f"  SPIN: {team_name.title()}  |  {decade}")
    print(f"{'='*60}")

    options = get_players_for_spin(team_name, decade)

    for pos in ["PG", "SG", "SF", "PF", "C"]:
        players = options.get(pos, [])
        print(f"\n  {pos}")
        if not players:
            print("    (no players found)")
            continue
        for i, opt in enumerate(players, 1):
            s = opt.stats
            award_tag = f"  [{s.best_award}]" if s.best_award != "None" else ""
            print(
                f"    {i}. {s.name:<25} "
                f"PTS {s.ppg:>5.1f}  REB {s.rpg:>4.1f}  "
                f"AST {s.apg:>4.1f}  STL {s.spg:>4.1f}  BLK {s.bpg:>4.1f}"
                f"  WS {opt.win_shares:>5.1f}{award_tag}"
            )
            if advanced and s.ts_pct:
                print(
                    f"       TS% {s.ts_pct:.3f}  "
                    f"WS/48 {s.ws_per_48:.3f}  "
                    f"USG% {s.usg_pct:.1f}"
                    if s.usg_pct else ""
                )


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Loading Chicago Bulls 1990s...")
    display_spin_options("Chicago Bulls", "1990s")

    print("\n\nLoading Los Angeles Lakers 1980s...")
    display_spin_options("Los Angeles Lakers", "1980s")
