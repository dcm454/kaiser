from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kaiser import BID_MAX, BID_MIN, RANK_ORDER, SUITS, TRUMP_ORDER, Bid, Card, KaiserGame


@dataclass
class BotProfile:
    name: str
    bid_aggression: float = 1.0
    bid_risk_buffer: int = 0
    no_trump_bias: float = 1.0
    no_trump_bid_margin: float = 3.0
    no_trump_take_margin: float = 5.0
    dealer_take_threshold: float = 52.0
    lead_high_bias: float = 0.5
    trump_spend_bias: float = 0.5
    random_play_jitter: float = 0.1


PRESET_PROFILES: Dict[str, BotProfile] = {
    "cautious": BotProfile(
        name="cautious",
        bid_aggression=0.72,
        bid_risk_buffer=2,
        no_trump_bias=0.85,
        dealer_take_threshold=80.0,
        lead_high_bias=0.2,
        trump_spend_bias=0.2,
        random_play_jitter=0.05,
    ),
    "balanced": BotProfile(
        name="balanced",
        bid_aggression=0.74,
        bid_risk_buffer=3,
        no_trump_bias=0.80,
        dealer_take_threshold=78.0,
        lead_high_bias=0.5,
        trump_spend_bias=0.5,
        random_play_jitter=0.1,
    ),
    "aggressive": BotProfile(
        name="aggressive",
        bid_aggression=0.77,
        bid_risk_buffer=3,
        no_trump_bias=0.78,
        dealer_take_threshold=74.0,
        lead_high_bias=0.8,
        trump_spend_bias=0.8,
        random_play_jitter=0.2,
    ),
    "chaotic": BotProfile(
        name="chaotic",
        bid_aggression=0.8,
        bid_risk_buffer=2,
        no_trump_bias=0.78,
        dealer_take_threshold=76.0,
        lead_high_bias=0.5,
        trump_spend_bias=0.6,
        random_play_jitter=0.6,
    ),
}


@dataclass
class DecisionRecord:
    hand: int
    trick: int
    phase: str
    player: str
    action: str
    payload: Dict[str, object]
    reason: str


