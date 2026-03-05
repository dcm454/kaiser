#!/usr/bin/env python3
"""
WebSocket client CLI for multiplayer Kaiser card game.
"""
import asyncio
import json
import sys
import websockets
from websockets.client import WebSocketClientProtocol


HELP_TEXT = """
Commands:
    help                Show this help
    state               Show current game core state
    deal                Build + shuffle deck and deal 8 cards to each player (any player can deal)
    hand                Show your hand
    bidding             Show bidding history and next bidder
    bid <n> <trump>     Bid (trump: clubs|diamonds|hearts|spades|no-trump)
    pass                Pass for current bidder
    take <trump>        Dealer takes current highest number with chosen trump
    trick               Show trick/contract/team points state
    play <card>         Play card (example: 10h, As, 7c)
    rotate              Rotate dealer to next player
    quit                Exit
""".strip()


class KaiserClient:
    """WebSocket client for Kaiser game."""
    
    def __init__(self, server_url: str, room_id: str, player_name: str):
        self.server_url = server_url
        self.room_id = room_id
        self.player_name = player_name
        self.websocket: WebSocketClientProtocol = None
        self.player_index: int = None
        self.running = True
    
    async def connect(self):
        """Connect to the server and join a room."""
        try:
            self.websocket = await websockets.connect(self.server_url)
            
            # Send join message
            await self.websocket.send(json.dumps({
                "action": "join",
                "room_id": self.room_id,
                "name": self.player_name
            }))
            
            # Wait for join confirmation
            response = await self.websocket.recv()
            data = json.loads(response)
            
            if "error" in data:
                print(f"Error joining room: {data['error']}")
                return False
            
            if data.get("type") == "joined":
                self.player_index = data["player_index"]
                print(f"\n✓ Joined room '{self.room_id}' as {self.player_name} (Player {self.player_index + 1})")
                print(f"Players in room: {data['players_count']}/4")
                if data['players_count'] < 4:
                    print("Waiting for more players...")
                else:
                    print("Room is full! Ready to play.")
                return True
            
            return False
        
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    async def handle_messages(self):
        """Listen for messages from the server."""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self.process_message(data)
        except websockets.exceptions.ConnectionClosed:
            print("\n✗ Connection to server closed")
            self.running = False
        except Exception as e:
            print(f"\n✗ Error: {e}")
            self.running = False
    
    async def process_message(self, data: dict):
        """Process a message from the server."""
        msg_type = data.get("type")

        def show_turn_prompt(payload: dict) -> None:
            if "current_player_index" not in payload:
                return
            current_index = payload["current_player_index"]
            current_name = payload.get("current_player_name", f"Player {current_index + 1}")
            context = payload.get("turn_context")
            label = "Current bidder" if context == "bidding" else "Current player"
            print(f"\n{label}: {current_name}")
            if self.player_index == current_index:
                print(">>> Your turn")
        
        if msg_type == "player_joined":
            print(f"\n✓ {data['player_name']} joined (Player {data['player_index'] + 1})")
            print(f"Players: {data['players_count']}/4")
            if data.get("ready"):
                print("Room is full! Ready to play. Type 'deal' to start.")
        
        elif msg_type == "player_left":
            print(f"\n✗ {data['player_name']} left")
            print(f"Players: {data['players_count']}/4")
        
        elif msg_type == "game_update":
            print(f"\n{data['message']}")
            if "bidding" in data:
                print(f"\n{data['bidding']}")
            show_turn_prompt(data)
        
        elif msg_type == "phase_change":
            print(f"\n{data['message']}")
            if "trick" in data:
                print(f"\n{data['trick']}")
            show_turn_prompt(data)
        
        elif msg_type == "hand_complete":
            print(f"\n{data['message']}")
            print(f"\n{data['trick']}")
            print("\nType 'rotate' to move dealer, then 'deal' for next hand.")
        
        elif msg_type == "hand":
            print(f"\nYour hand: {data['cards']}")
        
        elif msg_type == "state":
            print(f"\n{data['content']}")
            show_turn_prompt(data)
        
        elif msg_type == "bidding":
            print(f"\n{data['content']}")
            show_turn_prompt(data)
        
        elif msg_type == "trick":
            print(f"\n{data['content']}")
            show_turn_prompt(data)
        
        elif msg_type == "error" or "error" in data:
            print(f"\n✗ Error: {data.get('error', 'Unknown error')}")
    
    async def send_command(self, command: str):
        """Send a command to the server."""
        parts = command.strip().split()
        if not parts:
            return
        
        cmd = parts[0].lower()
        
        if cmd in ("quit", "exit"):
            print("bye")
            self.running = False
            return
        
        if cmd == "help":
            print(HELP_TEXT)
            return
        
        # Build message based on command
        message = None
        
        if cmd == "state":
            message = {"action": "state"}
        
        elif cmd == "deal":
            message = {"action": "deal"}
        
        elif cmd in ("hand", "hands"):
            message = {"action": "hands"}
        
        elif cmd == "bidding":
            message = {"action": "bidding"}
        
        elif cmd == "bid":
            if len(parts) != 3:
                print("Usage: bid <n> <trump>")
                return
            try:
                value = int(parts[1])
            except ValueError:
                print("Bid value must be an integer")
                return
            trump = parts[2].lower()
            message = {"action": "bid", "value": value, "trump": trump}
        
        elif cmd == "pass":
            message = {"action": "pass"}
        
        elif cmd == "take":
            if len(parts) != 2:
                print("Usage: take <trump>")
                return
            trump = parts[1].lower()
            message = {"action": "take", "trump": trump}
        
        elif cmd in ("trick", "tricks"):
            message = {"action": "trick"}
        
        elif cmd == "play":
            if len(parts) != 2:
                print("Usage: play <card>")
                return
            message = {"action": "play", "card": parts[1]}
        
        elif cmd == "rotate":
            message = {"action": "rotate"}
        
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'help' for available commands.")
            return
        
        if message:
            try:
                await self.websocket.send(json.dumps(message))
            except Exception as e:
                print(f"Error sending command: {e}")
                self.running = False
    
    async def input_loop(self):
        """Handle user input."""
        while self.running:
            try:
                # Use asyncio to run blocking input in executor
                command = await asyncio.get_event_loop().run_in_executor(
                    None, input, "\nkaiser> "
                )
                await self.send_command(command)
            except (EOFError, KeyboardInterrupt):
                print("\nbye")
                self.running = False
                break
            except Exception as e:
                if self.running:
                    print(f"Error: {e}")
    
    async def run(self):
        """Run the client."""
        if not await self.connect():
            return
        
        # Run message handler and input loop concurrently
        await asyncio.gather(
            self.handle_messages(),
            self.input_loop()
        )
        
        if self.websocket:
            await self.websocket.close()


async def main():
    """Main entry point."""
    print("Kaiser Multiplayer Client")
    print("=" * 40)
    
    # Get connection details
    if len(sys.argv) > 1:
        server_url = sys.argv[1]
    else:
        server_url = input("Server URL (default: ws://localhost:8080): ").strip()
        if not server_url:
            server_url = "ws://localhost:8080"
    
    room_id = input("Room ID (default: default): ").strip()
    if not room_id:
        room_id = "default"
    
    player_name = input("Your name: ").strip()
    if not player_name:
        player_name = f"Player{id(None) % 100}"
    
    print(f"\nConnecting to {server_url}...")
    
    client = KaiserClient(server_url, room_id, player_name)
    await client.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye")
