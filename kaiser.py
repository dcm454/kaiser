from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import random


SUITS = ("clubs", "diamonds", "hearts", "spades")
RANK_ORDER = ("3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
TRUMP_ORDER = ("clubs", "diamonds", "hearts", "spades", "no-trump")
BID_MIN = 7
BID_MAX = 12


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str
    suit_special: bool = False

    def __post_init__(self) -> None:
        if self.suit not in SUITS:
            raise ValueError(f"Invalid suit: {self.suit}")
        if self.rank not in RANK_ORDER:
            raise ValueError(f"Invalid rank: {self.rank}")
        should_be_special = (self.rank, self.suit) in (("5", "hearts"), ("3", "spades"))
        if self.suit_special != should_be_special:
            object.__setattr__(self, "suit_special", should_be_special)

    def short(self) -> str:
        markers = {
            "clubs": "♣",
            "diamonds": "♦",
            "hearts": "♥",
            "spades": "♠",
        }
        suffix = "*" if self.suit_special else ""
        return f"{self.rank}{markers[self.suit]}{suffix}"


@dataclass
class Deck:
    cards: List[Card] = field(default_factory=list)

    @classmethod
    def build_kaiser_32(cls) -> "Deck":
        cards: List[Card] = []

        for rank in ("7", "8", "9", "10", "J", "Q", "K", "A"):
            cards.append(Card(rank=rank, suit="clubs"))
            cards.append(Card(rank=rank, suit="diamonds"))

        for rank in ("8", "9", "10", "J", "Q", "K", "A"):
            cards.append(Card(rank=rank, suit="hearts"))
            cards.append(Card(rank=rank, suit="spades"))

        cards.append(Card(rank="5", suit="hearts", suit_special=True))
        cards.append(Card(rank="3", suit="spades", suit_special=True))

        return cls(cards=cards)

    def shuffle(self) -> None:
        random.shuffle(self.cards)

    def draw(self) -> Card:
        if not self.cards:
            raise ValueError("Deck is empty")
        return self.cards.pop()

    def size(self) -> int:
        return len(self.cards)


@dataclass
class Player:
    name: str
    hand: List[Card] = field(default_factory=list)

    def receive(self, card: Card) -> None:
        self.hand.append(card)

    def sort_hand(self) -> None:
        suit_pos = {suit: index for index, suit in enumerate(SUITS)}
        rank_pos = {rank: index for index, rank in enumerate(RANK_ORDER)}
        self.hand.sort(key=lambda card: (suit_pos[card.suit], rank_pos[card.rank]))

    def show_hand(self) -> str:
        return " ".join(card.short() for card in self.hand)

    def has_suit(self, suit: str) -> bool:
        return any(card.suit == suit for card in self.hand)

    def remove_card(self, card: Card) -> None:
        self.hand.remove(card)

    def find_card_by_token(self, token: str) -> Optional[Card]:
        normalized = token.strip().lower().replace(" ", "")
        if len(normalized) < 2:
            return None
        suit_code = normalized[-1]
        rank_code = normalized[:-1].upper()

        suit_map = {
            "c": "clubs",
            "d": "diamonds",
            "h": "hearts",
            "s": "spades",
        }
        rank_map = {
            "A": "A",
            "K": "K",
            "Q": "Q",
            "J": "J",
            "10": "10",
            "9": "9",
            "8": "8",
            "7": "7",
            "6": "6",
            "5": "5",
            "4": "4",
            "3": "3",
        }

        suit = suit_map.get(suit_code)
        rank = rank_map.get(rank_code)
        if suit is None or rank is None:
            return None

        for card in self.hand:
            if card.rank == rank and card.suit == suit:
                return card
        return None


@dataclass(frozen=True)
class Bid:
    value: int
    trump: str
    player_index: int


@dataclass
class KaiserGame:
    players: List[Player] = field(default_factory=list)
    dealer_index: int = 0
    last_bid: Optional[str] = None
    current_deck: Optional[Deck] = None
    phase: str = "idle"
    bid_turn_index: int = 0
    trump_select_index: int = 0
    highest_bid: Optional[Bid] = None
    bid_history: List[str] = field(default_factory=list)
    bids_made: int = 0
    play_turn_index: int = 0
    contract: Optional[Bid] = None
    current_trick: List[Tuple[int, Card]] = field(default_factory=list)
    trick_leader_index: int = 0
    trick_number: int = 1
    team_tricks: List[int] = field(default_factory=lambda: [0, 0])
    team_points: List[int] = field(default_factory=lambda: [0, 0])
    game_score: List[int] = field(default_factory=lambda: [0, 0])
    no_trump_bid_seen: bool = False
    winning_team_index: Optional[int] = None

    @classmethod
    def new_default(cls) -> "KaiserGame":
        players = [Player(name=f"P{i}") for i in range(1, 5)]
        return cls(players=players)

    def rotate_dealer(self) -> Player:
        self.dealer_index = (self.dealer_index + 1) % len(self.players)
        return self.players[self.dealer_index]

    def dealer(self) -> Player:
        return self.players[self.dealer_index]

    def deal_new_hand(self) -> None:
        for player in self.players:
            player.hand.clear()

        deck = Deck.build_kaiser_32()
        deck.shuffle()

        for _ in range(8):
            for player in self.players:
                player.receive(deck.draw())

        for player in self.players:
            player.sort_hand()

        self.current_deck = deck
        self._start_bidding_phase()

    def _start_bidding_phase(self) -> None:
        self.phase = "bidding"
        self.bid_turn_index = (self.dealer_index + 1) % len(self.players)
        self.trump_select_index = 0
        self.highest_bid = None
        self.contract = None
        self.bid_history.clear()
        self.bids_made = 0
        self.current_trick.clear()
        self.trick_number = 1
        self.trick_leader_index = 0
        self.play_turn_index = 0
        self.team_tricks = [0, 0]
        self.team_points = [0, 0]
        self.last_bid = None

    def current_bidder(self) -> Player:
        return self.players[self.bid_turn_index]

    def place_bid(self, value: int, trump: Optional[str] = None) -> str:
        if self.phase != "bidding":
            raise ValueError("Bidding is not active")
        if value < BID_MIN or value > BID_MAX:
            raise ValueError(f"Bid value must be between {BID_MIN} and {BID_MAX}")

        if self.highest_bid is not None and value <= self.highest_bid.value:
            raise ValueError("Bid must be higher than current highest bid")

        stored_trump = "no-trump" if trump == "no-trump" else "hidden"
        bid = Bid(value=value, trump=stored_trump, player_index=self.bid_turn_index)
        self.highest_bid = bid
        self.bids_made += 1

        bidder = self.players[self.bid_turn_index].name
        # During bidding, only disclose bid value publicly; trump stays hidden until contract is awarded.
        item = f"{bidder}: {value}"
        self.bid_history.append(item)
        self.last_bid = f"{value}"

        if self.bid_turn_index == self.dealer_index:
            self._finalize_bidding()
            return f"{item} (dealer closed bidding)"

        self._advance_bidding_turn()
        return item

    def pass_bid(self) -> str:
        if self.phase != "bidding":
            raise ValueError("Bidding is not active")

        if self.bid_turn_index == self.dealer_index and self.highest_bid is None:
            raise ValueError("Dealer must bid when no one has bid")

        bidder = self.players[self.bid_turn_index].name
        self.bid_history.append(f"{bidder}: pass")
        self.bids_made += 1

        if self.bid_turn_index == self.dealer_index:
            self._finalize_bidding()
            return f"{bidder}: pass (dealer closed bidding)"

        self._advance_bidding_turn()
        return f"{bidder}: pass"

    def dealer_take_bid(self) -> str:
        if self.phase != "bidding":
            raise ValueError("Bidding is not active")
        if self.bid_turn_index != self.dealer_index:
            raise ValueError("Only the dealer can take the highest bid")
        if self.highest_bid is None:
            raise ValueError("No highest bid to take")

        taken = Bid(
            value=self.highest_bid.value,
            trump="hidden",
            player_index=self.dealer_index,
        )
        self.highest_bid = taken
        self.last_bid = f"{taken.value}"
        self.bids_made += 1

        dealer_name = self.dealer().name
        item = f"{dealer_name}: take {taken.value}"
        self.bid_history.append(item)

        self._finalize_bidding()
        return f"{item} (dealer closed bidding)"

    def current_trump_selector(self) -> Player:
        return self.players[self.trump_select_index]

    def choose_contract_trump(self, trump: str) -> str:
        if self.phase != "choosing_trump":
            raise ValueError("Trump selection is not active")
        if trump not in TRUMP_ORDER:
            raise ValueError("Trump must be one of: clubs, diamonds, hearts, spades, no-trump")
        if self.highest_bid is None:
            raise ValueError("No winning bid available for trump selection")

        winner_index = self.highest_bid.player_index
        declarer_name = self.players[winner_index].name
        self.contract = Bid(value=self.highest_bid.value, trump=trump, player_index=winner_index)
        self.highest_bid = self.contract
        if trump == "no-trump":
            self.no_trump_bid_seen = True
        self.last_bid = f"{self.contract.value} {self.contract.trump}"
        self.bid_history.append(f"{declarer_name}: trump {trump}")

        self.phase = "playing"
        self.trick_leader_index = self.contract.player_index
        self.play_turn_index = self.trick_leader_index
        self.current_trick.clear()
        return f"{declarer_name} selected trump: {trump}"

    def _advance_bidding_turn(self) -> None:
        self.bid_turn_index = (self.bid_turn_index + 1) % len(self.players)

    def _finalize_bidding(self) -> None:
        if self.highest_bid is None:
            raise ValueError("Cannot finalize bidding without a bid")
        if self.highest_bid.trump == "no-trump":
            # No-trump was declared during bidding — skip trump selection phase.
            winner_index = self.highest_bid.player_index
            declarer_name = self.players[winner_index].name
            self.contract = Bid(value=self.highest_bid.value, trump="no-trump", player_index=winner_index)
            self.highest_bid = self.contract
            self.no_trump_bid_seen = True
            self.last_bid = f"{self.contract.value} no-trump"
            self.bid_history.append(f"{declarer_name}: trump no-trump (declared at bid)")
            self.phase = "playing"
            self.trick_leader_index = winner_index
            self.play_turn_index = winner_index
            self.current_trick.clear()
        else:
            self.contract = None
            self.phase = "choosing_trump"
            self.trump_select_index = self.highest_bid.player_index
            self.current_trick.clear()

    def current_player_to_play(self) -> Player:
        return self.players[self.play_turn_index]

    def play_card(self, card_token: str) -> str:
        if self.phase != "playing":
            raise ValueError("Play phase is not active")

        player = self.players[self.play_turn_index]
        card = player.find_card_by_token(card_token)
        if card is None:
            raise ValueError(f"{player.name} does not have card '{card_token}'")

        if self.current_trick:
            lead_suit = self.current_trick[0][1].suit
            if card.suit != lead_suit and player.has_suit(lead_suit):
                raise ValueError(f"{player.name} must follow suit: {lead_suit}")

        player.remove_card(card)
        self.current_trick.append((self.play_turn_index, card))
        played_msg = f"{player.name} played {card.short()}"

        if len(self.current_trick) < len(self.players):
            self.play_turn_index = (self.play_turn_index + 1) % len(self.players)
            return played_msg

        winner_index, trick_points = self._resolve_current_trick()
        winner_name = self.players[winner_index].name
        team_index = winner_index % 2
        self.team_tricks[team_index] += 1
        self.team_points[team_index] += trick_points

        self.trick_number += 1
        self.current_trick.clear()
        self.trick_leader_index = winner_index
        self.play_turn_index = winner_index

        if all(len(p.hand) == 0 for p in self.players):
            self.phase = "hand_over"
            self._finalize_hand_scoring()

        return f"{played_msg} | Trick won by {winner_name} (+{trick_points} pts)"

    def _resolve_current_trick(self) -> Tuple[int, int]:
        assert self.contract is not None
        lead_suit = self.current_trick[0][1].suit
        trump = self.contract.trump

        def rank_value(card: Card) -> int:
            return RANK_ORDER.index(card.rank)

        candidates = self.current_trick
        if trump != "no-trump":
            trump_cards = [entry for entry in self.current_trick if entry[1].suit == trump]
            if trump_cards:
                candidates = trump_cards
            else:
                candidates = [entry for entry in self.current_trick if entry[1].suit == lead_suit]
        else:
            candidates = [entry for entry in self.current_trick if entry[1].suit == lead_suit]

        winner_index, _ = max(candidates, key=lambda entry: rank_value(entry[1]))

        points = 1
        for _, card in self.current_trick:
            if card.rank == "5" and card.suit == "hearts":
                points += 5
            if card.rank == "3" and card.suit == "spades":
                points -= 3

        return winner_index, points

    def _finalize_hand_scoring(self) -> None:
        """Tally hand result into game score."""
        assert self.contract is not None
        contracting_team = self.contract.player_index % 2
        defending_team = 1 - contracting_team
        score_multiplier = 2 if self.contract.trump == "no-trump" else 1
        
        # Contracting team: made bid gets points, failed deducts bid
        if self.team_points[contracting_team] >= self.contract.value:
            self.game_score[contracting_team] += self.team_points[contracting_team] * score_multiplier
        else:
            self.game_score[contracting_team] -= self.contract.value * score_multiplier
        
        # Defending team: all-or-nothing at current game target (52/64).
        # If this hand's defending points would push them past target,
        # award none of those points.
        target = self._winning_score_target()
        defending_award = self.team_points[defending_team]
        if self.game_score[defending_team] + defending_award > target:
            defending_award = 0
        self.game_score[defending_team] += defending_award
        self._update_winner_after_hand(contracting_team)

    def _winning_score_target(self) -> int:
        return 64 if self.no_trump_bid_seen else 52

    def _update_winner_after_hand(self, contracting_team: int) -> None:
        """Winner must bid out and reach target score threshold."""
        if self.winning_team_index is not None:
            return
        assert self.contract is not None

        made_contract = self.team_points[contracting_team] >= self.contract.value
        target = self._winning_score_target()
        if made_contract and self.game_score[contracting_team] >= target:
            self.winning_team_index = contracting_team

    def bidding_summary(self) -> str:
        lines = ["Bidding"]
        if not self.bid_history:
            lines.append("No bids yet")
        else:
            lines.extend(self.bid_history)
        if self.highest_bid is not None:
            leader = self.players[self.highest_bid.player_index].name
            if self.phase in ("bidding", "choosing_trump"):
                lines.append(f"Highest: {self.highest_bid.value} by {leader}")
            else:
                lines.append(f"Highest: {self.highest_bid.value} {self.highest_bid.trump} by {leader}")
        if self.phase == "bidding":
            lines.append(f"Next bidder: {self.current_bidder().name}")
            lines.append(f"Bids made: {self.bids_made}/4")
        if self.phase == "choosing_trump":
            lines.append(f"Contract winner: {self.current_trump_selector().name}")
            lines.append("Next action: choose trump")
        return "\n".join(lines)

    def trick_summary(self) -> str:
        lines = ["Trick State"]
        if self.contract is not None:
            declarer = self.players[self.contract.player_index].name
            lines.append(f"Contract: {self.contract.value} {self.contract.trump} by {declarer}")
        lines.append(f"Phase: {self.phase}")
        lines.append(f"Trick #: {self.trick_number}")
        if self.current_trick:
            lines.append("Current trick plays:")
            for idx, card in self.current_trick:
                lines.append(f"- {self.players[idx].name}: {card.short()}")
        if self.phase == "playing":
            lines.append(f"Next player: {self.current_player_to_play().name}")
        lines.append(f"Team P1/P3 tricks={self.team_tricks[0]} points={self.team_points[0]}")
        lines.append(f"Team P2/P4 tricks={self.team_tricks[1]} points={self.team_points[1]}")
        if self.phase == "hand_over":
            lines.append(f"Hand complete. Team P1/P3 game score: {self.game_score[0]}")
            lines.append(f"Hand complete. Team P2/P4 game score: {self.game_score[1]}")
            lines.append(f"Winning target: {self._winning_score_target()} (no-trump bid seen: {'yes' if self.no_trump_bid_seen else 'no'})")
            if self.winning_team_index is not None:
                if self.winning_team_index == 0:
                    lines.append("Winner: Team P1/P3 (bid out)")
                else:
                    lines.append("Winner: Team P2/P4 (bid out)")
        return "\n".join(lines)

    def state_summary(self) -> str:
        dealer_name = self.dealer().name
        bid_text = self.last_bid if self.last_bid is not None else "None"
        lines = [
            "Kaiser Core State",
            f"Dealer: {dealer_name} (index {self.dealer_index})",
            f"Phase: {self.phase}",
            f"Last bid: {bid_text}",
            f"Game score - Team P1/P3: {self.game_score[0]}, Team P2/P4: {self.game_score[1]}",
            f"Winning target: {self._winning_score_target()} (no-trump bid seen: {'yes' if self.no_trump_bid_seen else 'no'})",
        ]

        if self.winning_team_index is not None:
            winner = "Team P1/P3" if self.winning_team_index == 0 else "Team P2/P4"
            lines.append(f"Winner: {winner} (bid out)")

        if self.current_deck is not None:
            lines.append(f"Cards remaining in deck: {self.current_deck.size()}")

        for player in self.players:
            lines.append(f"{player.name}: {len(player.hand)} cards")

        if self.phase == "bidding":
            lines.append(f"Current bidder: {self.current_bidder().name}")
        elif self.phase == "choosing_trump":
            lines.append(f"Selecting trump: {self.current_trump_selector().name}")
        elif self.phase == "playing":
            lines.append(f"Current player: {self.current_player_to_play().name}")

        return "\n".join(lines)