class BotPolicy:
    def __init__(self, profile: BotProfile):
        self.profile = profile

    @staticmethod
    def _rank_value(card: Card) -> int:
        return RANK_ORDER.index(card.rank)

    @staticmethod
    def _clamp_bid(value: int) -> int:
        return max(BID_MIN, min(BID_MAX, value))

    @staticmethod
    def _is_card(card: Card, rank: str, suit: str) -> bool:
        return card.rank == rank and card.suit == suit

    @staticmethod
    def _partner_index(player_index: int) -> int:
        return (player_index + 2) % 4

    @staticmethod
    def _hand_cards_short(hand: List[Card]) -> List[str]:
        return [card.short() for card in hand]

    def _all_other_hearts_played(self, game: KaiserGame) -> bool:
        # "Other hearts" means any heart except the special 5h.
        for player in game.players:
            for card in player.hand:
                if card.suit == "hearts" and card.rank != "5":
                    return False
        return True

    def _no_trump_strength(self, hand: List[Card]) -> float:
        rank_scores = {
            "A": 6.0,
            "K": 3.5,
            "Q": 2.2,
            "J": 1.3,
            "10": 0.8,
            "9": 0.3,
            "8": 0.1,
        }
        cards_by_suit: Dict[str, List[Card]] = {suit: [] for suit in SUITS}
        for card in hand:
            cards_by_suit[card.suit].append(card)

        score = 0.0
        stopped_suits = 0
        controlled_suits = 0

        for suit in SUITS:
            suit_cards = sorted(cards_by_suit[suit], key=self._rank_value, reverse=True)
            ranks = {card.rank for card in suit_cards}
            honor_count = sum(1 for card in suit_cards if card.rank in {"A", "K", "Q", "J", "10"})

            for card in suit_cards:
                score += rank_scores.get(card.rank, 0.0)

            is_stopped = False
            has_control = False
            if "A" in ranks:
                score += 2.5
                is_stopped = True
                has_control = True
            elif "K" in ranks and len(suit_cards) >= 2:
                score += 1.5
                is_stopped = True
                has_control = True
            elif "Q" in ranks and "J" in ranks and len(suit_cards) >= 3:
                score += 1.0
                is_stopped = True
            elif "J" in ranks and "10" in ranks and len(suit_cards) >= 4:
                score += 0.5
                is_stopped = True

            if "A" in ranks and "K" in ranks:
                score += 4.0
                has_control = True
            elif "A" in ranks and "Q" in ranks:
                score += 2.5
            elif "K" in ranks and "Q" in ranks and "J" in ranks:
                score += 3.0
                has_control = True
            elif "Q" in ranks and "J" in ranks and "10" in ranks:
                score += 2.0

            if len(suit_cards) >= 3 and honor_count >= 2:
                score += 0.75 * (len(suit_cards) - 2)

            if len(suit_cards) == 0:
                score -= 0.75
            elif len(suit_cards) == 1 and "A" not in ranks:
                score -= 1.25
            elif len(suit_cards) == 2 and honor_count == 0:
                score -= 0.5

            if is_stopped:
                stopped_suits += 1
            if has_control:
                controlled_suits += 1

        hearts_ranks = {card.rank for card in cards_by_suit["hearts"]}
        if "5" in hearts_ranks:
            score += 4.0
            if "A" in hearts_ranks or "K" in hearts_ranks:
                score += 2.0
            elif "Q" in hearts_ranks or "J" in hearts_ranks or "10" in hearts_ranks:
                score += 1.0

        if "3" in {card.rank for card in cards_by_suit["spades"]}:
            score -= 3.0

        score += max(0, stopped_suits - 1) * 1.5
        if controlled_suits >= 2:
            score += 2.0 + (controlled_suits - 2) * 1.0

        # Keep no-trump strengths on roughly the same scale as suit-trump strengths.
        return score * 3.0 * self.profile.no_trump_bias

    def _preferred_bid_trump(self, strengths: Dict[str, float], take_context: bool = False) -> Tuple[str, float, str, float]:
        suit_strengths = {trump: score for trump, score in strengths.items() if trump != "no-trump"}
        best_suit_trump = max(suit_strengths, key=lambda trump: suit_strengths[trump])
        best_suit_strength = suit_strengths[best_suit_trump]
        no_trump_strength = strengths["no-trump"]
        margin = self.profile.no_trump_take_margin if take_context else self.profile.no_trump_bid_margin
        if no_trump_strength >= best_suit_strength + margin:
            return "no-trump", no_trump_strength, best_suit_trump, best_suit_strength
        return best_suit_trump, best_suit_strength, best_suit_trump, best_suit_strength

    def _hand_strength_by_trump(self, hand: List[Card]) -> Dict[str, float]:
        strength: Dict[str, float] = {trump: 0.0 for trump in TRUMP_ORDER}

        for card in hand:
            base = self._rank_value(card) + 1
            if card.suit_special:
                if card.rank == "5" and card.suit == "hearts":
                    base += 4
                elif card.rank == "3" and card.suit == "spades":
                    base -= 3

            for trump in TRUMP_ORDER:
                if trump == "no-trump":
                    continue
                card_score = float(base)
                if trump != "no-trump" and card.suit == trump:
                    card_score += 5.0
                strength[trump] += card_score

        for trump in TRUMP_ORDER:
            if trump == "no-trump":
                continue
            suit_len = sum(1 for c in hand if c.suit == trump)
            strength[trump] += suit_len * 1.75

        strength["no-trump"] = self._no_trump_strength(hand)
        return strength

    def choose_bid_action(self, game: KaiserGame, player_index: int) -> Tuple[str, Dict[str, object], str]:
        hand = game.players[player_index].hand
        strengths = self._hand_strength_by_trump(hand)
        best_trump, best_strength, best_suit_trump, best_suit_strength = self._preferred_bid_trump(strengths)

        projected_bid = int((best_strength / 8.0) * self.profile.bid_aggression)
        projected_bid = self._clamp_bid(projected_bid)

        highest = game.highest_bid
        highest_value = highest.value if highest else 0

        reason = (
            f"best_trump={best_trump}, strength={best_strength:.1f}, projected_bid={projected_bid}, "
            f"best_suit={best_suit_trump}, best_suit_strength={best_suit_strength:.1f}, "
            f"no_trump_strength={strengths['no-trump']:.1f}"
        )
        debug = {
            "hand_cards": self._hand_cards_short(hand),
            "bid_strength_best": round(best_strength, 2),
            "bid_strength_best_trump": best_trump,
            "bid_strength_best_suit_trump": best_suit_trump,
            "bid_strength_best_suit": round(best_suit_strength, 2),
            "bid_strength_no_trump": round(strengths["no-trump"], 2),
            "bid_strength_by_trump": {trump: round(score, 2) for trump, score in strengths.items()},
            "projected_bid": projected_bid,
            "current_highest_bid": highest_value,
        }

        if highest is None:
            payload: Dict[str, object] = {"value": projected_bid, "__debug": debug}
            if best_trump == "no-trump":
                payload["trump"] = "no-trump"
            return "bid", payload, reason

        can_bid = projected_bid >= highest_value if best_trump == "no-trump" else projected_bid >= highest_value + 1 + self.profile.bid_risk_buffer
        if can_bid:
            payload = {"value": projected_bid, "__debug": debug}
            if best_trump == "no-trump":
                payload["trump"] = "no-trump"
            return "bid", payload, reason

        is_dealer_turn = player_index == game.dealer_index == game.bid_turn_index
        take_trump, take_strength, _, _ = self._preferred_bid_trump(strengths, take_context=True)
        effective_take_trump = "no-trump" if highest is not None and highest.trump == "no-trump" else take_trump
        projected_take_bid = int((take_strength / 8.0) * self.profile.bid_aggression)
        projected_take_bid = self._clamp_bid(projected_take_bid)
        projected_can_match_current_bid = projected_take_bid >= highest_value
        if is_dealer_turn and projected_can_match_current_bid and take_strength >= self.profile.dealer_take_threshold:
            # Taking partner's bid should be rare and only done with very high confidence.
            if highest is not None and highest.player_index != player_index and (highest.player_index % 2) == (player_index % 2):
                high_confidence_threshold = self.profile.dealer_take_threshold + 12.0
                can_confidently_support_current_bid = projected_take_bid >= highest_value
                if take_strength >= high_confidence_threshold and can_confidently_support_current_bid:
                    payload = {"__debug": debug}
                    if effective_take_trump == "no-trump" and (highest is None or highest.trump != "no-trump"):
                        payload["trump"] = "no-trump"
                    return "take", payload, f"{reason}, take_trump={effective_take_trump}, partner_take_high_confidence"
                return "pass", {"__debug": debug}, f"{reason}, avoid_partner_take"

            payload = {"__debug": debug}
            if effective_take_trump == "no-trump" and (highest is None or highest.trump != "no-trump"):
                payload["trump"] = "no-trump"
            return "take", payload, f"{reason}, take_trump={effective_take_trump}"

        return "pass", {"__debug": debug}, reason

    def choose_trump_action(self, game: KaiserGame, player_index: int) -> Tuple[str, Dict[str, object], str]:
        hand = game.players[player_index].hand
        strengths = self._hand_strength_by_trump(hand)
        suit_strengths = {trump: score for trump, score in strengths.items() if trump != "no-trump"}
        best_trump = max(suit_strengths, key=lambda t: suit_strengths[t])
        best_strength = suit_strengths[best_trump]
        reason = f"select_best_trump={best_trump}, strength={best_strength:.1f}"
        debug = {
            "hand_cards": self._hand_cards_short(hand),
            "bid_strength_best": round(best_strength, 2),
            "bid_strength_best_trump": best_trump,
            "bid_strength_by_trump": {trump: round(score, 2) for trump, score in strengths.items()},
        }
        return "choose_trump", {"trump": best_trump, "__debug": debug}, reason

    def _current_partial_winner(self, game: KaiserGame) -> Optional[Tuple[int, Card]]:
        if not game.current_trick:
            return None
        lead_suit = game.current_trick[0][1].suit
        trump = game.contract.trump if game.contract else "no-trump"

        candidates = game.current_trick
        if trump != "no-trump":
            trump_cards = [entry for entry in candidates if entry[1].suit == trump]
            if trump_cards:
                candidates = trump_cards
            else:
                candidates = [entry for entry in candidates if entry[1].suit == lead_suit]
        else:
            candidates = [entry for entry in candidates if entry[1].suit == lead_suit]

        return max(candidates, key=lambda item: self._rank_value(item[1]))

    def _would_currently_win(self, game: KaiserGame, card: Card) -> bool:
        if not game.current_trick:
            return True
        if game.contract is None:
            return False

        lead_suit = game.current_trick[0][1].suit
        trump = game.contract.trump
        current_winner = self._current_partial_winner(game)
        if current_winner is None:
            return True
        winner_card = current_winner[1]

        if trump != "no-trump":
            winner_is_trump = winner_card.suit == trump
            card_is_trump = card.suit == trump
            if winner_is_trump and not card_is_trump:
                return False
            if card_is_trump and not winner_is_trump:
                return True
            if card_is_trump and winner_is_trump:
                return self._rank_value(card) > self._rank_value(winner_card)

        if winner_card.suit != lead_suit:
            return card.suit == lead_suit
        if card.suit != lead_suit:
            return False
        return self._rank_value(card) > self._rank_value(winner_card)

    def _team_wins_trick_after_play(self, game: KaiserGame, player_index: int, card: Card) -> bool:
        """Conservative certainty check used for protecting 5H.

        We only treat the trick as secure if this play closes the trick and the
        resulting winner is on the current player's team.
        """
        plays_before = len(game.current_trick)
        plays_after = plays_before + 1
        trick_size = len(game.players)

        # If others still act after this play, outcome is not certain.
        if plays_after < trick_size:
            return False

        # Last card of the trick: winner is now deterministic from visible cards.
        if self._would_currently_win(game, card):
            winner_index = player_index
        else:
            current_winner = self._current_partial_winner(game)
            if current_winner is None:
                return False
            winner_index = current_winner[0]

        return (winner_index % 2) == (player_index % 2)

    def choose_play_card(self, game: KaiserGame, player_index: int) -> Tuple[str, Dict[str, object], str]:
        player = game.players[player_index]
        hand = list(player.hand)
        if not hand:
            raise ValueError("Bot has no cards to play")

        lead_suit = game.current_trick[0][1].suit if game.current_trick else None
        if lead_suit and any(c.suit == lead_suit for c in hand):
            legal = [c for c in hand if c.suit == lead_suit]
        else:
            legal = hand

        partner_index = self._partner_index(player_index)
        lead_entry = game.current_trick[0] if game.current_trick else None
        lead_index = lead_entry[0] if lead_entry else None
        lead_card = lead_entry[1] if lead_entry else None
        five_hearts = next((c for c in legal if self._is_card(c, "5", "hearts")), None)
        three_spades = next((c for c in legal if self._is_card(c, "3", "spades")), None)

        # Special-card directives for 5h and 3s override baseline heuristics.
        if five_hearts is not None and lead_card is not None:
            opponent_led_hearts = (lead_card.suit == "hearts") and (lead_index % 2 != player_index % 2)
            if opponent_led_hearts and len(legal) > 1:
                legal_wo_5h = [c for c in legal if not self._is_card(c, "5", "hearts")]
                if legal_wo_5h:
                    legal = legal_wo_5h
                    five_hearts = None

        if five_hearts is not None and not game.current_trick and len(legal) > 1 and not self._all_other_hearts_played(game):
            legal_wo_5h = [c for c in legal if not self._is_card(c, "5", "hearts")]
            if legal_wo_5h:
                legal = legal_wo_5h
                five_hearts = None

        # Protect 5H unless team is certain to take this trick after this play.
        if five_hearts is not None and len(legal) > 1:
            team_secures_trick = self._team_wins_trick_after_play(game, player_index, five_hearts)
            if not team_secures_trick:
                legal_wo_5h = [c for c in legal if not self._is_card(c, "5", "hearts")]
                if legal_wo_5h:
                    legal = legal_wo_5h
                    five_hearts = None

        current_winner = self._current_partial_winner(game)
        partner_winning = current_winner is not None and current_winner[0] == partner_index
        three_spades_in_trick = any(self._is_card(card, "3", "spades") for _, card in game.current_trick)

        if three_spades is not None and len(legal) > 1:
            if partner_winning:
                legal_wo_3s = [c for c in legal if not self._is_card(c, "3", "spades")]
                if legal_wo_3s:
                    legal = legal_wo_3s
                    three_spades = None
            elif game.current_trick and not self._would_currently_win(game, three_spades):
                return "play", {"card": self._card_to_token(three_spades)}, "rule_dump_3s_to_opponents"
            elif not game.current_trick:
                legal_wo_3s = [c for c in legal if not self._is_card(c, "3", "spades")]
                if legal_wo_3s:
                    legal = legal_wo_3s
                    three_spades = None

        contract_trump = game.contract.trump if game.contract else "no-trump"

        # If 3S is already in this trick, prioritize avoiding a trick win.
        if three_spades_in_trick and len(legal) > 1:
            losing_cards = [c for c in legal if not self._would_currently_win(game, c)]
            if losing_cards:
                target = min(losing_cards, key=self._rank_value)
                return "play", {"card": self._card_to_token(target)}, "avoid_winning_3s_trick"

        winning_cards = [c for c in legal if self._would_currently_win(game, c)]
        lowest_legal = min(legal, key=self._rank_value)
        highest_legal = max(legal, key=self._rank_value)

        # If 5H is in the current trick, always play the highest winning card or,
        # if unable to win by following suit, the highest available trump.
        five_hearts_in_trick = any(self._is_card(card, "5", "hearts") for _, card in game.current_trick)
        if five_hearts_in_trick:
            if winning_cards:
                target = max(winning_cards, key=self._rank_value)
                token = self._card_to_token(target)
                debug = {
                    "hand_cards_before_play": self._hand_cards_short(player.hand),
                    "play_reason": "5h_in_trick_highest_winning",
                }
                return "play", {"card": token, "__debug": debug}, "5h_in_trick_highest_winning"
            if contract_trump != "no-trump":
                trump_cards_legal = [c for c in legal if c.suit == contract_trump]
                if trump_cards_legal:
                    target = max(trump_cards_legal, key=self._rank_value)
                    token = self._card_to_token(target)
                    debug = {
                        "hand_cards_before_play": self._hand_cards_short(player.hand),
                        "play_reason": "5h_in_trick_highest_trump",
                    }
                    return "play", {"card": token, "__debug": debug}, "5h_in_trick_highest_trump"

        target: Card
        reason: str

        if winning_cards and random.random() < self.profile.lead_high_bias:
            target = min(winning_cards, key=self._rank_value)
            reason = "play_lowest_winning_card"
        else:
            if contract_trump != "no-trump" and any(c.suit == contract_trump for c in legal):
                trump_cards = [c for c in legal if c.suit == contract_trump]
                if random.random() < self.profile.trump_spend_bias:
                    target = max(trump_cards, key=self._rank_value)
                    reason = "spend_high_trump"
                else:
                    target = min(trump_cards, key=self._rank_value)
                    reason = "spend_low_trump"
            else:
                if random.random() < self.profile.lead_high_bias:
                    target = highest_legal
                    reason = "play_high_legal"
                else:
                    target = lowest_legal
                    reason = "play_low_legal"

        if random.random() < self.profile.random_play_jitter and len(legal) > 1:
            target = random.choice(legal)
            reason += " + jitter"

        token = self._card_to_token(target)
        debug = {
            "hand_cards_before_play": self._hand_cards_short(player.hand),
            "play_reason": reason,
        }
        return "play", {"card": token, "__debug": debug}, reason

    @staticmethod
    def _card_to_token(card: Card) -> str:
        suit_map = {
            "clubs": "c",
            "diamonds": "d",
            "hearts": "h",
            "spades": "s",
        }
        return f"{card.rank}{suit_map[card.suit]}"


