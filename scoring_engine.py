"""
82-0 Game Scoring Engine
------------------------
Evaluates a 5-player NBA lineup and predicts their season record (out of 82 games).

Display stats:  per-game (familiar to users)
Calculate with: per-100 possession equivalents (era-normalized)
Award bonus:    multiplier on player's contribution (best award only, no stacking)
Win curve:      non-linear, ~1-in-35 chance of hitting 82-0 with a perfect lineup
"""

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Position flexibility tiers
# ---------------------------------------------------------------------------
POSITION_FLEX = {
    # True positionless
    "LeBron James":          ["PG", "SG", "SF", "PF", "C"],
    "Magic Johnson":         ["PG", "SG", "SF", "PF", "C"],
    "Ben Simmons":           ["PG", "SG", "SF", "PF", "C"],
    "Scottie Pippen":        ["PG", "SG", "SF", "PF", "C"],
    "Giannis Antetokounmpo": ["PG", "SG", "SF", "PF", "C"],

    # PG/SG combo guards
    "Steph Curry":           ["PG", "SG"],
    "James Harden":          ["PG", "SG"],
    "Dwyane Wade":           ["PG", "SG"],
    "Allen Iverson":         ["PG", "SG"],
    "Jerry West":            ["PG", "SG"],
    "Oscar Robertson":       ["PG", "SG"],
    "Isiah Thomas":          ["PG", "SG"],
    "Gary Payton":           ["PG", "SG"],
    "Damian Lillard":        ["PG", "SG"],
    "Russell Westbrook":     ["PG", "SG"],
    "Chris Paul":            ["PG", "SG"],
    "Kyrie Irving":          ["PG", "SG"],
    "Tony Parker":           ["PG", "SG"],
    "Steve Nash":            ["PG", "SG"],
    "Jason Kidd":            ["PG", "SG"],
    "Luka Doncic":           ["PG", "SG", "SF"],
    "Trae Young":            ["PG", "SG"],
    "Derrick Rose":          ["PG", "SG"],

    # SG/SF wings
    "Kobe Bryant":           ["SG", "SF"],
    "Vince Carter":          ["SG", "SF"],
    "Tracy McGrady":         ["SG", "SF"],
    "Grant Hill":            ["SG", "SF"],
    "Clyde Drexler":         ["SG", "SF"],
    "Reggie Miller":         ["SG", "SF"],
    "Ray Allen":             ["SG", "SF"],
    "Manu Ginobili":         ["SG", "SF"],
    "Shai Gilgeous-Alexander": ["SG", "SF"],
    "Devin Booker":          ["SG", "SF"],
    "Bradley Beal":          ["SG", "SF"],
    "Jaylen Brown":          ["SG", "SF"],
    "DeMar DeRozan":         ["SG", "SF"],
    "Donovan Mitchell":      ["SG", "SF"],
    "Michael Jordan":        ["SG", "SF"],

    # SF/PF wings
    "Kevin Durant":          ["SF", "PF"],
    "Kawhi Leonard":         ["SG", "SF", "PF"],
    "Paul Pierce":           ["SG", "SF", "PF"],
    "Jimmy Butler":          ["SG", "SF", "PF"],
    "Draymond Green":        ["SF", "PF", "C"],
    "Elgin Baylor":          ["SF", "PF"],
    "Rick Barry":            ["SF", "PF"],
    "Julius Erving":         ["SF", "PF"],
    "Dominique Wilkins":     ["SF", "PF"],
    "Larry Bird":            ["SF", "PF"],
    "John Havlicek":         ["SG", "SF"],
    "Bob Pettit":            ["SF", "PF"],
    "Jayson Tatum":          ["SF", "PF"],
    "Paul George":           ["SG", "SF", "PF"],
    "Carmelo Anthony":       ["SF", "PF"],
    "Pau Gasol":             ["PF", "C"],
    "Boris Diaw":            ["PG", "SF", "PF"],
    "Lamar Odom":            ["SF", "PF"],
    "Khris Middleton":       ["SG", "SF"],

    # PF/C bigs
    "Dirk Nowitzki":         ["PF", "C"],
    "Kevin Garnett":         ["PF", "C"],
    "Chris Webber":          ["PF", "C"],
    "Karl Malone":           ["PF", "C"],
    "Charles Barkley":       ["SF", "PF"],
    "Nikola Jokic":          ["PF", "C"],
    "Anthony Davis":         ["PF", "C"],
    "Tim Duncan":            ["PF", "C"],
    "David Robinson":        ["PF", "C"],
    "Bob McAdoo":            ["PF", "C"],
    "Elvin Hayes":           ["PF", "C"],
    "Dave Cowens":           ["PF", "C"],
    "Wes Unseld":            ["PF", "C"],
    "Bob Lanier":            ["PF", "C"],
    "Alonzo Mourning":       ["PF", "C"],
    "Yao Ming":              ["PF", "C"],
    "Bam Adebayo":           ["PF", "C"],
    "Joel Embiid":           ["PF", "C"],
    "Karl-Anthony Towns":    ["PF", "C"],
    "Kristaps Porzingis":    ["PF", "C"],
    "Rasheed Wallace":       ["PF", "C"],
    "Zion Williamson":       ["PF", "C"],
}

