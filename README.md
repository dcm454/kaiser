# Kaiser CLI Core

Minimal interactive core for building a Kaiser card game.

**Now supports multiplayer!** Play with 4 players online via WebSocket.

## Current model

- `Card(rank, suit, suit_special)`
- `Deck` with 32 cards:
  - Clubs and Diamonds: `7` through `A`
  - Hearts and Spades: `8` through `A`
  - Special cards: `5♥` and `3♠` (marked with `suit_special=True`)
- `Player` (4 players total, 8 cards each when dealt)
- Dealer rotation and `last_bid` tracking
- Bidding turn order + validation
- Trick-taking rules with follow-suit enforcement, trump handling, trick winner, and team trick points
- Game scoring: contracting team earns points if they make bid (≥ bid value), loses bid value if they fail; defending team always earns points won

## Run

### Single-player (local)
```bash
python3 main.py
```

### Multiplayer (online)

**1. Start the server locally:**
```bash
pip install websockets
python3 server.py
```

**2. Open the browser client (recommended):**
- Open `web/index.html` (or your hosted static URL)
- Enter game name and your name, then connect (default game name: `mygame`)
- The first person to connect becomes host and sees a setup screen
- Host assigns Seat 1-4 (Team 1/Team 2 positions) to connected people and/or virtual players, then starts setup

`client.py` multiplayer usage is now deprecated in favor of the browser client flow.

### Browser client (no installs for players)

Preferred frontend is now `web-next/` (Next.js + React + Tailwind).

Quick start:

```bash
cd web-next
npm install
echo 'NEXT_PUBLIC_WS_URL=wss://kaiser-server-997088621734.us-central1.run.app/' > .env.local
npm run dev
```

For SEO canonical URLs, robots host, and sitemap links, also set your hosted site URL:

```bash
echo 'NEXT_PUBLIC_SITE_URL=https://kaiser-caaa4.web.app' >> .env.local
```

Browser client server is fixed to:
- `wss://kaiser-server-997088621734.us-central1.run.app/`

The browser client supports the same multiplayer actions: deal, state, bidding, bid, pass, take, trick, play, rotate, restart_game.
The first connected player becomes host and configures virtual players before gameplay.
Host control note: `restart_game` resets the game to a fresh start (scores and hand state) while keeping current seat assignments.
It also includes a live scoreboard panel showing:
- Live Score (team names shown as player pairs, e.g., `Alice/Carol` vs `Bob/Dave`)
- Bid-Out Status (live win target and winner: target 52 until a successful no-trump contract, then target 64)
- This Trick (current trick card plays and trick number; shows hand completed after trick 8)
- Current Bid (value, trump, declarer)
- Click-to-play cards in `Your hand` (no card token typing needed)
- Turn display:
  - `Turn: Dealer - <name>` during idle/hand-over phases
  - `Turn: <name>` during bidding/playing phases

Virtual players available in setup:
- `Anne` (balanced)
- `Lillian` (cautious)
- `Nelson` (unpredictable)
- `Edward` (aggressive)

Note: the underlying simulation/CLI profile key for Nelson remains `chaotic` for compatibility.

Each virtual player has an in-client bio describing play style and table personality.

### Bot simulation (4 automated players)

Run offline automated matches for behavior tuning and decision inspection:

```bash
python3 bot_sim.py --hands 50 --seed 42 --profiles balanced,aggressive,cautious,chaotic --log-file bot_decisions.jsonl
```

Simulation runs up to `--hands`, but stops early when a team wins the game (bid-out winner at target 52, or 64 after a successful no-trump contract).

Available preset profiles:
- `cautious`
- `balanced`
- `aggressive`
- `chaotic`

Tune profiles with overrides (JSON list of 4 objects):

```bash
python3 bot_sim.py --profiles balanced,balanced,balanced,balanced --profile-overrides bot_overrides.json
```

Override mapping is positional (not by profile name):
- Object 1 applies to profile in `--profiles` position 1 (P1)
- Object 2 applies to position 2 (P2)
- Object 3 applies to position 3 (P3)
- Object 4 applies to position 4 (P4)

Example: with `--profiles balanced,aggressive,cautious,chaotic`, the overrides map as:
- Object 1 → `balanced`
- Object 2 → `aggressive`
- Object 3 → `cautious`
- Object 4 → `chaotic`

Example `bot_overrides.json`:

```json
[
  {"bid_aggression": 0.9, "dealer_take_threshold": 58},
  {"bid_aggression": 1.3, "trump_spend_bias": 0.9},
  {"bid_risk_buffer": 1},
  {"random_play_jitter": 0.4}
]
```

Useful no-trump tuning fields for overrides:
- `no_trump_bias`: global multiplier for the dedicated no-trump evaluator
- `no_trump_bid_margin`: how far no-trump must beat the best suit strength before a bot bids no-trump
- `no_trump_take_margin`: how far no-trump must beat the best suit strength before a dealer take becomes no-trump

Decision log output is JSONL (`bot_decisions.jsonl`) with per-decision context (`hand`, `trick`, `phase`, `player`, `action`, `payload`, `reason`) for analysis.

Analyze a decision log summary:

```bash
python3 bot_analyze.py --log-file bot_decisions.jsonl
```

Machine-readable output for dashboards/tuning pipelines:

```bash
python3 bot_analyze.py --log-file bot_decisions.jsonl --json
```

Write JSON directly to a file for CI/pipelines:

```bash
python3 bot_analyze.py --log-file bot_decisions.jsonl --json --out summary.json
```

The analyzer prints: final score/winner, action and phase counts, per-player stats, and contract success by profile.

### Deploy to Google Cloud Run

