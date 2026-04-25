#!/usr/bin/env python3
"""
WebSocket server for multiplayer Kaiser card game.
Manages game rooms and player connections.
"""
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict
from typing import Dict, List, Optional
import websockets
from websockets.server import WebSocketServerProtocol
from bot_sim import BotPolicy, BotProfile, PRESET_PROFILES
from kaiser import KaiserGame

try:
    from google.cloud import firestore
except ImportError:
    firestore = None


BOT_PERSONAS: List[dict] = [
    {
        "name": "Anne",
        "profile": "balanced",
        "bio": "Balanced bidding. Anne reads the table and avoids wild swings. Off-table she is the organized one who always brings score sheets and snacks.",
    },
    {
        "name": "Lillian",
        "profile": "cautious",
        "bio": "Cautious bidding. Lillian values safe contracts and disciplined card management. She is thoughtful, observant, and quietly competitive.",
    },
    {
        "name": "Nelson",
        "profile": "chaotic",
        "bio": "Chaotic bidding style. Nelson brings unpredictable lines and momentum plays. Around the table he keeps things lively with playful banter.",
    },
    {
        "name": "Edward",
        "profile": "aggressive",
        "bio": "Aggressive bidding style. Edward pushes bids and pressures opponents early. Socially he is bold, confident, and loves high-stakes moments.",
    },
]