DEFAULT_POSITIONS = {
    "PG": ["PG"],
    "SG": ["SG"],
    "SF": ["SF"],
    "PF": ["PF"],
    "C":  ["C"],
}

def get_eligible_positions(player_name: str, primary_position: str) -> list[str]:
    """Return positions a player can fill."""
    return POSITION_FLEX.get(player_name, [primary_position])


# ---------------------------------------------------------------------------
# Award multipliers (best award only, no stacking)
# ---------------------------------------------------------------------------
AWARD_MULTIPLIERS = {
    "MVP":                    1.20,
    "Finals MVP":             1.12,
    "1st Team All-NBA":       1.10,
    "Defensive Player of the Year": 1.10,
    "1st Team All-Defense":   1.07,
    "2nd Team All-NBA":       1.06,
    "All-Star":               1.03,
    "None":                   1.00,
}

def get_award_multiplier(award: str) -> float:
    return AWARD_MULTIPLIERS.get(award, 1.00)


# ---------------------------------------------------------------------------
# Per-100 pace conversion
# Estimated average possessions per game by decade
# ---------------------------------------------------------------------------
DECADE_PACE = {
    "1960s": 115.0,
    "1970s": 107.0,
    "1980s": 100.0,
    "1990s":  91.0,
    "2000s":  91.0,
    "2010s":  94.0,
    "2020s":  99.0,
}

def per_game_to_per100(stat: float, team_pace: float) -> float:
    """Convert per-game stat to per-100 possessions."""
    if team_pace <= 0:
        return stat
    # Each player participates in roughly half the team's possessions
    player_possessions_per_game = team_pace / 2
    if player_possessions_per_game <= 0:
        return stat
    return (stat / player_possessions_per_game) * 100


# ---------------------------------------------------------------------------
# Category weights for the strength rating
# ---------------------------------------------------------------------------
CATEGORY_WEIGHTS = {
    "PTS": 1.0,
    "REB": 1.0,
    "AST": 1.2,   # slight bonus: playmaking lifts whole team
    "STL": 1.5,   # defense is harder to accumulate
    "BLK": 1.5,
}

# ---------------------------------------------------------------------------
# League average baselines per 100 possessions, by decade
# Source: Basketball Reference era averages, normalized to per-100 pace
# These represent what a typical NBA *team* produces per 100 possessions
# across 5 players combined — the penalty fires only when the lineup falls
# below this baseline in any category.
# ---------------------------------------------------------------------------
LEAGUE_BASELINE_PER100 = {
    "1960s": {"PTS": 110.0, "REB": 58.0, "AST": 24.0, "STL": 6.0,  "BLK": 4.0},
    "1970s": {"PTS": 107.0, "REB": 52.0, "AST": 24.0, "STL": 7.5,  "BLK": 4.5},
    "1980s": {"PTS": 109.0, "REB": 48.0, "AST": 25.0, "STL": 7.5,  "BLK": 5.0},
    "1990s": {"PTS": 100.0, "REB": 45.0, "AST": 23.0, "STL": 7.5,  "BLK": 5.0},
    "2000s": {"PTS": 100.0, "REB": 44.0, "AST": 22.0, "STL": 7.0,  "BLK": 5.0},
    "2010s": {"PTS": 104.0, "REB": 44.0, "AST": 23.0, "STL": 7.0,  "BLK": 5.0},
    "2020s": {"PTS": 112.0, "REB": 44.0, "AST": 25.0, "STL": 7.0,  "BLK": 5.0},
}

