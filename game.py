"""
82-0 Game — Spin Mechanic
--------------------------
Manages the full game state: spins, respins, lineup construction, and submission.

Rules (from spec):
  - 5 spins, each produces a (team, decade) pair
  - One respin of TEAM only available per game
  - One respin of ERA (decade) only available per game
  - Pick from top 4 players per position (20 per spin)
  - Final lineup: exactly PG, SG, SF, PF, C — one each
  - Players can fill any eligible position (flexibility tier)
  - Lineup can be rearranged freely before submission
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from player_db import get_players_for_spin, PlayerOption, DECADE_YEARS
from scoring_engine import Lineup, LineupSlot, PlayerStats, score_lineup, format_result

# ---------------------------------------------------------------------------
# Spin pool — franchises with enough history to be interesting across decades
# Organised by which decades they have meaningful rosters in
# ---------------------------------------------------------------------------

TEAM_DECADE_POOL: dict[str, list[str]] = {
    "Atlanta Hawks":              ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s"],
    "Boston Celtics":             ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"],
    "Chicago Bulls":              ["1970s", "1980s", "1990s", "2000s", "2010s"],
    "Cleveland Cavaliers":        ["1990s", "2000s", "2010s", "2020s"],
    "Dallas Mavericks":           ["1990s", "2000s", "2010s", "2020s"],
    "Denver Nuggets":             ["1980s", "1990s", "2000s", "2010s", "2020s"],
    "Detroit Pistons":            ["1980s", "1990s", "2000s", "2010s"],
    "Golden State Warriors":      ["1970s", "1990s", "2000s", "2010s", "2020s"],
    "Houston Rockets":            ["1980s", "1990s", "2000s", "2010s", "2020s"],
    "Indiana Pacers":             ["1990s", "2000s", "2010s", "2020s"],
    "Los Angeles Clippers":       ["2000s", "2010s", "2020s"],
    "Los Angeles Lakers":         ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"],
    "Miami Heat":                 ["1990s", "2000s", "2010s", "2020s"],
    "Milwaukee Bucks":            ["1970s", "1980s", "2000s", "2010s", "2020s"],
    "Minnesota Timberwolves":     ["2000s", "2010s", "2020s"],
    "New York Knicks":            ["1960s", "1970s", "1980s", "1990s", "2000s"],
    "Oklahoma City Thunder":      ["2010s", "2020s"],
    "Orlando Magic":              ["1990s", "2000s", "2010s"],
    "Philadelphia 76ers":         ["1960s", "1970s", "1980s", "2000s", "2010s", "2020s"],
    "Phoenix Suns":               ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"],
    "Portland Trail Blazers":     ["1970s", "1980s", "1990s", "2000s", "2010s"],
    "Sacramento Kings":           ["1980s", "1990s", "2000s"],
    "San Antonio Spurs":          ["1980s", "1990s", "2000s", "2010s", "2020s"],
    "Seattle Supersonics":        ["1970s", "1980s", "1990s", "2000s"],
    "Toronto Raptors":            ["2000s", "2010s", "2020s"],
    "Utah Jazz":                  ["1980s", "1990s", "2000s", "2010s"],
    "Washington Bullets":         ["1970s", "1980s"],
    "Washington Wizards":         ["1990s", "2000s", "2010s"],
}

ALL_DECADES = ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class RespinType(Enum):
    TEAM = "team"
    ERA  = "era"


@dataclass
class Spin:
    """A single slot in the game — one (team, decade) pair and the players it produced."""
    index: int                          # 0-4
    team: str
    decade: str
    players: dict[str, list[PlayerOption]] = field(default_factory=dict)
    # Which player the user picked for this spin (set after selection)
    selected_player: Optional[PlayerStats] = None
    # Which position slot the user assigned this player to
    assigned_position: Optional[str] = None

    def is_resolved(self) -> bool:
        return self.selected_player is not None and self.assigned_position is not None

    def label(self) -> str:
        return f"{self.team}  |  {self.decade}"


@dataclass
class GameState:
    """Full state of one game session."""
    spins: list[Spin] = field(default_factory=list)

    # Respin tokens — one of each, consumed on use
    team_respin_available: bool = True
    era_respin_available: bool  = True

    # Tracks which spins were respun and how
    respin_log: list[dict] = field(default_factory=list)

    # Final submitted lineup (set on submission)
    submitted_lineup: Optional[Lineup] = None
    result: Optional[dict] = None

    def all_spins_resolved(self) -> bool:
        return len(self.spins) == 5 and all(s.is_resolved() for s in self.spins)

    def current_assignments(self) -> dict[str, PlayerStats]:
        """Return {position: player} for all assigned slots so far."""
        return {
            s.assigned_position: s.selected_player
            for s in self.spins
            if s.is_resolved()
        }

    def positions_taken(self) -> set[str]:
        return set(self.current_assignments().keys())

    def positions_available(self) -> list[str]:
        all_pos = ["PG", "SG", "SF", "PF", "C"]
        taken = self.positions_taken()
        return [p for p in all_pos if p not in taken]


# ---------------------------------------------------------------------------
# Core game logic
# ---------------------------------------------------------------------------

def _random_spin(exclude_teams: list[str] = None,
                 exclude_decades: list[str] = None,
                 rng: random.Random = None) -> tuple[str, str]:
    """Pick a random (team, decade) pair from the pool."""
    if rng is None:
        rng = random.Random()
    exclude_teams  = exclude_teams  or []
    exclude_decades = exclude_decades or []

    candidates = [
        (team, decade)
        for team, decades in TEAM_DECADE_POOL.items()
        for decade in decades
        if team not in exclude_teams and decade not in exclude_decades
    ]

    if not candidates:
        # Fall back without filters if nothing qualifies
        candidates = [
            (team, decade)
            for team, decades in TEAM_DECADE_POOL.items()
            for decade in decades
        ]

    return rng.choice(candidates)


def start_game(seed: Optional[int] = None) -> GameState:
    """
    Initialise a new game: generate 5 (team, decade) pairs and fetch players.
    Pairs are unique — no duplicate (team, decade) combos in one game.
    """
    rng = random.Random(seed)
    state = GameState()

    used_pairs: set[tuple[str, str]] = set()

    for i in range(5):
        # Keep trying until we get a fresh pair
        for _ in range(50):
            team, decade = _random_spin(rng=rng)
            if (team, decade) not in used_pairs:
                break

        used_pairs.add((team, decade))
        players = _fetch_players(team, decade)
        state.spins.append(Spin(index=i, team=team, decade=decade, players=players))

    return state


def _fetch_players(team: str, decade: str) -> dict[str, list[PlayerOption]]:
    """Fetch players with a friendly progress message."""
    print(f"  Loading {team} {decade}...", flush=True)
    return get_players_for_spin(team, decade, top_n_per_position=4)


# ---------------------------------------------------------------------------
# Respin
# ---------------------------------------------------------------------------

def respin_team(state: GameState, spin_index: int) -> GameState:
    """
    Re-roll the TEAM for a given spin, keeping the same decade.
    Consumes the team respin token.
    """
    if not state.team_respin_available:
        raise ValueError("Team respin already used this game.")

    spin = state.spins[spin_index]
    old_team = spin.team
    decade = spin.decade

    # Exclude teams already used in this game
    used_teams = [s.team for s in state.spins]

    rng = random.Random()
    for _ in range(50):
        new_team, _ = _random_spin(exclude_decades=[d for d in ALL_DECADES if d != decade], rng=rng)
        if new_team not in used_teams:
            break

    spin.team = new_team
    spin.players = _fetch_players(new_team, decade)
    # Clear any existing selection on this spin
    spin.selected_player = None
    spin.assigned_position = None

    state.team_respin_available = False
    state.respin_log.append({
        "spin_index": spin_index,
        "type": "team",
        "from": old_team,
        "to": new_team,
        "decade_kept": decade,
    })

    return state


def respin_era(state: GameState, spin_index: int) -> GameState:
    """
    Re-roll the DECADE for a given spin, keeping the same team.
    Consumes the era respin token.
    """
    if not state.era_respin_available:
        raise ValueError("Era respin already used this game.")

    spin = state.spins[spin_index]
    team = spin.team
    old_decade = spin.decade

    # Pick a different decade that this team has data in
    available_decades = [
        d for d in TEAM_DECADE_POOL.get(team, [])
        if d != old_decade
    ]
    if not available_decades:
        raise ValueError(f"{team} has no other decades available.")

    new_decade = random.choice(available_decades)
    spin.decade = new_decade
    spin.players = _fetch_players(team, new_decade)
    spin.selected_player = None
    spin.assigned_position = None

    state.era_respin_available = False
    state.respin_log.append({
        "spin_index": spin_index,
        "type": "era",
        "team_kept": team,
        "from": old_decade,
        "to": new_decade,
    })

    return state


# ---------------------------------------------------------------------------
# Player selection & lineup management
# ---------------------------------------------------------------------------

def select_player(state: GameState,
                  spin_index: int,
                  player_name: str,
                  position: str) -> GameState:
    """
    Assign a player from a spin to a lineup position.
    Validates:
      - Player exists in that spin's pool
      - Player is eligible for that position
      - Position isn't already taken by another spin
    """
    spin = state.spins[spin_index]
    position = position.upper()

    # Find player in pool
    player = _find_player_in_spin(spin, player_name)
    if player is None:
        available = _all_players_in_spin(spin)
        raise ValueError(
            f"'{player_name}' not found in {spin.label()}.\n"
            f"Available: {', '.join(available)}"
        )

    # Check position eligibility
    eligible = player.eligible_positions()
    if position not in eligible:
        raise ValueError(
            f"{player_name} cannot play {position}. "
            f"Eligible positions: {', '.join(eligible)}"
        )

    # Check position not already taken by a DIFFERENT spin
    for i, other in enumerate(state.spins):
        if i != spin_index and other.assigned_position == position:
            raise ValueError(
                f"{position} is already filled by "
                f"{other.selected_player.name} (spin {i + 1})."
            )

    spin.selected_player = player
    spin.assigned_position = position
    return state


def move_player(state: GameState,
                spin_index: int,
                new_position: str) -> GameState:
    """
    Move a player to a new position slot.
    If the target slot is occupied, swap the two players.
    Both players must be eligible for their new positions.
    """
    spin = state.spins[spin_index]
    if spin.selected_player is None:
        raise ValueError(f"Spin {spin_index + 1} has no player selected yet.")

    new_position = new_position.upper()
    eligible = spin.selected_player.eligible_positions()
    if new_position not in eligible:
        raise ValueError(
            f"{spin.selected_player.name} cannot play {new_position}. "
            f"Eligible: {', '.join(eligible)}"
        )

    # Check if target position is already occupied
    occupying_spin = next(
        (s for i, s in enumerate(state.spins)
         if i != spin_index and s.assigned_position == new_position),
        None
    )

    if occupying_spin is not None:
        # Swap: other player must also be eligible for the position we're vacating
        old_position = spin.assigned_position
        other_eligible = occupying_spin.selected_player.eligible_positions()
        if old_position and old_position not in other_eligible:
            raise ValueError(
                f"Cannot swap: {occupying_spin.selected_player.name} is not eligible "
                f"for {old_position} (eligible: {', '.join(other_eligible)})"
            )
        occupying_spin.assigned_position = old_position

    spin.assigned_position = new_position
    return state


def clear_selection(state: GameState, spin_index: int) -> GameState:
    """Remove the player/position assignment for a spin so it can be re-picked."""
    state.spins[spin_index].selected_player = None
    state.spins[spin_index].assigned_position = None
    return state


# ---------------------------------------------------------------------------
# Lineup submission
# ---------------------------------------------------------------------------

def submit_lineup(state: GameState) -> GameState:
    """
    Build the final Lineup, run the scoring engine, and attach the result.
    """
    if not state.all_spins_resolved():
        unresolved = [i + 1 for i, s in enumerate(state.spins) if not s.is_resolved()]
        raise ValueError(f"Spins {unresolved} still need a player and position.")

    slots = [
        LineupSlot(position=s.assigned_position, player=s.selected_player)
        for s in state.spins
    ]
    lineup = Lineup(slots=slots)

    errors = lineup.validation_errors()
    if errors:
        raise ValueError("Invalid lineup:\n  " + "\n  ".join(errors))

    state.submitted_lineup = lineup
    state.result = score_lineup(lineup)
    return state


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _find_player_in_spin(spin: Spin, name: str) -> Optional[PlayerStats]:
    name_lower = name.lower()
    for opts in spin.players.values():
        for opt in opts:
            if opt.stats.name.lower() == name_lower:
                return opt.stats
    return None


def _all_players_in_spin(spin: Spin) -> list[str]:
    seen = set()
    names = []
    for opts in spin.players.values():
        for opt in opts:
            if opt.stats.name not in seen:
                seen.add(opt.stats.name)
                names.append(opt.stats.name)
    return names


def display_game_state(state: GameState, advanced: bool = False) -> None:
    """Print full game state to terminal."""
    print("\n" + "=" * 62)
    print("  82-0 GAME")
    print("=" * 62)

    tokens = []
    if state.team_respin_available:
        tokens.append("Team respin ✓")
    else:
        tokens.append("Team respin ✗ (used)")
    if state.era_respin_available:
        tokens.append("Era respin ✓")
    else:
        tokens.append("Era respin ✗ (used)")
    print(f"  Tokens:  {' | '.join(tokens)}\n")

    for spin in state.spins:
        _display_spin(spin, advanced)

    # Lineup summary
    assigned = state.current_assignments()
    if assigned:
        print("\n  CURRENT LINEUP:")
        for pos in ["PG", "SG", "SF", "PF", "C"]:
            if pos in assigned:
                p = assigned[pos]
                award = f"  [{p.best_award}]" if p.best_award != "None" else ""
                print(f"    {pos}  {p.name:<25} {p.team} {p.decade}{award}")
            else:
                print(f"    {pos}  —")

    if state.result:
        from scoring_engine import format_result
        print("\n" + format_result(state.result, advanced))


def _display_spin(spin: Spin, advanced: bool = False) -> None:
    status = ""
    if spin.selected_player:
        status = f"  → {spin.assigned_position}: {spin.selected_player.name}"

    print(f"\n  Spin {spin.index + 1}: {spin.label()}{status}")

    if not spin.players:
        print("    (no players loaded)")
        return

    for pos in ["PG", "SG", "SF", "PF", "C"]:
        opts = spin.players.get(pos, [])
        if not opts:
            continue
        print(f"    {pos}")
        for i, opt in enumerate(opts, 1):
            s = opt.stats
            award = f"  [{s.best_award}]" if s.best_award != "None" else ""
            print(
                f"      {i}. {s.name:<25} "
                f"PTS {s.ppg:>5.1f}  REB {s.rpg:>4.1f}  "
                f"AST {s.apg:>4.1f}  STL {s.spg:>4.1f}  BLK {s.bpg:>4.1f}"
                f"{award}"
            )
            if advanced and s.ts_pct:
                print(
                    f"         TS% {s.ts_pct:.3f}  "
                    f"WS/48 {(s.ws_per_48 or 0):.3f}  "
                    f"USG% {(s.usg_pct or 0):.1f}"
                )


# ---------------------------------------------------------------------------
# Quick interactive demo (CLI)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting new game...\n")
    state = start_game(seed=42)

    display_game_state(state)

    print("\n\n--- Simulating player picks ---\n")

    # Auto-pick the top player from each spin at their primary position
    for spin in state.spins:
        for pos in ["PG", "SG", "SF", "PF", "C"]:
            opts = spin.players.get(pos, [])
            if opts:
                available_positions = [
                    p for p in state.positions_available()
                    if p in opts[0].stats.eligible_positions()
                ]
                if available_positions:
                    try:
                        select_player(state, spin.index, opts[0].stats.name, available_positions[0])
                        print(
                            f"  Spin {spin.index+1}: {opts[0].stats.name} → {available_positions[0]}"
                        )
                    except ValueError as e:
                        print(f"  Spin {spin.index+1} skip: {e}")
                    break

    print("\n--- Submitting lineup ---\n")
    try:
        state = submit_lineup(state)
        from scoring_engine import format_result
        print(format_result(state.result, advanced=True))
    except ValueError as e:
        print(f"Submission error: {e}")
        display_game_state(state)