**Prerequisites:**
- Google Cloud account with billing enabled
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed

**Deploy steps:**

1. Authenticate and set project:
```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Important: run Cloud Run deploy from the repo root (`kaiser/`), not from `web-next/`.

2. Build and deploy to Cloud Run:
```bash
cd /path/to/kaiser
gcloud run deploy kaiser-server \
  --source . \
  --platform managed \
  --region us-central1 \
  --timeout=3600 \
  --set-env-vars=BOT_TURN_DELAY_SECONDS=1.2 \
  --allow-unauthenticated
```

3. Note the service URL (e.g., `https://kaiser-server-xxx.run.app`)

4. Players open your hosted browser page and connect there (game name + name, default game name `mygame`).

**Note:** Set `--timeout=3600` on deploy/update. Cloud Run WebSocket requests are capped by service timeout (max 60 minutes).

Bot pacing note: set `BOT_TURN_DELAY_SECONDS` to slow/speed virtual player actions (default `1.2`).

### Host browser client on Firebase Hosting (Next.js static export)

This gives players a URL they can open with no local software.

Important: run Firebase Hosting commands from `web-next/`.

1. Install Firebase CLI (once):
```bash
npm install -g firebase-tools
```

2. Configure project in `web-next/.firebaserc`:
```json
{
  "projects": {
    "default": "YOUR_FIREBASE_PROJECT_ID"
  }
}
```

3. Build static export:
```bash
cd web-next
npm install
npm run build
```

4. Deploy:
```bash
firebase login
firebase deploy --only hosting
```

Firebase will output your hosted URL. Players open that URL and connect to your Cloud Run WebSocket server using `wss://...`.

## CLI commands

### Single-player (main.py)
- `help` - Show help
- `rules` - Show game rules
- `state` - Show game state
- `deal` - Deal new hand
- `hands` - Show all players' hands
- `bidding` - Show bidding status
- `bid <n> <trump>` - Place bid (7-12, clubs|diamonds|hearts|spades|no-trump)
- `pass` - Pass on bidding
- `take <trump>` - Dealer takes high bid with chosen trump
- `trick` / `tricks` - Show trick state
- `play <card>` - Play a card (e.g., `10h`, `As`, `7c`)
- `rotate` - Rotate dealer
- `quit` - Exit

### Multiplayer (web client)
Browser client behavior:
- Each player only sees their own hand
- First connected player is host and runs game setup
- Host can assign teams by seat and choose which seats are people vs virtual players
- Only the active dealer can `deal` when setup is complete
- Game state is synchronized across all connected clients
- Commands are only valid for the current player's turn
- Turn clarity: all players see `Turn`, and the active player gets a highlighted `Your turn` label
- Command panel visibility by phase:
  - Idle/hand-over: only dealer sees `deal` and `rotate` (others see no command panel)
  - Bidding: only bidding controls are shown (`bid`, `pass`, `take`)
  - Playing: command controls are hidden; play is via clickable cards in `Your hand`

## Gameplay flow

1. `deal` starts a hand and enters bidding.
2. Use `bid <n> <trump>` or `pass` for the current bidder shown in `state`/`bidding`.
3. This is a single-cycle bidding round: each player acts once, dealer acts last.
4. A bid must be between 7 and 12, and higher than the current high bid.
5. If no one bids before the dealer, the dealer must bid (dealer cannot pass there).
6. On dealer turn, `take <trump>` lets dealer take the current highest number and choose trump.
7. On dealer turn, `pass` lets dealer accept the current highest bid as-is (only if a high bid exists).
8. Dealer action closes bidding and starts play.
9. Use `play <card>` for the current player.
10. Players must follow lead suit when possible.

## Scoring

At the end of each hand:
- **Contracting team** (the team that won the bid):
  - If they collected ≥ their bid value: they receive the points they won during the hand
  - If they collected < their bid value: they lose the bid amount (deducted from game score)
  - If the contract is `no-trump`, contracting-team scoring is doubled:
    - Made bid: receive `2x` points won
    - Failed bid: lose `2x` bid amount
- **Defending team** (the team that did not bid):
  - Always receives the points they won during the hand

Game score is cumulative across multiple hands.

Game winner rule:
- A team only wins when it bids out (it is the contracting team for that hand and makes its bid).
- Score target is `52` until a successful no-trump contract occurs in the game.
- After a successful no-trump contract, winning target becomes `64`.

Card token format:
- Rank + suit letter: `7c`, `10d`, `Qh`, `As`

## Project Structure

- `kaiser.py` - Core game logic (cards, deck, players, bidding, tricks, scoring)
- `main.py` - Single-player CLI interface
- `server.py` - WebSocket server for multiplayer (manages rooms and game state)
- `client.py` - Multiplayer CLI client (connects to server)
- `bot_sim.py` - 4-bot automated simulation runner with configurable profiles + decision logs
- `bot_analyze.py` - Summary analyzer for `bot_sim.py` JSONL decision logs
- `web-next/` - Next.js + React + Tailwind browser client (Firebase hosting target)
- `web/index.html` - Legacy static browser UI
- `web/app.js` - Legacy static browser client WebSocket logic
- `Dockerfile` - Container definition for Cloud Run deployment
- `requirements.txt` - Python dependencies

## Architecture

### Single-player
- Direct interaction with `KaiserGame` instance
- All players controlled from one terminal

### Multiplayer
- **Server** (`server.py`): Hosts game rooms, validates moves, broadcasts state updates
- **Client** (`client.py`): Connects via WebSocket, displays updates, sends commands
- Each player runs their own client and sees only their hand
- Game state synchronized in real-time across all clients