# Max penalty when a category is completely absent (0% of baseline)
BALANCE_FLOOR_MULTIPLIER = 0.80


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------
@dataclass
class PlayerStats:
    name: str
    team: str
    decade: str
    primary_position: str
    best_season_year: int

    # Per-game stats (displayed to user)
    ppg: float
    rpg: float
    apg: float
    spg: float
    bpg: float

    # Best award this decade
    best_award: str = "None"

    # Optional advanced stats (shown in advanced mode, display only)
    ts_pct: Optional[float] = None      # True Shooting %
    ws_per_48: Optional[float] = None   # Win Shares per 48 min
    ast_pct: Optional[float] = None     # Assist %
    stl_pct: Optional[float] = None     # Steal %
    blk_pct: Optional[float] = None     # Block %
    usg_pct: Optional[float] = None     # Usage %

    def per100(self) -> dict[str, float]:
        """Convert per-game stats to per-100 possessions using decade pace."""
        pace = DECADE_PACE.get(self.decade, 95.0)
        return {
            "PTS": per_game_to_per100(self.ppg, pace),
            "REB": per_game_to_per100(self.rpg, pace),
            "AST": per_game_to_per100(self.apg, pace),
            "STL": per_game_to_per100(self.spg, pace),
            "BLK": per_game_to_per100(self.bpg, pace),
        }

    def eligible_positions(self) -> list[str]:
        return get_eligible_positions(self.name, self.primary_position)


@dataclass
class LineupSlot:
    position: str       # PG | SG | SF | PF | C
    player: PlayerStats


@dataclass
class Lineup:
    slots: list[LineupSlot] = field(default_factory=list)

    def is_valid(self) -> bool:
        if len(self.slots) != 5:
            return False
        positions = [s.position for s in self.slots]
        required = {"PG", "SG", "SF", "PF", "C"}
        if set(positions) != required:
            return False
        # Each player must be eligible for the slot they fill
        for slot in self.slots:
            if slot.position not in slot.player.eligible_positions():
                return False
        return True

    def validation_errors(self) -> list[str]:
        errors = []
        if len(self.slots) != 5:
            errors.append(f"Need exactly 5 players, have {len(self.slots)}")
            return errors
        positions = [s.position for s in self.slots]
        required = {"PG", "SG", "SF", "PF", "C"}
        missing = required - set(positions)
        dupes = [p for p in required if positions.count(p) > 1]
        if missing:
            errors.append(f"Missing positions: {', '.join(missing)}")
        if dupes:
            errors.append(f"Duplicate positions: {', '.join(dupes)}")
        for slot in self.slots:
            if slot.position not in slot.player.eligible_positions():
                errors.append(
                    f"{slot.player.name} cannot play {slot.position} "
                    f"(eligible: {', '.join(slot.player.eligible_positions())})"
                )
        return errors


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _player_contribution(player: PlayerStats) -> float:
    """
    Raw contribution score for a single player.
    Uses per-100 stats (era-normalized) × category weights × award multiplier.
    """
    stats = player.per100()
    raw = sum(stats[cat] * CATEGORY_WEIGHTS[cat] for cat in CATEGORY_WEIGHTS)
    multiplier = get_award_multiplier(player.best_award)
    return raw * multiplier


def _balance_penalty(lineup: Lineup) -> float:
    """
    Penalize lineups that are weak in any category compared to a real NBA team.
    Uses era-adjusted league average baselines — the penalty only fires when
    the lineup falls below what a typical team produces, not just because
    one stat looks small relative to another.

    Returns a multiplier in [BALANCE_FLOOR_MULTIPLIER, 1.0].
    """
    # Sum each category across all five players
    totals: dict[str, float] = {cat: 0.0 for cat in CATEGORY_WEIGHTS}
    for slot in lineup.slots:
        stats = slot.player.per100()
        for cat in CATEGORY_WEIGHTS:
            totals[cat] += stats[cat]

    # Use the most common decade in the lineup as the baseline reference
    decades = [slot.player.decade for slot in lineup.slots]
    reference_decade = max(set(decades), key=decades.count)
    baseline = LEAGUE_BASELINE_PER100.get(
        reference_decade,
        LEAGUE_BASELINE_PER100["2010s"]
    )

    # For each category, compute how much of the baseline the lineup covers.
    # ratio >= 1.0 means at or above average → no penalty for that category.
    # ratio < 1.0 means below average → penalty proportional to the shortfall.
    worst_penalty = 1.0
    for cat in CATEGORY_WEIGHTS:
        cat_baseline = baseline[cat]
        if cat_baseline <= 0:
            continue
        ratio = totals[cat] / cat_baseline
        if ratio >= 1.0:
            continue  # at or above baseline — no penalty
        # Linearly interpolate: ratio=1.0 → no penalty, ratio=0.0 → full penalty
        cat_penalty = BALANCE_FLOOR_MULTIPLIER + (1.0 - BALANCE_FLOOR_MULTIPLIER) * ratio
        worst_penalty = min(worst_penalty, cat_penalty)

    return max(BALANCE_FLOOR_MULTIPLIER, min(1.0, worst_penalty))