class GameRoom:
    """Manages a single game instance with 4 players."""
    
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.game = KaiserGame.new_default()
        self.players: Dict[int, WebSocketServerProtocol] = {}  # player_index -> websocket
        self.player_names: Dict[int, str] = {}  # player_index -> name
        self.observers: Dict[WebSocketServerProtocol, str] = {}  # websocket -> observer name
        self.bot_policies: Dict[int, BotPolicy] = {}  # player_index -> policy
        self.bot_personas: Dict[int, dict] = {}  # player_index -> persona metadata
        self.host_player_index: Optional[int] = None
        self.host_observer_ws: Optional[WebSocketServerProtocol] = None
        self.setup_complete: bool = False
        self.ready = False
        self.session_wins: List[int] = [0, 0]
        self.current_game_winner_recorded: bool = False
        self.new_game_votes: set[int] = set()
        self.last_timeout_refresh_at: float = time.time()
        self.game_sequence: int = 1
        self.current_game_id: str = uuid.uuid4().hex
        self.current_game_started_at: float = time.time()

    def _recompute_ready(self) -> None:
        self.ready = (len(self.players) + len(self.bot_policies)) == 4

    def is_observer(self, ws: WebSocketServerProtocol) -> bool:
        return ws in self.observers

    def mark_timeout_refresh(self) -> None:
        # Any explicit user action updates this marker so clients can display that keepalive activity happened.
        self.last_timeout_refresh_at = time.time()

    def is_bot_seat(self, player_index: int) -> bool:
        return player_index in self.bot_policies

    def available_bot_personas(self) -> List[dict]:
        used_names = {self.game.players[idx].name for idx in self.bot_personas}
        return [persona for persona in BOT_PERSONAS if persona["name"] not in used_names]

    def setup_options_payload(self) -> dict:
        human_options = [
            {
                "id": f"human:{seat}",
                "name": self.player_names[seat],
                "seat": seat,
            }
            for seat in sorted(self.players.keys())
        ]
        bot_options = [
            {
                "id": f"bot:{persona['name']}",
                "name": persona["name"],
            }
            for persona in BOT_PERSONAS
        ]

        current_assignments: List[Optional[str]] = []
        for seat in range(4):
            if seat in self.players:
                current_assignments.append(f"human:{seat}")
            elif seat in self.bot_personas:
                current_assignments.append(f"bot:{self.bot_personas[seat]['name']}")
            else:
                current_assignments.append(None)

        return {
            "setup": {
                "human_options": human_options,
                "bot_options": bot_options,
                "current_assignments": current_assignments,
            }
        }

    def enable_observer_learning_mode(self, host_ws: WebSocketServerProtocol) -> List[dict]:
        if self.setup_complete:
            raise ValueError("Game setup is already complete")
        if self.host_player_index is None:
            raise ValueError("Observer mode requires an active host")
        if len(self.players) != 1:
            raise ValueError("Observer mode can only start when you are the only connected human")
        if host_ws != self.players.get(self.host_player_index):
            raise ValueError("Only the host can enable observer mode")

        host_name = self.player_names.get(self.host_player_index, "Host")
        del self.players[self.host_player_index]
        del self.player_names[self.host_player_index]
        self.observers[host_ws] = host_name
        self.host_observer_ws = host_ws
        self.host_player_index = None

        assignments = [f"bot:{persona['name']}" for persona in BOT_PERSONAS]
        return self.apply_setup_assignments(assignments)

    def apply_setup_assignments(self, seat_assignments: List[str]) -> List[dict]:
        if len(seat_assignments) != 4:
            raise ValueError("Setup requires exactly 4 seat assignments")
        if len(set(seat_assignments)) != 4:
            raise ValueError("Seat assignments must be unique")

        old_players = dict(self.players)
        old_names = dict(self.player_names)
        host_ws = old_players.get(self.host_player_index) if self.host_player_index is not None else None

        valid_human_ids = {f"human:{seat}" for seat in old_players.keys()}
        selected_humans = [item for item in seat_assignments if item.startswith("human:")]
        if set(selected_humans) != valid_human_ids:
            raise ValueError("All connected human players must be assigned exactly once")

        bot_lookup = {f"bot:{persona['name']}": persona for persona in BOT_PERSONAS}

        new_players: Dict[int, WebSocketServerProtocol] = {}
        new_player_names: Dict[int, str] = {}
        new_bot_policies: Dict[int, BotPolicy] = {}
        new_bot_personas: Dict[int, dict] = {}

        for seat, assignment in enumerate(seat_assignments):
            if assignment in valid_human_ids:
                old_seat = int(assignment.split(":", 1)[1])
                ws = old_players.get(old_seat)
                if ws is None:
                    raise ValueError("Invalid human seat assignment")
                name = old_names[old_seat]
                new_players[seat] = ws
                new_player_names[seat] = name
                self.game.players[seat].name = name
                continue

            persona = bot_lookup.get(assignment)
            if persona is None:
                raise ValueError(f"Invalid setup assignment '{assignment}'")

            preset = PRESET_PROFILES[persona["profile"]]
            profile = BotProfile(**asdict(preset))
            new_bot_policies[seat] = BotPolicy(profile=profile)
            new_bot_personas[seat] = persona
            self.game.players[seat].name = persona["name"]

        self.players = new_players
        self.player_names = new_player_names
        self.bot_policies = new_bot_policies
        self.bot_personas = new_bot_personas
        self.setup_complete = True
        self.new_game_votes.clear()

        if host_ws is not None:
            for seat, ws in self.players.items():
                if ws == host_ws:
                    self.host_player_index = seat
                    break
        elif self.host_observer_ws is None:
            self.host_player_index = None
        if self.host_player_index is None and self.players:
            self.host_player_index = min(self.players.keys())

        self._recompute_ready()
        return [
            {
                "seat": seat,
                "type": "bot",
                "name": persona["name"],
                "profile": persona["profile"],
            }
            for seat, persona in sorted(self.bot_personas.items())
        ]

    def add_bots_to_fill(self) -> List[dict]:
        default_assignments: List[str] = []
        available_bots = [f"bot:{persona['name']}" for persona in BOT_PERSONAS]
        cursor = 0
        for seat in range(4):
            if seat in self.players:
                default_assignments.append(f"human:{seat}")
            else:
                default_assignments.append(available_bots[cursor])
                cursor += 1
        return self.apply_setup_assignments(default_assignments)

    def restart_game(self) -> None:
        self.game = KaiserGame.new_default()
        self.game_sequence += 1
        self.current_game_id = uuid.uuid4().hex
        self.current_game_started_at = time.time()
        self.current_game_winner_recorded = False
        self.new_game_votes.clear()
        self.mark_timeout_refresh()
        for seat in range(4):
            if seat in self.players:
                name = self.player_names.get(seat, f"Player {seat + 1}")
                self.game.players[seat].name = name
            elif seat in self.bot_personas:
                self.game.players[seat].name = self.bot_personas[seat]["name"]
        self.setup_complete = bool(self.players or self.bot_personas)
        self._recompute_ready()

    def start_new_game(self) -> None:
        """Start a fresh game with the current seats and setup kept intact."""
        self.game = KaiserGame.new_default()
        self.game_sequence += 1
        self.current_game_id = uuid.uuid4().hex
        self.current_game_started_at = time.time()
        self.current_game_winner_recorded = False
        self.new_game_votes.clear()
        self.mark_timeout_refresh()

        for seat in range(4):
            if seat in self.players:
                self.game.players[seat].name = self.player_names.get(seat, f"Player {seat + 1}")
            elif seat in self.bot_personas:
                self.game.players[seat].name = self.bot_personas[seat]["name"]

        self._recompute_ready()

    def required_new_game_votes(self) -> int:
        return len(self.players)

    def register_new_game_vote(self, player_index: int) -> None:
        if player_index in self.players:
            self.new_game_votes.add(player_index)
            self.mark_timeout_refresh()

    def record_winner_if_needed(self) -> None:
        winner = self.game.winning_team_index
        if winner is None or self.current_game_winner_recorded:
            return
        if winner in (0, 1):
            self.session_wins[winner] += 1
            self.current_game_winner_recorded = True

    def room_payload(self) -> dict:
        roster = []
        for seat in range(4):
            if seat in self.players:
                roster.append(
                    {
                        "seat": seat,
                        "type": "human",
                        "name": self.game.players[seat].name,
                    }
                )
            elif seat in self.bot_personas:
                persona = self.bot_personas[seat]
                roster.append(
                    {
                        "seat": seat,
                        "type": "bot",
                        "name": persona["name"],
                        "profile": persona["profile"],
                        "bio": persona["bio"],
                    }
                )
            else:
                roster.append({"seat": seat, "type": "empty", "name": None})

        return {
            "room": {
                "humans": len(self.players),
                "observers": len(self.observers),
                "bots": len(self.bot_policies),
                "ready": self.ready,
                "setup_complete": self.setup_complete,
                "host_player_index": self.host_player_index,
                "host_is_observer": self.host_observer_ws is not None,
                "roster": roster,
                "available_virtual_players": [
                    {
                        "id": f"bot:{persona['name']}",
                        "name": persona["name"],
                    }
                    for persona in BOT_PERSONAS
                ],
                **self.setup_options_payload(),
            }
        }
    
    def add_player(self, ws: WebSocketServerProtocol, name: str) -> Optional[int]:
        """Add a player to the room. Returns player index or None if room full."""
        for i in range(4):
            if i not in self.players and i not in self.bot_policies:
                self.players[i] = ws
                self.player_names[i] = name
                self.game.players[i].name = name
                if self.host_player_index is None:
                    self.host_player_index = i
                self._recompute_ready()
                return i
        return None

    def add_observer(self, ws: WebSocketServerProtocol, name: str, is_host: bool = False) -> None:
        self.observers[ws] = name
        if is_host:
            self.host_observer_ws = ws

    def remove_observer(self, ws: WebSocketServerProtocol) -> Optional[str]:
        name = self.observers.pop(ws, None)
        if self.host_observer_ws == ws:
            self.host_observer_ws = None
        return name
    
    def remove_player(self, ws: WebSocketServerProtocol) -> Optional[int]:
        """Remove a player from the room. Returns their index or None."""
        for idx, player_ws in self.players.items():
            if player_ws == ws:
                del self.players[idx]
                del self.player_names[idx]
                if self.host_player_index == idx:
                    self.host_player_index = min(self.players.keys()) if self.players else None
                if idx in self.new_game_votes:
                    self.new_game_votes.remove(idx)
                self._recompute_ready()
                return idx
        return None
    
    def get_player_index(self, ws: WebSocketServerProtocol) -> Optional[int]:
        """Get the player index for a websocket."""
        for idx, player_ws in self.players.items():
            if player_ws == ws:
                return idx
        return None
    
    async def broadcast(self, message: dict, exclude: Optional[WebSocketServerProtocol] = None):
        """Send a message to all players in the room."""
        disconnected = []
        for idx, ws in self.players.items():
            if ws != exclude:
                try:
                    await ws.send(json.dumps(message))
                except:
                    disconnected.append(idx)

        disconnected_observers: List[WebSocketServerProtocol] = []
        for ws in list(self.observers.keys()):
            if ws == exclude:
                continue
            try:
                await ws.send(json.dumps(message))
            except:
                disconnected_observers.append(ws)
        
        # Clean up disconnected players
        for idx in disconnected:
            if idx in self.players:
                del self.players[idx]
            if idx in self.player_names:
                del self.player_names[idx]
            if self.host_player_index == idx:
                self.host_player_index = min(self.players.keys()) if self.players else None
            self._recompute_ready()

        for ws in disconnected_observers:
            self.remove_observer(ws)
    
    async def send_to_player(self, player_index: int, message: dict):
        """Send a message to a specific player."""
        if player_index in self.players:
            try:
                await self.players[player_index].send(json.dumps(message))
            except:
                pass


