from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from bot_sim import BotProfile, BotSimulator, apply_profile_overrides, parse_profiles


PLAYER_SEAT_RE = re.compile(r"^[A-Za-z](\d+)-")


def parse_float_csv(value: str) -> List[float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ValueError("Expected at least one numeric value")
    out: List[float] = []
    for part in parts:
        out.append(float(part))
    return out


def parse_contract(contract: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not contract:
        return None, None
    pieces = contract.strip().split(maxsplit=1)
    if not pieces:
        return None, None
    try:
        value = int(pieces[0])
    except ValueError:
        value = None
    trump = pieces[1] if len(pieces) > 1 else None
    return value, trump


def parse_player_seat(player_name: str) -> Optional[int]:
    match = PLAYER_SEAT_RE.match(player_name)
    if not match:
        return None
    try:
        return int(match.group(1)) - 1
    except ValueError:
        return None


def clone_profiles(profiles: Sequence[BotProfile]) -> List[BotProfile]:
    return [BotProfile(**asdict(profile)) for profile in profiles]


def apply_play_candidate(
    profiles: Sequence[BotProfile],
    candidate_seats: Iterable[int],
    lead_high_bias: Optional[float] = None,
    trump_spend_bias: Optional[float] = None,
    random_play_jitter: Optional[float] = None,
    nt_cash_top_bias: Optional[float] = None,
    nt_entry_preserve_bias: Optional[float] = None,
    nt_duck_bias: Optional[float] = None,
) -> List[BotProfile]:
    updated = clone_profiles(profiles)
    for seat in candidate_seats:
        if lead_high_bias is not None:
            updated[seat].lead_high_bias = lead_high_bias
        if trump_spend_bias is not None:
            updated[seat].trump_spend_bias = trump_spend_bias
        if random_play_jitter is not None:
            updated[seat].random_play_jitter = random_play_jitter
        if nt_cash_top_bias is not None:
            updated[seat].nt_cash_top_bias = nt_cash_top_bias
        if nt_entry_preserve_bias is not None:
            updated[seat].nt_entry_preserve_bias = nt_entry_preserve_bias
        if nt_duck_bias is not None:
            updated[seat].nt_duck_bias = nt_duck_bias
    return updated


def collect_run_metrics(simulator: BotSimulator, candidate_team: int, candidate_seats: set[int], game_score: List[int]) -> Dict[str, float]:
    # Track highest-bid owner per hand so we can resolve no-trump declarer at hand_complete.
    highest_by_hand: Dict[int, Dict[str, Optional[int] | Optional[str]]] = {}

    nt_attempts_all = 0
    nt_makes_all = 0

    nt_attempts_candidate = 0
    nt_makes_candidate = 0
    nt_margin_sum_candidate = 0.0

    for rec in simulator.decisions:
        hand_state = highest_by_hand.setdefault(
            rec.hand,
            {
                "highest_player": None,
                "highest_value": None,
                "highest_trump": None,
            },
        )

        if rec.phase == "bidding" and rec.player != "SYSTEM":
            seat = parse_player_seat(rec.player)
            if seat is None:
                continue

            if rec.action == "bid":
                value = rec.payload.get("value")
                if isinstance(value, int):
                    hand_state["highest_player"] = seat
                    hand_state["highest_value"] = value
                    hand_state["highest_trump"] = rec.payload.get("trump") if isinstance(rec.payload.get("trump"), str) else "hidden"
            elif rec.action == "take":
                if hand_state.get("highest_value") is not None:
                    hand_state["highest_player"] = seat
                    if rec.payload.get("trump") == "no-trump":
                        hand_state["highest_trump"] = "no-trump"

        if rec.action != "hand_complete":
            continue

        value, trump = parse_contract(rec.payload.get("contract") if isinstance(rec.payload, dict) else None)
        if trump != "no-trump" or value is None:
            continue

        team0_points = rec.payload.get("team0_points")
        team1_points = rec.payload.get("team1_points")
        if not isinstance(team0_points, int) or not isinstance(team1_points, int):
            continue

        highest_player = hand_state.get("highest_player")
        if not isinstance(highest_player, int):
            continue

        declarer_team = highest_player % 2
        declarer_points = team0_points if declarer_team == 0 else team1_points
        made = declarer_points >= value

        nt_attempts_all += 1
        nt_makes_all += 1 if made else 0

        if highest_player in candidate_seats:
            nt_attempts_candidate += 1
            nt_makes_candidate += 1 if made else 0
            nt_margin_sum_candidate += float(declarer_points - value)

    candidate_score = game_score[candidate_team]
    opponent_score = game_score[1 - candidate_team]

    return {
        "candidate_win": 1.0 if candidate_score > opponent_score else 0.5 if candidate_score == opponent_score else 0.0,
        "candidate_score_diff": float(candidate_score - opponent_score),
        "nt_attempts_all": float(nt_attempts_all),
        "nt_makes_all": float(nt_makes_all),
        "nt_attempts_candidate": float(nt_attempts_candidate),
        "nt_makes_candidate": float(nt_makes_candidate),
        "nt_margin_sum_candidate": nt_margin_sum_candidate,
    }


def run_match(
    profiles: Sequence[BotProfile],
    hands: int,
    seed: int,
    candidate_team: int,
    candidate_seats: set[int],
) -> Dict[str, float]:
    sim = BotSimulator(profiles=clone_profiles(profiles), seed=seed)
    game, _ = sim.run(hands=hands)
    return collect_run_metrics(sim, candidate_team=candidate_team, candidate_seats=candidate_seats, game_score=game.game_score)


def aggregate_results(rows: List[Dict[str, float]]) -> Dict[str, float]:
    total: Dict[str, float] = {}
    for row in rows:
        for key, value in row.items():
            total[key] = total.get(key, 0.0) + value

    runs = float(len(rows)) if rows else 1.0
    attempts_all = total.get("nt_attempts_all", 0.0)
    makes_all = total.get("nt_makes_all", 0.0)
    attempts_candidate = total.get("nt_attempts_candidate", 0.0)
    makes_candidate = total.get("nt_makes_candidate", 0.0)

    return {
        "runs": runs,
        "win_rate": total.get("candidate_win", 0.0) / runs,
        "avg_score_diff": total.get("candidate_score_diff", 0.0) / runs,
        "nt_attempts_all": attempts_all,
        "nt_make_rate_all": (makes_all / attempts_all) if attempts_all > 0 else 0.0,
        "nt_attempts_candidate": attempts_candidate,
        "nt_make_rate_candidate": (makes_candidate / attempts_candidate) if attempts_candidate > 0 else 0.0,
        "nt_avg_margin_candidate": (total.get("nt_margin_sum_candidate", 0.0) / attempts_candidate) if attempts_candidate > 0 else 0.0,
    }


def candidate_label(
    lead_high_bias: Optional[float],
    trump_spend_bias: Optional[float],
    random_play_jitter: Optional[float],
    nt_cash_top_bias: Optional[float],
    nt_entry_preserve_bias: Optional[float],
    nt_duck_bias: Optional[float],
) -> str:
    parts: List[str] = []
    if lead_high_bias is not None:
        parts.append(f"lead={lead_high_bias:.2f}")
    if trump_spend_bias is not None:
        parts.append(f"trump={trump_spend_bias:.2f}")
    if random_play_jitter is not None:
        parts.append(f"jitter={random_play_jitter:.2f}")
    if nt_cash_top_bias is not None:
        parts.append(f"nt_cash={nt_cash_top_bias:.2f}")
    if nt_entry_preserve_bias is not None:
        parts.append(f"nt_entry={nt_entry_preserve_bias:.2f}")
    if nt_duck_bias is not None:
        parts.append(f"nt_duck={nt_duck_bias:.2f}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Play-only no-trump tuning harness. Bidding/contract parameters stay fixed from base profiles/overrides; "
            "only play knobs are swept for candidate seats against baseline opponents."
        )
    )
    parser.add_argument("--profiles", type=str, default="balanced,aggressive,cautious,chaotic", help="Comma-separated 4 profiles")
    parser.add_argument("--base-overrides", type=str, default=None, help="Optional JSON overrides file applied before tuning")
    parser.add_argument("--hands", type=int, default=150, help="Max hands per simulation run")
    parser.add_argument("--seed-start", type=int, default=1, help="First seed in range")
    parser.add_argument("--seed-count", type=int, default=20, help="How many sequential seeds to run")
    parser.add_argument(
        "--sweep-knobs",
        type=str,
        choices=("legacy", "nt", "all"),
        default="legacy",
        help="Which knob groups to sweep: legacy (lead/trump/jitter), nt (nt_* only), or all",
    )
    parser.add_argument("--lead-high-values", type=str, default="0.2,0.4,0.6,0.8", help="CSV values for lead_high_bias")
    parser.add_argument("--trump-spend-values", type=str, default="0.2,0.4,0.6,0.8", help="CSV values for trump_spend_bias")
    parser.add_argument("--jitter-values", type=str, default="0.0,0.05,0.1,0.2", help="CSV values for random_play_jitter")
    parser.add_argument("--nt-cash-values", type=str, default="0.6,0.75,0.9", help="CSV values for nt_cash_top_bias")
    parser.add_argument("--nt-entry-values", type=str, default="0.4,0.6,0.8", help="CSV values for nt_entry_preserve_bias")
    parser.add_argument("--nt-duck-values", type=str, default="0.1,0.25,0.4", help="CSV values for nt_duck_bias")
    parser.add_argument("--top-k", type=int, default=10, help="How many top candidates to print")
    parser.add_argument("--out-json", type=str, default="nt_play_tuning_results.json", help="Where to write full JSON results")
    parser.add_argument("--out-csv", type=str, default="nt_play_tuning_leaderboard.csv", help="Where to write leaderboard CSV")
    args = parser.parse_args()

    base_profiles = parse_profiles(args.profiles)
    apply_profile_overrides(base_profiles, args.base_overrides)

    lead_values = parse_float_csv(args.lead_high_values)
    trump_values = parse_float_csv(args.trump_spend_values)
    jitter_values = parse_float_csv(args.jitter_values)
    nt_cash_values = parse_float_csv(args.nt_cash_values)
    nt_entry_values = parse_float_csv(args.nt_entry_values)
    nt_duck_values = parse_float_csv(args.nt_duck_values)

    seeds = [args.seed_start + i for i in range(args.seed_count)]
    if args.sweep_knobs == "legacy":
        candidate_grid = [
            {
                "lead_high_bias": lead,
                "trump_spend_bias": trump,
                "random_play_jitter": jitter,
                "nt_cash_top_bias": None,
                "nt_entry_preserve_bias": None,
                "nt_duck_bias": None,
            }
            for lead, trump, jitter in product(lead_values, trump_values, jitter_values)
        ]
    elif args.sweep_knobs == "nt":
        candidate_grid = [
            {
                "lead_high_bias": None,
                "trump_spend_bias": None,
                "random_play_jitter": None,
                "nt_cash_top_bias": nt_cash,
                "nt_entry_preserve_bias": nt_entry,
                "nt_duck_bias": nt_duck,
            }
            for nt_cash, nt_entry, nt_duck in product(nt_cash_values, nt_entry_values, nt_duck_values)
        ]
    else:
        candidate_grid = [
            {
                "lead_high_bias": lead,
                "trump_spend_bias": trump,
                "random_play_jitter": jitter,
                "nt_cash_top_bias": nt_cash,
                "nt_entry_preserve_bias": nt_entry,
                "nt_duck_bias": nt_duck,
            }
            for lead, trump, jitter, nt_cash, nt_entry, nt_duck in product(
                lead_values,
                trump_values,
                jitter_values,
                nt_cash_values,
                nt_entry_values,
                nt_duck_values,
            )
        ]

    results: List[Dict[str, object]] = []

    for candidate in candidate_grid:
        lead_high_bias = candidate["lead_high_bias"]
        trump_spend_bias = candidate["trump_spend_bias"]
        random_play_jitter = candidate["random_play_jitter"]
        nt_cash_top_bias = candidate["nt_cash_top_bias"]
        nt_entry_preserve_bias = candidate["nt_entry_preserve_bias"]
        nt_duck_bias = candidate["nt_duck_bias"]
        run_rows: List[Dict[str, float]] = []

        for seed in seeds:
            # Candidate on Team 0 seats (0,2), baseline on Team 1 seats (1,3)
            p_team0 = apply_play_candidate(
                profiles=base_profiles,
                candidate_seats=(0, 2),
                lead_high_bias=lead_high_bias,
                trump_spend_bias=trump_spend_bias,
                random_play_jitter=random_play_jitter,
                nt_cash_top_bias=nt_cash_top_bias,
                nt_entry_preserve_bias=nt_entry_preserve_bias,
                nt_duck_bias=nt_duck_bias,
            )
            run_rows.append(
                run_match(
                    profiles=p_team0,
                    hands=args.hands,
                    seed=seed,
                    candidate_team=0,
                    candidate_seats={0, 2},
                )
            )

            # Mirror seats for fairness: candidate on Team 1 seats (1,3)
            p_team1 = apply_play_candidate(
                profiles=base_profiles,
                candidate_seats=(1, 3),
                lead_high_bias=lead_high_bias,
                trump_spend_bias=trump_spend_bias,
                random_play_jitter=random_play_jitter,
                nt_cash_top_bias=nt_cash_top_bias,
                nt_entry_preserve_bias=nt_entry_preserve_bias,
                nt_duck_bias=nt_duck_bias,
            )
            run_rows.append(
                run_match(
                    profiles=p_team1,
                    hands=args.hands,
                    seed=seed,
                    candidate_team=1,
                    candidate_seats={1, 3},
                )
            )

        agg = aggregate_results(run_rows)
        results.append(
            {
                "label": candidate_label(
                    lead_high_bias,
                    trump_spend_bias,
                    random_play_jitter,
                    nt_cash_top_bias,
                    nt_entry_preserve_bias,
                    nt_duck_bias,
                ),
                "lead_high_bias": lead_high_bias,
                "trump_spend_bias": trump_spend_bias,
                "random_play_jitter": random_play_jitter,
                "nt_cash_top_bias": nt_cash_top_bias,
                "nt_entry_preserve_bias": nt_entry_preserve_bias,
                "nt_duck_bias": nt_duck_bias,
                **agg,
            }
        )

    # Rank primarily by no-trump make rate for tuned seats, then by no-trump margin, then win rate.
    ranked = sorted(
        results,
        key=lambda row: (
            float(row["nt_make_rate_candidate"]),
            float(row["nt_avg_margin_candidate"]),
            float(row["win_rate"]),
            float(row["avg_score_diff"]),
        ),
        reverse=True,
    )

    json_payload = {
        "config": {
            "profiles": args.profiles,
            "base_overrides": args.base_overrides,
            "hands": args.hands,
            "seed_start": args.seed_start,
            "seed_count": args.seed_count,
            "sweep_knobs": args.sweep_knobs,
            "lead_high_values": lead_values,
            "trump_spend_values": trump_values,
            "jitter_values": jitter_values,
            "nt_cash_values": nt_cash_values,
            "nt_entry_values": nt_entry_values,
            "nt_duck_values": nt_duck_values,
            "candidate_count": len(candidate_grid),
            "run_count": len(candidate_grid) * len(seeds) * 2,
        },
        "ranked_results": ranked,
    }

    Path(args.out_json).write_text(json.dumps(json_payload, indent=2) + "\n", encoding="utf-8")

    with Path(args.out_csv).open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "label",
            "lead_high_bias",
            "trump_spend_bias",
            "random_play_jitter",
            "nt_cash_top_bias",
            "nt_entry_preserve_bias",
            "nt_duck_bias",
            "runs",
            "nt_attempts_candidate",
            "nt_make_rate_candidate",
            "nt_avg_margin_candidate",
            "nt_attempts_all",
            "nt_make_rate_all",
            "win_rate",
            "avg_score_diff",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ranked:
            writer.writerow({key: row.get(key) for key in fieldnames})

    top_k = max(1, min(args.top_k, len(ranked)))
    print("No-trump play tuning complete")
    print(f"Candidates evaluated: {len(candidate_grid)}")
    print(f"Total simulation runs: {len(candidate_grid) * len(seeds) * 2}")
    print(f"JSON results: {args.out_json}")
    print(f"CSV leaderboard: {args.out_csv}")
    print(f"Top {top_k} candidates:")

    for idx, row in enumerate(ranked[:top_k], start=1):
        print(
            f"{idx:2}. {row['label']} | "
            f"nt_make_rate_candidate={row['nt_make_rate_candidate']:.3f} "
            f"nt_avg_margin_candidate={row['nt_avg_margin_candidate']:.3f} "
            f"win_rate={row['win_rate']:.3f} score_diff={row['avg_score_diff']:.3f} "
            f"nt_attempts_candidate={int(row['nt_attempts_candidate'])}"
        )


if __name__ == "__main__":
    main()