class BotSimulator:
    def __init__(self, profiles: List[BotProfile], seed: Optional[int] = None):
        if len(profiles) != 4:
            raise ValueError("Exactly 4 bot profiles are required")
        self.profiles = profiles
        self.policies = [BotPolicy(profile=p) for p in profiles]
        self.seed = seed
        self.decisions: List[DecisionRecord] = []

    @staticmethod
    def _hand_snapshot(game: KaiserGame, player_index: int) -> List[str]:
        return [card.short() for card in game.players[player_index].hand]

    @staticmethod
    def _bidding_debug_payload(policy: BotPolicy, game: KaiserGame, player_index: int) -> Dict[str, object]:
        hand = game.players[player_index].hand
        strengths = policy._hand_strength_by_trump(hand)
        best_trump, best_strength, best_suit_trump, best_suit_strength = policy._preferred_bid_trump(strengths)
        projected_bid = int((best_strength / 8.0) * policy.profile.bid_aggression)
        projected_bid = policy._clamp_bid(projected_bid)
        highest_value = game.highest_bid.value if game.highest_bid is not None else 0

        return {
            "hand_cards": [card.short() for card in hand],
            "bid_strength_best": round(best_strength, 2),
            "bid_strength_best_trump": best_trump,
            "bid_strength_best_suit_trump": best_suit_trump,
            "bid_strength_best_suit": round(best_suit_strength, 2),
            "bid_strength_no_trump": round(strengths["no-trump"], 2),
            "bid_strength_by_trump": {trump: round(score, 2) for trump, score in strengths.items()},
            "projected_bid": projected_bid,
            "current_highest_bid": highest_value,
        }

    def run(self, hands: int) -> Tuple[KaiserGame, int]:
        if self.seed is not None:
            random.seed(self.seed)

        game = KaiserGame.new_default()
        for idx, profile in enumerate(self.profiles):
            game.players[idx].name = f"{profile.name[:1].upper()}{idx+1}-{profile.name}"

        hands_played = 0
        for hand_no in range(1, hands + 1):
            game.deal_new_hand()
            self._log(hand_no, game.trick_number, game.phase, "SYSTEM", "deal", {}, "new hand dealt")

            while game.phase == "bidding":
                idx = game.bid_turn_index
                action, payload, reason = self.policies[idx].choose_bid_action(game, idx)
                log_payload = {**payload, **self._bidding_debug_payload(self.policies[idx], game, idx)}
                self._apply_bidding_action(game, idx, action, payload)
                self._log(hand_no, game.trick_number, "bidding", game.players[idx].name, action, log_payload, reason)

            while game.phase == "choosing_trump":
                idx = game.trump_select_index
                action, payload, reason = self.policies[idx].choose_trump_action(game, idx)
                self._apply_trump_selection_action(game, idx, action, payload)
                self._log(hand_no, game.trick_number, "choosing_trump", game.players[idx].name, action, payload, reason)

            while game.phase == "playing":
                idx = game.play_turn_index
                action, payload, reason = self.policies[idx].choose_play_card(game, idx)
                log_payload = {
                    **payload,
                    "play_reason": reason,
                    "hand_cards_before_play": self._hand_snapshot(game, idx),
                }
                self._apply_play_action(game, idx, action, payload)
                self._log(hand_no, game.trick_number, "playing", game.players[idx].name, action, log_payload, reason)

            self._log(
                hand_no,
                game.trick_number,
                game.phase,
                "SYSTEM",
                "hand_complete",
                {
                    "team0_score": game.game_score[0],
                    "team1_score": game.game_score[1],
                    "team0_points": game.team_points[0],
                    "team1_points": game.team_points[1],
                    "contract": f"{game.contract.value} {game.contract.trump}" if game.contract else None,
                    "winning_target": 64 if game.no_trump_bid_seen else 52,
                    "winner_team_index": game.winning_team_index,
                },
                "hand finished",
            )

            hands_played = hand_no
            if game.winning_team_index is not None:
                break

            game.rotate_dealer()

        return game, hands_played

    def _apply_bidding_action(self, game: KaiserGame, player_index: int, action: str, payload: Dict[str, object]) -> None:
        if game.bid_turn_index != player_index:
            raise ValueError("Out-of-turn bidding action")
        if action == "bid":
            game.place_bid(int(payload["value"]), trump=str(payload["trump"]) if payload.get("trump") else None)
            return
        if action == "take":
            game.dealer_take_bid(trump=str(payload["trump"]) if payload.get("trump") else None)
            return
        if action == "pass":
            game.pass_bid()
            return
        raise ValueError(f"Unsupported bidding action: {action}")

    def _apply_trump_selection_action(self, game: KaiserGame, player_index: int, action: str, payload: Dict[str, object]) -> None:
        if game.trump_select_index != player_index:
            raise ValueError("Out-of-turn trump selection action")
        if action != "choose_trump":
            raise ValueError(f"Unsupported trump selection action: {action}")
        game.choose_contract_trump(str(payload["trump"]))

    def _apply_play_action(self, game: KaiserGame, player_index: int, action: str, payload: Dict[str, object]) -> None:
        if game.play_turn_index != player_index:
            raise ValueError("Out-of-turn play action")
        if action != "play":
            raise ValueError(f"Unsupported play action: {action}")
        game.play_card(str(payload["card"]))

    def _log(
        self,
        hand: int,
        trick: int,
        phase: str,
        player: str,
        action: str,
        payload: Dict[str, object],
        reason: str,
    ) -> None:
        self.decisions.append(
            DecisionRecord(
                hand=hand,
                trick=trick,
                phase=phase,
                player=player,
                action=action,
                payload=payload,
                reason=reason,
            )
        )