class GameServer:
    """Manages multiple game rooms."""
    
    def __init__(self):
        self.rooms: Dict[str, GameRoom] = {}
        self.connections: Dict[WebSocketServerProtocol, tuple] = {}  # ws -> (room_id, player_index or None)
        self.bot_turn_delay_seconds = float(os.environ.get("BOT_TURN_DELAY_SECONDS", "1.2"))
        self.trick_clear_pause_seconds = float(os.environ.get("TRICK_CLEAR_PAUSE_SECONDS", "4.0"))
        self.human_trick_result_pause_seconds = float(
            os.environ.get("HUMAN_TRICK_RESULT_PAUSE_SECONDS", str(self.trick_clear_pause_seconds))
        )
        self.firestore_enabled = os.environ.get("FIRESTORE_ENABLED", "1").lower() not in ("0", "false", "no")
        self.firestore_collection = os.environ.get("FIRESTORE_GAMES_COLLECTION", "kaiser_game_stats")
        self.firestore_client = None
        if self.firestore_enabled and firestore is not None:
            project_id = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
            try:
                self.firestore_client = firestore.Client(project=project_id) if project_id else firestore.Client()
            except Exception as exc:
                print(f"[firestore] Disabled: failed to initialize client: {exc}")
                self.firestore_client = None

    async def _persist_room_snapshot(self, room: GameRoom, event_type: str) -> None:
        if self.firestore_client is None:
            return

        game = room.game
        status = "completed" if game.winning_team_index in (0, 1) else "partial"
        payload = {
            "game_id": room.current_game_id,
            "game_started": room.current_game_started_at,
            "last_event": event_type,
            "status": status,
            "score": {
                "team0": game.game_score[0],
                "team1": game.game_score[1],
            },
            "players": [player.name for player in game.players],
            "points": {
                "team0": game.team_points[0],
                "team1": game.team_points[1],
            },
            "tricks": {
                "team0": game.team_tricks[0],
                "team1": game.team_tricks[1],
            },
            "updated_at_unix": time.time(),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        doc_id = f"{room.room_id}_{room.current_game_id}"

        def _write() -> None:
            self.firestore_client.collection(self.firestore_collection).document(doc_id).set(payload, merge=True)

        try:
            await asyncio.to_thread(_write)
        except Exception as exc:
            print(f"[firestore] Failed to write game snapshot for {doc_id}: {exc}")
    
    def create_room(self, room_id: str) -> GameRoom:
        """Create a new game room."""
        if room_id not in self.rooms:
            self.rooms[room_id] = GameRoom(room_id)
        return self.rooms[room_id]
    
    def get_room(self, room_id: str) -> Optional[GameRoom]:
        """Get an existing room."""
        return self.rooms.get(room_id)

    def _turn_payload(self, game: KaiserGame) -> dict:
        if game.phase == "bidding":
            index = game.bid_turn_index
            return {
                "current_player_index": index,
                "current_player_name": game.players[index].name,
                "turn_context": "bidding",
            }
        if game.phase == "choosing_trump":
            index = game.trump_select_index
            return {
                "current_player_index": index,
                "current_player_name": game.players[index].name,
                "turn_context": "choosing_trump",
            }
        if game.phase == "playing":
            index = game.play_turn_index
            return {
                "current_player_index": index,
                "current_player_name": game.players[index].name,
                "turn_context": "playing",
            }
        index = game.dealer_index
        return {
            "current_player_index": index,
            "current_player_name": game.players[index].name,
            "turn_context": "idle",
        }

    def _scoreboard_payload(self, game: KaiserGame, room: Optional[GameRoom] = None) -> dict:
        team0_label = f"{game.players[0].name}/{game.players[2].name}"
        team1_label = f"{game.players[1].name}/{game.players[3].name}"

        if game.phase == "hand_over":
            live_game_team0 = game.game_score[0]
            live_game_team1 = game.game_score[1]
        else:
            live_game_team0 = game.game_score[0] + game.team_points[0]
            live_game_team1 = game.game_score[1] + game.team_points[1]

        bid = None
        bid_source = game.highest_bid if game.highest_bid is not None else game.contract
        if bid_source is not None:
            declarer = game.players[bid_source.player_index].name
            team_index = bid_source.player_index % 2
            bid_trump = bid_source.trump if game.phase not in ("bidding", "choosing_trump") else "hidden"
            bid = {
                "value": bid_source.value,
                "trump": bid_trump,
                "declarer": declarer,
                "team_index": team_index,
                "team_label": team0_label if team_index == 0 else team1_label,
            }

        winner_exists = game.winning_team_index in (0, 1)
        new_game_votes = len(room.new_game_votes) if room is not None else 0
        new_game_required_votes = room.required_new_game_votes() if room is not None else 0
        new_game_ready = (new_game_required_votes == 0) or (new_game_votes >= new_game_required_votes)
        return {
            "scoreboard": {
                "phase": game.phase,
                "dealer_index": game.dealer_index,
                "dealer_name": game.players[game.dealer_index].name,
                "winning": {
                    "target": 64 if game.no_trump_bid_seen else 52,
                    "no_trump_bid_seen": game.no_trump_bid_seen,
                    "winner_team_index": game.winning_team_index,
                    "winner_team_label": (
                        team0_label if game.winning_team_index == 0 else team1_label if game.winning_team_index == 1 else None
                    ),
                },
                "team_labels": {
                    "team0": team0_label,
                    "team1": team1_label,
                },
                "game_score": {
                    "team0": game.game_score[0],
                    "team1": game.game_score[1],
                },
                "live_game_score": {
                    "team0": live_game_team0,
                    "team1": live_game_team1,
                },
                "session_wins": {
                    "team0": room.session_wins[0] if room is not None else 0,
                    "team1": room.session_wins[1] if room is not None else 0,
                },
                "hand": {
                    "tricks": {
                        "team0": game.team_tricks[0],
                        "team1": game.team_tricks[1],
                    },
                    "points": {
                        "team0": game.team_points[0],
                        "team1": game.team_points[1],
                    },
                    "trick_number": game.trick_number,
                },
                "bid": bid,
                "new_game": {
                    "available": bool(room is not None and room.setup_complete and winner_exists),
                    "votes": new_game_votes,
                    "required_votes": new_game_required_votes,
                    "ready_to_start": new_game_ready,
                    "voted_players": sorted(list(room.new_game_votes)) if room is not None else [],
                    "timeout_refreshed_at": room.last_timeout_refresh_at if room is not None else None,
                },
            }
        }

    async def _send_hands_to_humans(self, room: GameRoom) -> None:
        game = room.game
        for idx in room.players:
            await room.send_to_player(
                idx,
                {
                    "type": "hand",
                    "cards": game.players[idx].show_hand(),
                },
            )

    async def _run_bot_turns(self, room: GameRoom) -> None:
        game = room.game

        while room.ready:
            if game.phase == "bidding":
                seat = game.bid_turn_index
            elif game.phase == "choosing_trump":
                seat = game.trump_select_index
            elif game.phase == "playing":
                seat = game.play_turn_index
            else:
                break

            if not room.is_bot_seat(seat):
                break

            bot_policy = room.bot_policies[seat]
            bot_name = game.players[seat].name
            try:
                if game.phase == "bidding":
                    action, payload, reason = bot_policy.choose_bid_action(game, seat)
                    if action == "bid":
                        result = game.place_bid(value=int(payload["value"]), trump=payload.get("trump"))
                    elif action == "take":
                        result = game.dealer_take_bid(trump=payload.get("trump"))
                    elif action == "pass":
                        result = game.pass_bid()
                    else:
                        result = game.pass_bid()

                    await room.broadcast(
                        {
                            "type": "game_update",
                            "message": result,
                            "phase": game.phase,
                            "bidding": game.bidding_summary(),
                            "bot_action": {
                                "bot_name": bot_name,
                                "action": action,
                                "reason": reason,
                                "debug": payload.get("__debug", {}),
                            },
                            **self._turn_payload(game),
                            **self._scoreboard_payload(game, room),
                            **room.room_payload(),
                        }
                    )
                    await self._persist_room_snapshot(room, "bot_bid_action")

                    if game.phase == "choosing_trump":
                        await room.broadcast(
                            {
                                "type": "phase_change",
                                "phase": "choosing_trump",
                                "message": f"Bidding complete. {game.current_trump_selector().name} selects trump.",
                                "bidding": game.bidding_summary(),
                                **self._turn_payload(game),
                                **self._scoreboard_payload(game, room),
                                **room.room_payload(),
                            }
                        )
                        await self._persist_room_snapshot(room, "bot_phase_change")
                    if game.phase == "playing":
                        await room.broadcast(
                            {
                                "type": "phase_change",
                                "phase": "playing",
                                "message": "Bidding complete. Play phase started.",
                                "trick": game.trick_summary(),
                                **self._turn_payload(game),
                                **self._scoreboard_payload(game, room),
                                **room.room_payload(),
                            }
                        )
                        await self._persist_room_snapshot(room, "bot_phase_change")
                    if self.bot_turn_delay_seconds > 0:
                        await asyncio.sleep(self.bot_turn_delay_seconds)
                elif game.phase == "choosing_trump":
                    action, payload, reason = bot_policy.choose_trump_action(game, seat)
                    result = game.choose_contract_trump(str(payload["trump"]))

                    await room.broadcast(
                        {
                            "type": "game_update",
                            "message": result,
                            "phase": game.phase,
                            "bidding": game.bidding_summary(),
                            "bot_action": {
                                "bot_name": bot_name,
                                "action": action,
                                "reason": reason,
                                "debug": payload.get("__debug", {}),
                            },
                            **self._turn_payload(game),
                            **self._scoreboard_payload(game, room),
                            **room.room_payload(),
                        }
                    )
                    await self._persist_room_snapshot(room, "bot_choose_trump")

                    if game.phase == "playing":
                        await room.broadcast(
                            {
                                "type": "phase_change",
                                "phase": "playing",
                                "message": "Trump selected. Play phase started.",
                                "trick": game.trick_summary(),
                                **self._turn_payload(game),
                                **self._scoreboard_payload(game, room),
                                **room.room_payload(),
                            }
                        )
                        await self._persist_room_snapshot(room, "bot_phase_change")
                    if self.bot_turn_delay_seconds > 0:
                        await asyncio.sleep(self.bot_turn_delay_seconds)
                else:
                    action, payload, reason = bot_policy.choose_play_card(game, seat)
                    result = game.play_card(str(payload["card"]))
                    room.record_winner_if_needed()
                    await room.broadcast(
                        {
                            "type": "game_update",
                            "message": result,
                            "phase": game.phase,
                            "trick": game.trick_summary(),
                            "bot_action": {
                                "bot_name": bot_name,
                                "action": action,
                                "reason": reason,
                                "debug": payload.get("__debug", {}),
                            },
                            **self._turn_payload(game),
                            **self._scoreboard_payload(game, room),
                            **room.room_payload(),
                        }
                    )
                    await self._persist_room_snapshot(room, "bot_play_card")
                    await self._send_hands_to_humans(room)

                    trick_completed = isinstance(result, str) and "| Trick won by " in result
                    if (
                        trick_completed
                        and game.phase == "playing"
                        and room.is_bot_seat(game.play_turn_index)
                        and self.trick_clear_pause_seconds > 0
                    ):
                        await asyncio.sleep(self.trick_clear_pause_seconds)
                        continue

                    if game.phase == "hand_over":
                        await room.broadcast(
                            {
                                "type": "hand_complete",
                                "message": "Hand complete.",
                                "trick": game.trick_summary(),
                                "state": game.state_summary(),
                                **self._scoreboard_payload(game, room),
                                **room.room_payload(),
                            }
                        )
                        await self._persist_room_snapshot(room, "hand_complete")
                        break
                    if self.bot_turn_delay_seconds > 0:
                        await asyncio.sleep(self.bot_turn_delay_seconds)
            except Exception as exc:
                await room.broadcast(
                    {
                        "type": "game_update",
                        "message": f"Bot action failed for {bot_name}: {exc}",
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    }
                )
                await self._persist_room_snapshot(room, "bot_action_error")
                break
    
    async def handle_connection(self, websocket: WebSocketServerProtocol):
        """Handle a new WebSocket connection."""
        room_id = None
        player_index = None
        
        try:
            # Wait for initial join message
            message = await websocket.recv()
            data = json.loads(message)
            
            if data.get("action") != "join":
                await websocket.send(json.dumps({"error": "First message must be 'join'"}))
                return
            
            room_id = data.get("room_id", "mygame")
            player_name = data.get("name", f"Player{len(self.connections) + 1}")
            
            # Get or create room
            room = self.get_room(room_id)
            if not room:
                room = self.create_room(room_id)
            
            # Add player to room. Observer mode is single-host-only and does not allow extra spectators.
            player_index = room.add_player(websocket, player_name)
            is_observer = False
            if player_index is None:
                await websocket.send(json.dumps({"error": "Room is full"}))
                return
            
            self.connections[websocket] = (room_id, player_index)
            
            # Send join confirmation
            await websocket.send(json.dumps({
                "type": "joined",
                "room_id": room_id,
                "player_index": player_index,
                "player_name": player_name,
                "players_count": len(room.players),
                "is_host": (player_index is not None and player_index == room.host_player_index) or (is_observer and websocket == room.host_observer_ws),
                "is_observer": is_observer,
                "setup_required": (
                    ((player_index is not None and player_index == room.host_player_index) or (is_observer and websocket == room.host_observer_ws))
                    and not room.setup_complete
                ),
                **self._turn_payload(room.game),
                **self._scoreboard_payload(room.game, room),
                **room.room_payload(),
            }))
            await self._persist_room_snapshot(room, "player_joined")
            
            # Notify other players
            await room.broadcast({
                "type": "player_joined",
                "player_name": player_name,
                "player_index": player_index,
                "is_observer": is_observer,
                "players_count": len(room.players),
                "ready": room.ready,
                **self._turn_payload(room.game),
                **self._scoreboard_payload(room.game, room),
                **room.room_payload(),
            }, exclude=websocket)
            
            # Handle game commands
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_command(room, websocket, data)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"error": "Invalid JSON"}))
                except Exception as e:
                    await websocket.send(json.dumps({"error": str(e)}))
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            # Clean up on disconnect
            if websocket in self.connections:
                room_id, player_index = self.connections[websocket]
                del self.connections[websocket]
                
                room = self.get_room(room_id)
                if room:
                    current_index = room.get_player_index(websocket)
                    if current_index is not None:
                        player_name = room.player_names.get(current_index, "Unknown")
                        room.remove_player(websocket)
                    else:
                        player_name = room.remove_observer(websocket) or "Unknown"
                    
                    # Notify remaining players
                    await room.broadcast({
                        "type": "player_left",
                        "player_name": player_name,
                        "player_index": current_index,
                        "players_count": len(room.players),
                        "observers_count": len(room.observers),
                        "ready": room.ready,
                        **self._turn_payload(room.game),
                        **self._scoreboard_payload(room.game, room),
                        **room.room_payload(),
                    })
                    await self._persist_room_snapshot(room, "player_left")
    
    async def handle_command(self, room: GameRoom, websocket: WebSocketServerProtocol, data: dict):
        """Handle a game command from a player."""
        action = data.get("action")
        game = room.game
        run_bots_after = False
        pause_before_bots = False
        persist_after_action = False
        is_host_observer = room.host_observer_ws == websocket
        player_index = room.get_player_index(websocket)
        if player_index is None and not is_host_observer:
            raise ValueError("Player is not seated in this room")

        def require_active_bidder() -> None:
            if game.phase != "bidding":
                raise ValueError("Bidding is not active")
            active_index = game.bid_turn_index
            if player_index != active_index:
                active_name = game.players[active_index].name
                raise ValueError(f"Not your turn to bid. Active bidder: {active_name}")

        def require_trump_selector() -> None:
            if game.phase != "choosing_trump":
                raise ValueError("Trump selection is not active")
            active_index = game.trump_select_index
            if player_index != active_index:
                active_name = game.players[active_index].name
                raise ValueError(f"Not your turn to select trump. Active player: {active_name}")

        def require_active_player() -> None:
            if game.phase != "playing":
                raise ValueError("Play phase is not active")
            active_index = game.play_turn_index
            if player_index != active_index:
                active_name = game.players[active_index].name
                raise ValueError(f"Not your turn to play. Active player: {active_name}")
        
        try:
            room.mark_timeout_refresh()
            if action == "setup_game":
                if player_index != room.host_player_index:
                    raise ValueError("Only the first connected player can run game setup")
                if room.setup_complete:
                    raise ValueError("Game setup is already complete")

                seat_assignments = data.get("seat_assignments")
                if isinstance(seat_assignments, list) and seat_assignments:
                    added = room.apply_setup_assignments([str(item) for item in seat_assignments])
                else:
                    added = room.add_bots_to_fill()
                added_names = ", ".join(bot["name"] for bot in added) if added else "none"
                await room.broadcast({
                    "type": "setup_complete",
                    "message": f"Game setup complete. Virtual players added: {added_names}.",
                    "added_bots": added,
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                persist_after_action = True

                for seat in sorted(room.players.keys()):
                    await room.send_to_player(
                        seat,
                        {
                            "type": "seat_assigned",
                            "player_index": seat,
                            "is_host": seat == room.host_player_index,
                            "setup_required": (seat == room.host_player_index and not room.setup_complete),
                            **self._turn_payload(game),
                            **self._scoreboard_payload(game, room),
                            **room.room_payload(),
                        },
                    )

            elif action == "setup_observer_mode":
                if player_index != room.host_player_index:
                    raise ValueError("Only the first connected player can enable observer mode")
                added = room.enable_observer_learning_mode(websocket)
                game = room.game
                added_names = ", ".join(bot["name"] for bot in added) if added else "none"
                await room.broadcast({
                    "type": "setup_complete",
                    "message": f"Observer mode ready. Watching AI table: {added_names}.",
                    "added_bots": added,
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                await websocket.send(json.dumps({
                    "type": "seat_assigned",
                    "player_index": None,
                    "is_host": True,
                    "is_observer": True,
                    "setup_required": False,
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                }))
                persist_after_action = True

            elif action == "state":
                await websocket.send(json.dumps({
                    "type": "state",
                    "content": game.state_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                }))
            
            elif action == "deal":
                if not room.ready:
                    raise ValueError("Need 4 players to start")
                if not is_host_observer and player_index != game.dealer_index:
                    dealer_name = game.players[game.dealer_index].name
                    raise ValueError(f"Only the dealer can deal. Current dealer: {dealer_name}")
                game.deal_new_hand()
                await room.broadcast({
                    "type": "game_update",
                    "message": "Dealt 8 cards to each player.",
                    "state": game.state_summary(),
                    "phase": game.phase,
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                # Send each player their hand privately
                await self._send_hands_to_humans(room)
                run_bots_after = True
                persist_after_action = True

            elif action == "next_hand":
                if not room.ready:
                    raise ValueError("Need 4 players to start")
                if game.phase != "hand_over":
                    raise ValueError("Next hand can only be started after a hand is complete")
                if not is_host_observer:
                    if player_index not in room.players:
                        raise ValueError("Only seated human players can start the next hand")

                new_dealer = game.rotate_dealer()
                game.deal_new_hand()
                await room.broadcast({
                    "type": "game_update",
                    "message": f"Starting next hand. Dealer rotated to {new_dealer.name}. Dealt 8 cards to each player.",
                    "state": game.state_summary(),
                    "phase": game.phase,
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                await self._send_hands_to_humans(room)
                run_bots_after = True
                persist_after_action = True

            elif action == "start_new_game":
                if game.winning_team_index not in (0, 1):
                    raise ValueError("New game can only be started after a winner is determined")

                if is_host_observer and room.required_new_game_votes() == 0:
                    room.start_new_game()
                    game = room.game
                    await room.broadcast({
                        "type": "new_game_started",
                        "message": "Observer host started a new AI game.",
                        "state": game.state_summary(),
                        "phase": game.phase,
                        "timeout_refreshed_at": room.last_timeout_refresh_at,
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                    persist_after_action = True
                else:
                    room.register_new_game_vote(player_index)
                    votes = len(room.new_game_votes)
                    required_votes = room.required_new_game_votes()
                    await room.broadcast({
                        "type": "new_game_vote",
                        "message": f"{game.players[player_index].name} is ready for a new game ({votes}/{required_votes}).",
                        "new_game": {
                            "votes": votes,
                            "required_votes": required_votes,
                            "timeout_refreshed_at": room.last_timeout_refresh_at,
                        },
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })

                    if required_votes > 0 and votes >= required_votes:
                        room.start_new_game()
                        game = room.game
                        await room.broadcast({
                            "type": "new_game_started",
                            "message": "All players confirmed. New game is ready. Dealer can deal.",
                            "state": game.state_summary(),
                            "phase": game.phase,
                            "timeout_refreshed_at": room.last_timeout_refresh_at,
                            **self._turn_payload(game),
                            **self._scoreboard_payload(game, room),
                            **room.room_payload(),
                        })
                    persist_after_action = True

            elif action == "restart_game":
                if not ((player_index is not None and player_index == room.host_player_index) or is_host_observer):
                    raise ValueError("Only the host can restart the game")
                room.restart_game()
                game = room.game
                await room.broadcast({
                    "type": "game_update",
                    "message": "Game reset. Existing seats preserved. Dealer can deal again.",
                    "state": game.state_summary(),
                    "phase": game.phase,
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                persist_after_action = True
            
            elif action == "hands":
                hand = game.players[player_index].show_hand()
                await websocket.send(json.dumps({
                    "type": "hand",
                    "cards": hand
                }))
            
            elif action == "bidding":
                await websocket.send(json.dumps({
                    "type": "bidding",
                    "content": game.bidding_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                }))
            
            elif action == "bid":
                require_active_bidder()
                value = data.get("value")
                result = game.place_bid(value=value, trump=data.get("trump"))
                await room.broadcast({
                    "type": "game_update",
                    "message": result,
                    "phase": game.phase,
                    "bidding": game.bidding_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                if game.phase == "choosing_trump":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "choosing_trump",
                        "message": f"Bidding complete. {game.current_trump_selector().name} selects trump.",
                        "bidding": game.bidding_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                if game.phase == "playing":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "playing",
                        "message": "Bidding complete. Play phase started.",
                        "trick": game.trick_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                run_bots_after = True
                persist_after_action = True
            
            elif action == "pass":
                require_active_bidder()
                result = game.pass_bid()
                await room.broadcast({
                    "type": "game_update",
                    "message": result,
                    "phase": game.phase,
                    "bidding": game.bidding_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                if game.phase == "choosing_trump":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "choosing_trump",
                        "message": f"Bidding complete. {game.current_trump_selector().name} selects trump.",
                        "bidding": game.bidding_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                if game.phase == "playing":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "playing",
                        "message": "Bidding complete. Play phase started.",
                        "trick": game.trick_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                run_bots_after = True
                persist_after_action = True
            
            elif action == "take":
                require_active_bidder()
                if player_index != game.dealer_index:
                    raise ValueError("Only the dealer can take the highest bid")
                result = game.dealer_take_bid(trump=data.get("trump"))
                await room.broadcast({
                    "type": "game_update",
                    "message": result,
                    "phase": game.phase,
                    "bidding": game.bidding_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                if game.phase == "choosing_trump":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "choosing_trump",
                        "message": f"Bidding complete. {game.current_trump_selector().name} selects trump.",
                        "bidding": game.bidding_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                if game.phase == "playing":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "playing",
                        "message": "Bidding complete. Play phase started.",
                        "trick": game.trick_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                run_bots_after = True
                persist_after_action = True

            elif action == "choose_trump":
                require_trump_selector()
                trump = data.get("trump")
                result = game.choose_contract_trump(trump=trump)
                await room.broadcast({
                    "type": "game_update",
                    "message": result,
                    "phase": game.phase,
                    "bidding": game.bidding_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                if game.phase == "playing":
                    await room.broadcast({
                        "type": "phase_change",
                        "phase": "playing",
                        "message": "Trump selected. Play phase started.",
                        "trick": game.trick_summary(),
                        **self._turn_payload(game),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                run_bots_after = True
                persist_after_action = True
            
            elif action == "trick":
                await websocket.send(json.dumps({
                    "type": "trick",
                    "content": game.trick_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                }))
            
            elif action == "play":
                require_active_player()
                card_token = data.get("card")
                result = game.play_card(card_token)
                room.record_winner_if_needed()
                await room.broadcast({
                    "type": "game_update",
                    "message": result,
                    "phase": game.phase,
                    "trick": game.trick_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                # Update all players' hands
                await self._send_hands_to_humans(room)
                # If a human closes a trick and a bot leads next, keep completed trick visible briefly.
                trick_completed = isinstance(result, str) and "| Trick won by " in result
                if (
                    trick_completed
                    and game.phase == "playing"
                    and room.is_bot_seat(game.play_turn_index)
                    and self.human_trick_result_pause_seconds > 0
                ):
                    pause_before_bots = True
                if game.phase == "hand_over":
                    await room.broadcast({
                        "type": "hand_complete",
                        "message": "Hand complete.",
                        "trick": game.trick_summary(),
                        "state": game.state_summary(),
                        **self._scoreboard_payload(game, room),
                        **room.room_payload(),
                    })
                run_bots_after = True
                persist_after_action = True
            
            elif action == "rotate":
                new_dealer = game.rotate_dealer()
                await room.broadcast({
                    "type": "game_update",
                    "message": f"Dealer rotated to {new_dealer.name}.",
                    "state": game.state_summary(),
                    **self._turn_payload(game),
                    **self._scoreboard_payload(game, room),
                    **room.room_payload(),
                })
                persist_after_action = True
            
            else:
                await websocket.send(json.dumps({"error": f"Unknown action: {action}"}))

            if persist_after_action:
                await self._persist_room_snapshot(room, f"human_{action}")

            if run_bots_after:
                if pause_before_bots:
                    await asyncio.sleep(self.human_trick_result_pause_seconds)
                await self._run_bot_turns(room)
        
        except ValueError as e:
            await websocket.send(json.dumps({"error": str(e)}))


async def main():
    """Start the WebSocket server."""
    port = int(os.environ.get("PORT", 8080))
    server = GameServer()
    
    print(f"Starting Kaiser WebSocket server on port {port}")
    async with websockets.serve(server.handle_connection, "0.0.0.0", port):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