def _strength_to_wins(strength: float) -> float:
    """
    Non-linear sigmoid-style curve mapping lineup strength → predicted wins (0-82).

    Calibrated so that:
    - An average NBA starter lineup (strength ≈ 300) → ~41 wins
    - A very strong lineup (strength ≈ 500) → ~70 wins
    - A near-perfect lineup (strength ≈ 700+) → approaches 82
    - Hitting exactly 82-0 happens roughly 1 in 35 games for a truly elite lineup

    We use a logistic curve: wins = 82 / (1 + e^(-k*(strength - midpoint)))
    """
    midpoint = 320.0   # strength value that maps to ~41 wins
    k = 0.012          # steepness; tuned so 82-0 requires strength ≈ 750+
    wins = 82.0 / (1.0 + math.exp(-k * (strength - midpoint)))
    return wins


def _add_noise(wins: float, seed: Optional[int] = None) -> float:
    """
    Add a small stochastic element so identical lineups don't always score
    identically (mirrors the original game's daily variation).
    Range: ±3 wins, capped to [0, 82].
    """
    import random
    rng = random.Random(seed)
    noise = rng.gauss(0, 1.5)
    return max(0.0, min(82.0, wins + noise))


def score_lineup(lineup: Lineup, deterministic: bool = False) -> dict:
    """
    Main entry point. Returns a dict with full scoring breakdown.

    Args:
        lineup: A valid 5-player Lineup
        deterministic: If True, skip noise (useful for testing)

    Returns:
        {
            "valid": bool,
            "errors": list[str],
            "player_contributions": list[dict],
            "raw_strength": float,
            "balance_multiplier": float,
            "adjusted_strength": float,
            "predicted_wins": float,
            "predicted_losses": float,
            "record": str,
        }
    """
    errors = lineup.validation_errors()
    if errors:
        return {"valid": False, "errors": errors}

    player_contribs = []
    for slot in lineup.slots:
        contrib = _player_contribution(slot.player)
        player_contribs.append({
            "position": slot.position,
            "name": slot.player.name,
            "team": slot.player.team,
            "decade": slot.player.decade,
            "best_season_year": slot.player.best_season_year,
            "best_award": slot.player.best_award,
            "award_multiplier": get_award_multiplier(slot.player.best_award),
            "per_game": {
                "PTS": slot.player.ppg,
                "REB": slot.player.rpg,
                "AST": slot.player.apg,
                "STL": slot.player.spg,
                "BLK": slot.player.bpg,
            },
            "per_100": slot.player.per100(),
            "contribution": contrib,
        })

    raw_strength = sum(p["contribution"] for p in player_contribs)
    balance_mult = _balance_penalty(lineup)
    adjusted_strength = raw_strength * balance_mult

    raw_wins = _strength_to_wins(adjusted_strength)
    predicted_wins = raw_wins if deterministic else _add_noise(raw_wins)
    predicted_wins = round(predicted_wins, 1)
    predicted_losses = round(82.0 - predicted_wins, 1)

    return {
        "valid": True,
        "errors": [],
        "player_contributions": player_contribs,
        "raw_strength": round(raw_strength, 2),
        "balance_multiplier": round(balance_mult, 3),
        "adjusted_strength": round(adjusted_strength, 2),
        "predicted_wins": predicted_wins,
        "predicted_losses": predicted_losses,
        "record": f"{int(round(predicted_wins))}-{int(round(predicted_losses))}",
    }