def parse_profiles(spec: str) -> List[BotProfile]:
    names = [part.strip().lower() for part in spec.split(",") if part.strip()]
    if len(names) != 4:
        raise ValueError("--profiles must contain 4 preset names, e.g. balanced,balanced,aggressive,cautious")

    profiles: List[BotProfile] = []
    for name in names:
        if name not in PRESET_PROFILES:
            raise ValueError(f"Unknown profile '{name}'. Available: {', '.join(PRESET_PROFILES)}")
        preset = PRESET_PROFILES[name]
        profiles.append(BotProfile(**asdict(preset)))
    return profiles


def apply_profile_overrides(profiles: List[BotProfile], overrides_path: Optional[str]) -> None:
    if not overrides_path:
        return
    data = json.loads(Path(overrides_path).read_text())
    if not isinstance(data, list) or len(data) != 4:
        raise ValueError("Override file must be a JSON list with 4 objects")

    for idx, override in enumerate(data):
        if not isinstance(override, dict):
            continue
        for key, value in override.items():
            if hasattr(profiles[idx], key):
                setattr(profiles[idx], key, value)


def write_decision_log(path: str, records: List[DecisionRecord]) -> None:
    output = Path(path)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record)) + "\n")


def print_summary(
    game: KaiserGame,
    profiles: List[BotProfile],
    hands_requested: int,
    hands_played: int,
    log_file: str,
    overrides_path: Optional[str],
) -> None:
    team0 = f"{game.players[0].name}/{game.players[2].name}"
    team1 = f"{game.players[1].name}/{game.players[3].name}"
    print("\nBot Simulation Complete")
    print(f"Hands played: {hands_played}/{hands_requested}")
    print(f"Final score: {team0}={game.game_score[0]} | {team1}={game.game_score[1]}")
    if game.winning_team_index == 0:
        winner = team0
    elif game.winning_team_index == 1:
        winner = team1
    else:
        winner = "No game winner reached"
    print(f"Winner: {winner}")
    print(f"Decision log: {log_file}")
    if overrides_path:
        print(f"Profile overrides: {overrides_path}")
    else:
        print("Profile overrides: none")
    print("Profiles:")
    for idx, profile in enumerate(profiles):
        print(f"  P{idx+1}: {profile.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run automated 4-bot Kaiser simulations with decision logging.",
        epilog=(
            "Override mapping is positional and follows --profiles order: "
            "object 1->P1, object 2->P2, object 3->P3, object 4->P4."
        ),
    )
    parser.add_argument("--hands", type=int, default=20, help="Number of hands to simulate (default: 20)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    parser.add_argument(
        "--profiles",
        type=str,
        default="balanced,balanced,balanced,balanced",
        help="Comma-separated 4 preset names (cautious|balanced|aggressive|chaotic)",
    )
    parser.add_argument(
        "--profile-overrides",
        type=str,
        default=None,
        help="Path to JSON list of 4 profile override objects (positional by --profiles order)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="bot_decisions.jsonl",
        help="Decision log output file (JSONL)",
    )
    args = parser.parse_args()

    profiles = parse_profiles(args.profiles)
    apply_profile_overrides(profiles, args.profile_overrides)

    simulator = BotSimulator(profiles=profiles, seed=args.seed)
    game, hands_played = simulator.run(hands=args.hands)
    write_decision_log(args.log_file, simulator.decisions)
    print_summary(game, profiles, args.hands, hands_played, args.log_file, args.profile_overrides)


if __name__ == "__main__":
    main()
