from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Record:
    hand: int
    trick: int
    phase: str
    player: str
    action: str
    payload: Dict[str, object]
    reason: str


@dataclass
class HandSummary:
    hand: int
    declarer: Optional[str]
    contract_value: Optional[int]
    contract_trump: Optional[str]
    team_points: Dict[int, Optional[int]]
    team_score: Dict[int, Optional[int]]


def load_records(path: str) -> Tuple[List[Record], int]:
    records: List[Record] = []
    skipped = 0

    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                records.append(
                    Record(
                        hand=int(data["hand"]),
                        trick=int(data["trick"]),
                        phase=str(data["phase"]),
                        player=str(data["player"]),
                        action=str(data["action"]),
                        payload=dict(data.get("payload", {})),
                        reason=str(data.get("reason", "")),
                    )
                )
            except Exception:
                skipped += 1

    return records, skipped


def parse_player_profile(player_name: str) -> str:
    if "-" in player_name:
        return player_name.split("-", 1)[1]
    return "unknown"


def parse_player_seat(player_name: str) -> Optional[int]:
    match = re.match(r"^[A-Za-z](\d+)-", player_name)
    if not match:
        return None
    try:
        return int(match.group(1)) - 1
    except ValueError:
        return None


def parse_contract(contract: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not contract:
        return None, None
    parts = contract.strip().split(maxsplit=1)
    if not parts:
        return None, None
    try:
        value = int(parts[0])
    except ValueError:
        value = None
    trump = parts[1] if len(parts) > 1 else None
    return value, trump


def build_hand_summaries(records: List[Record]) -> Dict[int, HandSummary]:
    summaries: Dict[int, HandSummary] = {}

    for rec in sorted(records, key=lambda r: (r.hand, r.phase, r.trick)):
        if rec.hand not in summaries:
            summaries[rec.hand] = HandSummary(
                hand=rec.hand,
                declarer=None,
                contract_value=None,
                contract_trump=None,
                team_points={0: None, 1: None},
                team_score={0: None, 1: None},
            )
        hand = summaries[rec.hand]

        if rec.phase == "bidding" and rec.action in {"bid", "take"} and rec.player != "SYSTEM":
            if rec.action == "bid":
                bid_value = rec.payload.get("value")
                bid_trump = rec.payload.get("trump")
                if isinstance(bid_value, int) and isinstance(bid_trump, str):
                    hand.contract_value = bid_value
                    hand.contract_trump = bid_trump
                    hand.declarer = rec.player
            elif rec.action == "take":
                take_trump = rec.payload.get("trump")
                if isinstance(take_trump, str):
                    hand.contract_trump = take_trump
                    hand.declarer = rec.player

        if rec.action == "hand_complete":
            value, trump = parse_contract(rec.payload.get("contract") if isinstance(rec.payload, dict) else None)
            if value is not None:
                hand.contract_value = value
            if trump is not None:
                hand.contract_trump = trump

            t0p = rec.payload.get("team0_points")
            t1p = rec.payload.get("team1_points")
            t0s = rec.payload.get("team0_score")
            t1s = rec.payload.get("team1_score")

            hand.team_points[0] = int(t0p) if isinstance(t0p, int) else None
            hand.team_points[1] = int(t1p) if isinstance(t1p, int) else None
            hand.team_score[0] = int(t0s) if isinstance(t0s, int) else None
            hand.team_score[1] = int(t1s) if isinstance(t1s, int) else None

    return summaries


def build_summary(records: List[Record], skipped: int, log_file: str) -> Dict[str, Any]:
    if not records:
        return {
            "log_file": log_file,
            "valid_records": 0,
            "skipped_malformed_lines": skipped,
            "hands_observed": {"count": 0, "start": None, "end": None},
            "players": [],
            "final_score": None,
            "action_counts": {},
            "phase_counts": {},
            "per_player": [],
            "contract_success_by_profile": {},
        }

    hands = sorted({r.hand for r in records})
    seen_players = {r.player for r in records if r.player != "SYSTEM"}
    players = sorted(
        seen_players,
        key=lambda name: (parse_player_seat(name) is None, parse_player_seat(name) if parse_player_seat(name) is not None else name),
    )

    phase_counts = Counter(r.phase for r in records)
    action_counts = Counter(r.action for r in records)

    per_player_actions: Dict[str, Counter] = defaultdict(Counter)
    per_player_bid_values: Dict[str, List[int]] = defaultdict(list)
    per_player_trumps: Dict[str, Counter] = defaultdict(Counter)
    per_player_reasons: Dict[str, Counter] = defaultdict(Counter)

    for rec in records:
        if rec.player == "SYSTEM":
            continue
        per_player_actions[rec.player][rec.action] += 1
        if rec.reason:
            per_player_reasons[rec.player][rec.reason] += 1
        if rec.action == "bid":
            value = rec.payload.get("value")
            trump = rec.payload.get("trump")
            if isinstance(value, int):
                per_player_bid_values[rec.player].append(value)
            if isinstance(trump, str):
                per_player_trumps[rec.player][trump] += 1
        if rec.action == "take":
            trump = rec.payload.get("trump")
            if isinstance(trump, str):
                per_player_trumps[rec.player][trump] += 1

    hand_summaries = build_hand_summaries(records)

    contract_attempts_by_profile: Counter = Counter()
    contract_makes_by_profile: Counter = Counter()

    final_team_score = {0: None, 1: None}
    for hand_no in sorted(hand_summaries):
        hand = hand_summaries[hand_no]
        if hand.team_score[0] is not None:
            final_team_score[0] = hand.team_score[0]
        if hand.team_score[1] is not None:
            final_team_score[1] = hand.team_score[1]

        if hand.declarer and hand.contract_value is not None and hand.team_points[0] is not None and hand.team_points[1] is not None:
            declarer_seat = parse_player_seat(hand.declarer)
            if declarer_seat is None:
                continue
            declarer_team = 0 if declarer_seat % 2 == 0 else 1
            profile = parse_player_profile(hand.declarer)
            contract_attempts_by_profile[profile] += 1

            contracted_points = hand.team_points[declarer_team]
            if contracted_points is not None and contracted_points >= hand.contract_value:
                contract_makes_by_profile[profile] += 1

    final_score: Optional[Dict[str, Any]] = None
    if final_team_score[0] is not None and final_team_score[1] is not None:
        team0 = f"{players[0]}/{players[2]}" if len(players) >= 4 else "Team 0"
        team1 = f"{players[1]}/{players[3]}" if len(players) >= 4 else "Team 1"
        if final_team_score[0] > final_team_score[1]:
            winner = team0
        elif final_team_score[1] > final_team_score[0]:
            winner = team1
        else:
            winner = "Tie"
        final_score = {
            "team0_name": team0,
            "team1_name": team1,
            "team0": final_team_score[0],
            "team1": final_team_score[1],
            "winner": winner,
        }

    per_player_summary: List[Dict[str, Any]] = []
    for player in players:
        profile = parse_player_profile(player)
        actions = per_player_actions[player]
        bids = per_player_bid_values[player]
        trumps = per_player_trumps[player]
        top_reason = per_player_reasons[player].most_common(1)
        top_reason_text = top_reason[0][0] if top_reason else None

        per_player_summary.append(
            {
                "player": player,
                "seat": parse_player_seat(player),
                "profile": profile,
                "actions": dict(actions),
                "avg_bid": mean(bids) if bids else None,
                "no_trump_calls": trumps.get("no-trump", 0),
                "top_reason": top_reason_text,
            }
        )

    contract_success: Dict[str, Dict[str, Any]] = {}
    for profile, attempts in sorted(contract_attempts_by_profile.items()):
        makes = contract_makes_by_profile.get(profile, 0)
        pct = (makes / attempts) * 100.0 if attempts else 0.0
        contract_success[profile] = {
            "makes": makes,
            "attempts": attempts,
            "success_rate": pct,
        }

    return {
        "log_file": log_file,
        "valid_records": len(records),
        "skipped_malformed_lines": skipped,
        "hands_observed": {
            "count": len(hands),
            "start": hands[0],
            "end": hands[-1],
        },
        "players": players,
        "final_score": final_score,
        "action_counts": dict(sorted(action_counts.items())),
        "phase_counts": dict(sorted(phase_counts.items())),
        "per_player": per_player_summary,
        "contract_success_by_profile": contract_success,
    }

def print_text_summary(summary: Dict[str, Any]) -> None:
    if summary["valid_records"] == 0:
        print("No valid records found.")
        if summary["skipped_malformed_lines"]:
            print(f"Skipped malformed lines: {summary['skipped_malformed_lines']}")
        return

    hands = summary["hands_observed"]
    print("\nBot Log Analysis")
    print(f"Log file: {summary['log_file']}")
    print(f"Valid records: {summary['valid_records']}")
    print(f"Hands observed: {hands['count']} ({hands['start']}..{hands['end']})")
    if summary["skipped_malformed_lines"]:
        print(f"Skipped malformed lines: {summary['skipped_malformed_lines']}")

    final_score = summary["final_score"]
    if final_score:
        print(
            f"Final score: {final_score['team0_name']}={final_score['team0']} | "
            f"{final_score['team1_name']}={final_score['team1']}"
        )
        print(f"Winner: {final_score['winner']}")

    print("\nAction counts:")
    for action, count in summary["action_counts"].items():
        print(f"  {action:12} {count}")

    print("\nPhase counts:")
    for phase, count in summary["phase_counts"].items():
        print(f"  {phase:12} {count}")

    print("\nPer-player summary:")
    for player_info in summary["per_player"]:
        actions = player_info["actions"]
        avg_bid = f"{player_info['avg_bid']:.2f}" if player_info["avg_bid"] is not None else "n/a"
        print(
            f"  {player_info['player']} ({player_info['profile']}) | "
            f"bids={actions.get('bid', 0)} avg_bid={avg_bid} "
            f"passes={actions.get('pass', 0)} takes={actions.get('take', 0)} "
            f"plays={actions.get('play', 0)} no_trump_calls={player_info['no_trump_calls']}"
        )
        print(f"    top_reason: {player_info['top_reason'] or 'n/a'}")

    if summary["contract_success_by_profile"]:
        print("\nContract success by profile:")
        for profile, details in summary["contract_success_by_profile"].items():
            makes = details["makes"]
            attempts = details["attempts"]
            pct = details["success_rate"]
            print(f"  {profile:12} {makes}/{attempts} ({pct:.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze bot_sim JSONL logs and print aggregate summaries.")
    parser.add_argument(
        "--log-file",
        type=str,
        default="bot_decisions.jsonl",
        help="Path to decision log JSONL file (default: bot_decisions.jsonl)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON summary",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Write JSON output to file path (use with --json), e.g. --out summary.json",
    )
    args = parser.parse_args()

    records, skipped = load_records(args.log_file)
    summary = build_summary(records, skipped, args.log_file)
    if args.json:
        json_text = json.dumps(summary, indent=2)
        if args.out:
            output_path = Path(args.out)
            output_path.write_text(json_text + "\n", encoding="utf-8")
        else:
            print(json_text)
    else:
        print_text_summary(summary)


if __name__ == "__main__":
    main()