def format_result(result: dict, advanced: bool = False) -> str:
    """Pretty-print the scoring result for CLI / debug use."""
    if not result["valid"]:
        return "INVALID LINEUP:\n  " + "\n  ".join(result["errors"])

    lines = ["=" * 60, "LINEUP SCORING RESULT", "=" * 60]

    for p in result["player_contributions"]:
        lines.append(
            f"\n  [{p['position']}] {p['name']}  |  {p['team']} {p['decade']}  "
            f"({p['best_season_year']})"
        )
        pg = p["per_game"]
        lines.append(
            f"         PTS {pg['PTS']:.1f}  REB {pg['REB']:.1f}  "
            f"AST {pg['AST']:.1f}  STL {pg['STL']:.1f}  BLK {pg['BLK']:.1f}"
        )
        if p["best_award"] != "None":
            lines.append(
                f"         Award: {p['best_award']}  "
                f"(×{p['award_multiplier']:.2f})"
            )
        if advanced:
            p100 = p["per_100"]
            lines.append(
                f"         Per-100 → PTS {p100['PTS']:.1f}  REB {p100['REB']:.1f}  "
                f"AST {p100['AST']:.1f}  STL {p100['STL']:.1f}  BLK {p100['BLK']:.1f}"
            )
            lines.append(
                f"         Contribution score: {p['contribution']:.1f}"
            )

    lines.append("\n" + "-" * 60)
    lines.append(f"  Raw strength:       {result['raw_strength']}")
    lines.append(f"  Balance multiplier: {result['balance_multiplier']}")
    lines.append(f"  Adjusted strength:  {result['adjusted_strength']}")
    lines.append(f"\n  ★  PREDICTED RECORD:  {result['record']}  ★")
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Build a sample "Dream Team" style lineup to verify the engine works

    magic = PlayerStats(
        name="Magic Johnson", team="Lakers", decade="1980s",
        primary_position="PG", best_season_year=1987,
        ppg=23.9, rpg=6.3, apg=12.2, spg=1.7, bpg=0.5,
        best_award="MVP",
        ts_pct=0.596, ws_per_48=0.277, ast_pct=48.2, usg_pct=27.1,
    )

    jordan = PlayerStats(
        name="Michael Jordan", team="Bulls", decade="1990s",
        primary_position="SG", best_season_year=1996,
        ppg=30.4, rpg=6.6, apg=4.3, spg=2.2, bpg=0.5,
        best_award="MVP",
        ts_pct=0.587, ws_per_48=0.250, usg_pct=35.8,
    )

    lebron = PlayerStats(
        name="LeBron James", team="Heat", decade="2010s",
        primary_position="SF", best_season_year=2013,
        ppg=26.8, rpg=8.0, apg=7.3, spg=1.7, bpg=0.9,
        best_award="MVP",
        ts_pct=0.640, ws_per_48=0.298, usg_pct=31.6,
    )

    giannis = PlayerStats(
        name="Giannis Antetokounmpo", team="Bucks", decade="2020s",
        primary_position="PF", best_season_year=2020,
        ppg=29.6, rpg=13.7, apg=5.8, spg=1.0, bpg=1.0,
        best_award="MVP",
        ts_pct=0.618, ws_per_48=0.282, usg_pct=36.6,
    )

    shaq = PlayerStats(
        name="Shaquille O'Neal", team="Lakers", decade="2000s",
        primary_position="C", best_season_year=2000,
        ppg=29.7, rpg=13.6, apg=3.8, spg=0.5, bpg=3.0,
        best_award="MVP",
        ts_pct=0.604, ws_per_48=0.258, usg_pct=36.9,
    )

    lineup = Lineup(slots=[
        LineupSlot("PG", magic),
        LineupSlot("SG", jordan),
        LineupSlot("SF", lebron),
        LineupSlot("PF", giannis),
        LineupSlot("C", shaq),
    ])

    result = score_lineup(lineup, deterministic=True)
    print(format_result(result, advanced=True))

    # Also test a weak lineup to verify the balance penalty works
    print("\n\n--- WEAK / UNBALANCED LINEUP TEST ---\n")

    weak_pg = PlayerStats(
        name="Average PG", team="Test", decade="2010s",
        primary_position="PG", best_season_year=2015,
        ppg=12.0, rpg=3.0, apg=6.0, spg=0.8, bpg=0.1,
        best_award="None",
    )
    weak_sg = PlayerStats(
        name="Average SG", team="Test", decade="2010s",
        primary_position="SG", best_season_year=2015,
        ppg=14.0, rpg=3.5, apg=2.5, spg=1.0, bpg=0.2,
        best_award="None",
    )
    weak_sf = PlayerStats(
        name="Average SF", team="Test", decade="2010s",
        primary_position="SF", best_season_year=2015,
        ppg=15.0, rpg=5.0, apg=2.0, spg=0.8, bpg=0.4,
        best_award="None",
    )
    weak_pf = PlayerStats(
        name="Average PF", team="Test", decade="2010s",
        primary_position="PF", best_season_year=2015,
        ppg=13.0, rpg=7.0, apg=1.5, spg=0.5, bpg=0.8,
        best_award="None",
    )
    weak_c = PlayerStats(
        name="Average C", team="Test", decade="2010s",
        primary_position="C", best_season_year=2015,
        ppg=10.0, rpg=8.0, apg=1.0, spg=0.4, bpg=1.2,
        best_award="None",
    )

    weak_lineup = Lineup(slots=[
        LineupSlot("PG", weak_pg),
        LineupSlot("SG", weak_sg),
        LineupSlot("SF", weak_sf),
        LineupSlot("PF", weak_pf),
        LineupSlot("C", weak_c),
    ])

    weak_result = score_lineup(weak_lineup, deterministic=True)
    print(format_result(weak_result))
