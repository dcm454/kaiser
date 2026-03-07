"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type SetupOption = { id: string; name: string; seat?: number; profile?: string; bio?: string };
type SetupState = { human_options?: SetupOption[]; bot_options?: SetupOption[]; current_assignments?: (string | null)[] };
type RoomPayload = {
  room?: {
    ready?: boolean;
    setup_complete?: boolean;
    host_player_index?: number;
    available_virtual_players?: SetupOption[];
    setup?: SetupState;
  };
};

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "wss://kaiser-server-997088621734.us-central1.run.app/";

function extractBidProgressionLines(biddingSummary: string): string[] {
  return biddingSummary
    .split("\n")
    .map((line) => line.trim())
    .filter((line) =>
      line.length > 0 &&
      line !== "Bidding" &&
      line !== "No bids yet" &&
      !line.startsWith("Highest:") &&
      !line.startsWith("Next bidder:") &&
      !line.startsWith("Bids made:")
    );
}

function EightCardHandIcon() {
  return (
    <svg
      viewBox="0 0 128 96"
      aria-hidden="true"
      className="h-10 w-12 text-emerald-800"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect x="8" y="28" width="20" height="40" rx="4" transform="rotate(-24 8 28)" fill="currentColor" opacity="0.22" />
      <rect x="17" y="22" width="20" height="42" rx="4" transform="rotate(-18 17 22)" fill="white" stroke="currentColor" strokeWidth="2" />

      <rect x="27" y="17" width="20" height="43" rx="4" transform="rotate(-12 27 17)" fill="white" stroke="currentColor" strokeWidth="2" />
      <rect x="39" y="13" width="20" height="44" rx="4" transform="rotate(-7 39 13)" fill="white" stroke="currentColor" strokeWidth="2" />

      <rect x="51" y="11" width="20" height="45" rx="4" transform="rotate(-3 51 11)" fill="white" stroke="currentColor" strokeWidth="2" />
      <rect x="63" y="10" width="20" height="45" rx="4" fill="white" stroke="currentColor" strokeWidth="2" />

      <rect x="75" y="11" width="20" height="45" rx="4" transform="rotate(3 75 11)" fill="white" stroke="currentColor" strokeWidth="2" />
      <rect x="87" y="13" width="20" height="44" rx="4" transform="rotate(7 87 13)" fill="white" stroke="currentColor" strokeWidth="2" />

      <rect x="99" y="17" width="20" height="43" rx="4" transform="rotate(12 99 17)" fill="white" stroke="currentColor" strokeWidth="2" />
      <text x="64" y="72" textAnchor="middle" fontSize="16" fontWeight="700" fill="currentColor">8</text>
    </svg>
  );
}

export default function Page() {
  const [gameName, setGameName] = useState("mygame");
  const [playerName, setPlayerName] = useState("");
  const [connected, setConnected] = useState(false);
  const [isHost, setIsHost] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [roomReady, setRoomReady] = useState(false);
  const [currentPhase, setCurrentPhase] = useState("idle");
  const [dealerIndex, setDealerIndex] = useState<number | null>(null);
  const [dealerName, setDealerName] = useState("Unknown");
  const [playerIndex, setPlayerIndex] = useState<number | null>(null);
  const [turnName, setTurnName] = useState("Unknown");
  const [turnContext, setTurnContext] = useState<string | null>(null);
  const [scoreSummary, setScoreSummary] = useState("-");
  const [sessionWinsSummary, setSessionWinsSummary] = useState("-");
  const [winningStatus, setWinningStatus] = useState("Target 52 (no no-trump bids yet)");
  const [newGameStatus, setNewGameStatus] = useState("No new game prompt yet.");
  const [startNewGameVisible, setStartNewGameVisible] = useState(false);
  const [startNewGameReady, setStartNewGameReady] = useState(false);
  const [startNewGameVoted, setStartNewGameVoted] = useState(false);
  const [thisHand, setThisHand] = useState("Team 1:0 tr (0 pts)\nTeam 2:0 tr (0 pts)");
  const [trickNumber, setTrickNumber] = useState(1);
  const [trickPlayHistory, setTrickPlayHistory] = useState<string[]>([]);
  const [trickCompleted, setTrickCompleted] = useState(false);
  const [bidText, setBidText] = useState("No bid yet");
  const [bidProgression, setBidProgression] = useState<string[]>([]);
  const [winningBidPatterns, setWinningBidPatterns] = useState<string[]>([]);
  const [cards, setCards] = useState<string[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [virtualPlayers, setVirtualPlayers] = useState<SetupOption[]>([]);
  const [setupInfo, setSetupInfo] = useState<SetupState | null>(null);
  const [setupAssignments, setSetupAssignments] = useState<(string | null)[]>([null, null, null, null]);
  const [bidValue, setBidValue] = useState(7);
  const [contractTrump, setContractTrump] = useState("clubs");
  const [helpOpen, setHelpOpen] = useState(false);
  const [joinRejection, setJoinRejection] = useState<string | null>(null);
  const [handActionError, setHandActionError] = useState<string | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const trickCompletedRef = useRef(false);

  const isMyTurn = useMemo(() => {
    if (playerIndex === null || !ws) return false;
    return turnContext === "bidding" || turnContext === "choosing_trump" || turnContext === "playing";
  }, [playerIndex, ws, turnContext]);

  const appendLog = (message: string) => {
    const line = `[${new Date().toLocaleTimeString()}] ${message}`;
    setLog((prev: string[]) => [line, ...prev]);
  };

  const send = (payload: Record<string, unknown>) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      appendLog("Not connected.");
      return;
    }
    ws.send(JSON.stringify(payload));
  };

  const isHandValidationError = (message: string) => {
    const lowered = message.toLowerCase();
    return (
      lowered.includes("must follow suit") ||
      lowered.includes("not your turn to play") ||
      lowered.includes("play phase is not active") ||
      lowered.includes("does not have card")
    );
  };

  const applyRoomPayload = (data: RoomPayload, effectivePlayerIndex: number | null, effectiveIsHost: boolean) => {
    if (!data.room) return;
    setRoomReady(data.room.ready === true);

    if (typeof data.room.host_player_index === "number" && effectivePlayerIndex !== null) {
      const computedHost = data.room.host_player_index === effectivePlayerIndex;
      setIsHost(computedHost);
      effectiveIsHost = computedHost;
    }

    if (typeof data.room.setup_complete === "boolean") {
      setSetupRequired(!data.room.setup_complete && effectiveIsHost);
    }
    if (data.room.available_virtual_players) {
      setVirtualPlayers(data.room.available_virtual_players);
    }
    if (data.room.setup) {
      setSetupInfo(data.room.setup);
      if (Array.isArray(data.room.setup.current_assignments) && data.room.setup.current_assignments.length === 4) {
        setSetupAssignments(data.room.setup.current_assignments);
      }
    }
  };

  const assignmentLabel = (assignment: string | null) => {
    if (!assignment) return "Unassigned";
    const human = (setupInfo?.human_options ?? []).find((h) => h.id === assignment);
    if (human) return `${human.name} (human)`;
    const bot = (setupInfo?.bot_options ?? []).find((b) => b.id === assignment);
    if (bot) return `${bot.name} (${displayProfileLabel(bot.profile)})`;
    return assignment;
  };

  const displayProfileLabel = (profile?: string) => {
    if (!profile) return "unknown";
    if (profile === "chaotic") return "unpredictable";
    return profile;
  };

  const assignBotToNextSeat = (botId: string) => {
    if (!isHost || !setupRequired) return;
    const next = [...setupAssignments];

    const existingSeat = next.findIndex((value) => value === botId);
    if (existingSeat >= 0) {
      next[existingSeat] = null;
      setSetupAssignments(next);
      return;
    }

    const targetSeat = next.findIndex((value) => value === null);
    if (targetSeat < 0) {
      appendLog("All seats already assigned. Change a seat dropdown first.");
      return;
    }
    next[targetSeat] = botId;
    setSetupAssignments(next);
  };

  const renderScoreboard = (data: Record<string, any>) => {
    const scoreboard = data.scoreboard;
    if (!scoreboard) return;

    const team0Label = scoreboard.team_labels?.team0 ?? "Team 1";
    const team1Label = scoreboard.team_labels?.team1 ?? "Team 2";
    const liveScore0 = scoreboard.live_game_score?.team0 ?? scoreboard.game_score?.team0 ?? 0;
    const liveScore1 = scoreboard.live_game_score?.team1 ?? scoreboard.game_score?.team1 ?? 0;
    setScoreSummary(`${team0Label} (${liveScore0}), ${team1Label} (${liveScore1})`);

    const sessionWins0 = scoreboard.session_wins?.team0 ?? 0;
    const sessionWins1 = scoreboard.session_wins?.team1 ?? 0;
    setSessionWinsSummary(`${team0Label} ${sessionWins0}, ${team1Label} ${sessionWins1}`);

    const winning = scoreboard.winning ?? {};
    const target = winning.target ?? 52;
    const noTrumpSeen = winning.no_trump_bid_seen === true;
    const winnerTeamLabel = winning.winner_team_label;
    const base = `Target ${target} (${noTrumpSeen ? "no-trump bid seen" : "no no-trump bids yet"})`;
    setWinningStatus(winnerTeamLabel ? `${base} | Winner: ${winnerTeamLabel} (bid out)` : `${base} | No winner yet`);

    const newGame = scoreboard.new_game ?? {};
    const votes = newGame.votes ?? 0;
    const requiredVotes = newGame.required_votes ?? 0;
    const available = newGame.available === true;
    const votedPlayers: number[] = Array.isArray(newGame.voted_players) ? newGame.voted_players : [];
    const iVoted = playerIndex !== null && votedPlayers.includes(playerIndex);
    const timeoutRefreshedAt = typeof newGame.timeout_refreshed_at === "number"
      ? new Date(newGame.timeout_refreshed_at * 1000).toLocaleTimeString()
      : null;
    setStartNewGameVisible(available);
    setStartNewGameReady(newGame.ready_to_start === true);
    setStartNewGameVoted(iVoted);
    if (available) {
      setNewGameStatus(`Start New Game: ${votes}/${requiredVotes} players ready${timeoutRefreshedAt ? ` | timeout refreshed ${timeoutRefreshedAt}` : ""}`);
    } else {
      setNewGameStatus("No new game prompt yet.");
    }

    setThisHand(`${team0Label}:${scoreboard.hand?.tricks?.team0 ?? 0} tr (${scoreboard.hand?.points?.team0 ?? 0} pts)\n${team1Label}:${scoreboard.hand?.tricks?.team1 ?? 0} tr (${scoreboard.hand?.points?.team1 ?? 0} pts)`);

    const nextTrickNumber = scoreboard.hand?.trick_number ?? 1;
    setTrickNumber(nextTrickNumber);

    if (typeof scoreboard.dealer_name === "string" && scoreboard.dealer_name.length > 0) {
      setDealerName(scoreboard.dealer_name);
    }

    const bid = scoreboard.bid;
    if (!bid) {
      setBidText("No bid yet");
      setWinningBidPatterns([]);
    } else {
      if (bid.trump === "hidden") {
        setBidText(`${bid.value} by ${bid.declarer}`);
      } else {
        setBidText(`${bid.value} ${bid.trump} by ${bid.declarer}`);
      }
      setWinningBidPatterns([
        `${bid.declarer}: ${bid.value} ${bid.trump}`,
        `${bid.declarer}: take ${bid.value} ${bid.trump}`,
      ]);
    }

    setCurrentPhase(scoreboard.phase ?? "idle");
    if (typeof scoreboard.dealer_index === "number") setDealerIndex(scoreboard.dealer_index);
  };

  useEffect(() => {
    return () => {
      ws?.close();
    };
  }, [ws]);

  useEffect(() => {
    if (!helpOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setHelpOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [helpOpen]);

  const connect = () => {
    setJoinRejection(null);
    setHandActionError(null);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close();
      setWs(null);
      setConnected(false);
      return;
    }

    const socket = new WebSocket(WS_URL);
    socket.onopen = () => {
      setConnected(true);
      setJoinRejection(null);
      appendLog(`Connected to ${WS_URL}`);
      const name = playerName.trim() || `Player-${Math.floor(Math.random() * 1000)}`;
      setPlayerName(name);
      socket.send(JSON.stringify({ action: "join", room_id: gameName.trim() || "mygame", name }));
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      let nextPlayerIndex = playerIndex;
      let nextIsHost = isHost;
      if (data.error) {
        const errorText = typeof data.error === "string" ? data.error : String(data.error);
        const lowered = errorText.toLowerCase();
        if (lowered.includes("room is full")) {
          setJoinRejection("That game is full (4 players already connected). Try a new game name to start or join another table.");
          setHandActionError(null);
        } else if (isHandValidationError(errorText)) {
          setJoinRejection(null);
          setHandActionError(errorText);
        } else {
          setJoinRejection(errorText);
        }
        appendLog(`Error: ${errorText}`);
        return;
      }

      if (typeof data.current_player_name === "string") {
        setTurnName(data.turn_context === "idle" ? `Dealer - ${data.current_player_name}` : data.current_player_name);
      }
      if (data.turn_context) {
        setTurnContext(data.turn_context);
        // Keep phase chip in sync even when payloads omit scoreboard.
        if (data.turn_context === "playing" || data.turn_context === "bidding") {
          setCurrentPhase(data.turn_context);
        }
      }

      switch (data.type) {
        case "joined":
          nextPlayerIndex = data.player_index;
          nextIsHost = data.is_host === true;
          setPlayerIndex(data.player_index);
          setIsHost(nextIsHost);
          setSetupRequired(data.setup_required === true);
          setJoinRejection(null);
          appendLog(`Joined game '${data.room_id}' as ${data.player_name} (Seat ${data.player_index + 1}).`);
          break;
        case "player_joined":
          appendLog(`${data.player_name} joined (Seat ${data.player_index + 1}).`);
          break;
        case "player_left":
          appendLog(`${data.player_name} left.`);
          break;
        case "setup_complete":
          setSetupRequired(false);
          appendLog(data.message ?? "Setup complete.");
          break;
        case "seat_assigned":
          if (typeof data.player_index === "number") {
            nextPlayerIndex = data.player_index;
            setPlayerIndex(data.player_index);
          }
          nextIsHost = data.is_host === true;
          setIsHost(nextIsHost);
          setSetupRequired(data.setup_required === true);
          appendLog(`Seat assignment updated. You are now Seat ${data.player_index + 1}.`);
          break;
        case "hand":
          setCards((data.cards || "").trim() ? data.cards.trim().split(/\s+/) : []);
          break;
        case "new_game_started":
          setBidProgression([]);
          setTrickPlayHistory([]);
          setTrickNumber(1);
          setStartNewGameVisible(false);
          setStartNewGameReady(false);
          setStartNewGameVoted(false);
          trickCompletedRef.current = false;
          setTrickCompleted(false);
          break;
        default:
          if (data.message) appendLog(data.message);
          if (data.content) appendLog(data.content);
      }

      if (typeof data.message === "string") {
        if (data.message.startsWith("Dealt 8 cards") || data.message.startsWith("Starting next hand") || data.message.startsWith("Game restarted")) {
          setBidProgression([]);
          setTrickPlayHistory([]);
          setTrickNumber((prev) => prev + 1);
          trickCompletedRef.current = false;
          setTrickCompleted(false);
        }
        if (data.message.includes(" played ")) {
          setHandActionError(null);
          const playedLine = data.message.split("|")[0].trim();
          if (data.message.includes("| Trick won by ")) {
            setTrickPlayHistory((prev) => [...prev, playedLine]);
            trickCompletedRef.current = true;
            setTrickCompleted(true);
          } else {
            if (trickCompletedRef.current) {
              setTrickPlayHistory([playedLine]);
            } else {
              setTrickPlayHistory((prev) => [...prev, playedLine]);
            }
            trickCompletedRef.current = false;
            setTrickCompleted(false);
          }
        }
      }

      if (typeof data.bidding === "string") {
        setBidProgression(extractBidProgressionLines(data.bidding));
      }

      applyRoomPayload(data, nextPlayerIndex, nextIsHost);
      renderScoreboard(data);

      if (data.bot_action && typeof data.bot_action.bot_name === "string") {
        const botName = data.bot_action.bot_name;
        const action = data.bot_action.action ?? "action";
        const reason = typeof data.bot_action.reason === "string" ? data.bot_action.reason : "";
        const debug = data.bot_action.debug ?? {};

        const parts: string[] = [`BOT ${botName}: ${action}`];
        if (debug.bid_strength_best !== undefined && debug.bid_strength_best_trump) {
          parts.push(`strength=${debug.bid_strength_best} (${debug.bid_strength_best_trump})`);
        }
        if (Array.isArray(debug.hand_cards) && debug.hand_cards.length > 0) {
          parts.push(`hand=${debug.hand_cards.join(" ")}`);
        }
        if (typeof debug.play_reason === "string" && debug.play_reason.length > 0) {
          parts.push(`play_reason=${debug.play_reason}`);
        } else if (reason.length > 0) {
          parts.push(`reason=${reason}`);
        }
        appendLog(parts.join(" | "));
      }
    };

    socket.onclose = () => {
      setConnected(false);
      setWs(null);
      appendLog("Disconnected.");
    };

    socket.onerror = () => appendLog("WebSocket error.");
    setWs(socket);
  };

  const suits = ["clubs", "diamonds", "hearts", "spades", "no-trump"];

  const thisTrickText = useMemo(() => {
    const displayTrickNumber = trickCompleted && trickNumber > 1 ? trickNumber - 1 : trickNumber;
    const header = trickCompleted ? `Trick Number: ${displayTrickNumber} (completed)` : `Trick Number: ${displayTrickNumber}`;
    const lines = [header];
    if (trickPlayHistory.length === 0) {
      lines.push(currentPhase === "hand_over" ? "No active trick" : "No cards played in this trick yet");
    } else {
      lines.push(...trickPlayHistory);
    }
    return lines.join("\n");
  }, [trickNumber, trickPlayHistory, currentPhase, trickCompleted]);

  const bidCardText = useMemo(() => {
    if (bidProgression.length > 0) return bidProgression;
    return ["No bids yet"];
  }, [bidProgression]);

  const isWinningBidLine = (line: string) => {
    const normalized = line.toLowerCase();
    return winningBidPatterns.some((pattern) => normalized.includes(pattern.toLowerCase()));
  };

  const sendSetup = () => {
    const values = setupAssignments.filter((v: string | null): v is string => typeof v === "string" && v.length > 0);
    if (values.length !== 4 || new Set(values).size !== 4) {
      appendLog("Setup error: assign all 4 unique seats.");
      return;
    }
    send({ action: "setup_game", seat_assignments: values });
  };

  const seatDisplay = ["Seat 1 (Team 1)", "Seat 2 (Team 2)", "Seat 3 (Team 1)", "Seat 4 (Team 2)"];
  const isMyBidTurn = turnContext === "bidding";
  const isMyTrumpTurn = turnContext === "choosing_trump";
  const isMyPlayTurn = turnContext === "playing";
  const phaseLabel = currentPhase.replaceAll("_", " ");

  const phaseChipClasses = () => {
    if (currentPhase === "playing") return "chip border-emerald-300 bg-emerald-100 text-emerald-900";
    if (currentPhase === "bidding") return "chip border-lime-300 bg-lime-100 text-lime-900";
    if (currentPhase === "hand_over") return "chip border-teal-300 bg-teal-100 text-teal-900";
    return "chip border-emerald-200 bg-emerald-50 text-emerald-900";
  };

  const cardTone = (card: string) => {
    const suit = card.replace("*", "").slice(-1);
    if (suit === "♥" || suit === "♦") return "border-emerald-300 bg-emerald-50 text-emerald-900";
    if (suit === "♣" || suit === "♠") return "border-lime-300 bg-lime-50 text-lime-900";
    return "border-emerald-200 bg-white text-emerald-900";
  };

  return (
    <main className="relative mx-auto max-w-7xl px-4 pb-8 pt-6 sm:px-6 lg:px-8">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-48 bg-gradient-to-b from-emerald-300/35 to-transparent" />
      <div className="space-y-4">
        <section className="panel animate-enter">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-soft">Realtime Table</p>
              <h1 className="mt-1 flex items-center gap-3 text-2xl font-bold tracking-tight sm:text-3xl">
                <EightCardHandIcon />
                <span>Play Kaiser</span>
              </h1>
              <p className="mt-1 text-sm text-soft">Fast multiplayer rounds with live bids, play-by-play trick state, and host setup controls.</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="chip border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200"
                onClick={() => setHelpOpen(true)}
                aria-label="Open game help"
              >
                Playing Guide
              </button>
              <span className={connected ? "chip border-emerald-300 bg-emerald-100 text-emerald-900" : "chip border-amber-300 bg-amber-100 text-amber-900"}>
                {connected ? "Connected" : "Disconnected"}
              </span>
              {connected && (
                <button className="chip border-rose-300 bg-rose-100 text-rose-900 transition hover:bg-rose-200" onClick={connect}>Disconnect</button>
              )}
            </div>
          </div>

          {!connected && (
            <div className="mt-4 grid gap-3 md:grid-cols-[1fr,1fr,auto]">
              <input className="field" value={gameName} onChange={(e) => setGameName(e.target.value)} placeholder="Game name" />
              <input className="field" value={playerName} onChange={(e) => setPlayerName(e.target.value)} placeholder="Your name" />
              <button className="btn-primary" onClick={connect}>Connect</button>
            </div>
          )}

          {joinRejection && (
            <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
              {joinRejection}
            </div>
          )}
        </section>

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[0.6fr,1.2fr,2fr]">
          <article className="info-card animate-enter py-2.5">
            <p className="text-xs uppercase tracking-[0.2em] text-soft">Turn</p>
            <p className="mt-1.5 text-base font-semibold">{turnName}</p>
          </article>
          <article className="info-card animate-enter py-2.5">
            <p className="text-xs uppercase tracking-[0.2em] text-soft">Phase</p>
            <p className="mt-1.5"><span className={phaseChipClasses()}>{phaseLabel}</span></p>
            <div className="mt-2.5 flex flex-wrap gap-2">
              {isHost && roomReady && (
                <button className="chip border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200" onClick={() => send({ action: "restart_game" })}>Reset Game</button>
              )}
              {roomReady && currentPhase === "hand_over" && (
                <button
                  className="chip border-emerald-700 bg-emerald-700 text-emerald-50 transition hover:bg-emerald-800"
                  onClick={() => {
                    // Reflect next-hand transition immediately in the trick panel.
                    setTrickPlayHistory([]);
                    setTrickNumber((prev) => prev + 1);
                    trickCompletedRef.current = false;
                    setTrickCompleted(false);
                    send({ action: "next_hand" });
                  }}
                >
                  Start Next Hand
                </button>
              )}
              {roomReady && startNewGameVisible && (
                <button
                  className="chip border-lime-700 bg-lime-700 text-lime-50 transition hover:bg-lime-800 disabled:opacity-60"
                  onClick={() => send({ action: "start_new_game" })}
                  disabled={startNewGameVoted && !startNewGameReady}
                >
                  {startNewGameVoted && !startNewGameReady ? "Waiting for Players" : "Start New Game"}
                </button>
              )}
            </div>
          </article>
          <article className="info-card animate-enter py-2.5 sm:col-span-2 xl:col-span-1">
            <p className="text-xs uppercase tracking-[0.2em] text-soft">Live Score</p>
            <p className="mt-1.5 text-base font-semibold">{scoreSummary}</p>
            <p className="mt-1 text-sm text-soft">Session Wins: {sessionWinsSummary}</p>
            <p className="mt-1 text-sm text-soft">{winningStatus}</p>
            <p className="mt-1 text-sm text-soft">{newGameStatus}</p>
          </article>
        </section>

        {!roomReady && (
          <section className="panel animate-enter space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Game Setup</h2>
              <span className="text-sm text-soft">
                {isHost ? (setupRequired ? "You are host. Assign seats and start setup." : "Setup complete.") : "Waiting for host setup..."}
              </span>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {seatDisplay.map((label, seat) => (
                <article key={label} className="info-card space-y-2">
                  <p className="text-sm font-semibold">{label}</p>
                  {isHost && setupRequired ? (
                    <select
                      className="field"
                      value={setupAssignments[seat] ?? ""}
                      onChange={(e) => {
                        const next = [...setupAssignments];
                        next[seat] = e.target.value;
                        setSetupAssignments(next);
                      }}
                    >
                      <option value="">Select...</option>
                      {(setupInfo?.human_options ?? []).map((h) => (
                        <option key={h.id} value={h.id}>{h.name} (human)</option>
                      ))}
                      {(setupInfo?.bot_options ?? []).map((b) => (
                        <option key={b.id} value={b.id}>{b.name} (AI)</option>
                      ))}
                    </select>
                  ) : (
                    <p className="text-sm text-soft">{assignmentLabel(setupAssignments[seat])}</p>
                  )}
                </article>
              ))}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {virtualPlayers.map((vp) => (
                <button
                  key={vp.id ?? vp.name}
                  type="button"
                  onClick={() => vp.id && assignBotToNextSeat(vp.id)}
                  className="info-card text-left transition hover:bg-emerald-50 disabled:opacity-60"
                  disabled={!isHost || !setupRequired || !vp.id}
                >
                  <p className="text-sm font-semibold">{vp.name} ({displayProfileLabel(vp.profile)})</p>
                  <p className="mt-1 text-sm text-soft">{vp.bio}</p>
                </button>
              ))}
            </div>

            {isHost && setupRequired && (
              <button className="btn-primary" onClick={sendSetup}>Start Game with Selected Seats</button>
            )}
          </section>
        )}

        <section className="grid gap-4 xl:grid-cols-[1.55fr,1fr]">
          <div className="space-y-4">
            <section className="panel animate-enter">
              <h2 className="mb-3 text-lg font-semibold">Round Snapshot</h2>
              <div className="grid gap-3 md:grid-cols-3">
                <pre className="mono-block whitespace-pre-wrap"><strong>This Hand</strong>{"\n"}Dealer: {dealerName}{"\n"}{thisHand}</pre>
                <pre className="mono-block whitespace-pre-wrap"><strong>This Trick</strong>{"\n"}{thisTrickText}</pre>
                <div className="mono-block whitespace-pre-wrap">
                  <strong>Bid</strong>
                  <div className="mt-2 space-y-1">
                    {bidCardText.map((line, index) => (
                      <div
                        key={`${line}-${index}`}
                        className={isWinningBidLine(line) ? "font-semibold text-emerald-700" : undefined}
                      >
                        {line}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            {roomReady && (
              <section className="panel animate-enter space-y-4">
                <div className="flex flex-wrap gap-2">
                  {currentPhase === "idle" && dealerIndex === playerIndex && (
                    <>
                      <button className="btn-primary" onClick={() => send({ action: "deal" })}>Deal</button>
                      <button className="btn-secondary" onClick={() => send({ action: "rotate" })}>Rotate</button>
                    </>
                  )}
                </div>

                {currentPhase === "bidding" && (
                  <div className="grid gap-3 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3 md:grid-cols-2 xl:grid-cols-3">
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-[0.2em] text-soft">Bid Value</p>
                      <select value={String(bidValue)} onChange={(e) => setBidValue(Number(e.target.value))} className="field">
                        {[7, 8, 9, 10, 11, 12].map((n) => (
                          <option key={n} value={n}>{n}</option>
                        ))}
                      </select>
                    </div>

                    <div className="flex flex-wrap gap-2 md:col-span-2 xl:col-span-3">
                      <button disabled={!isMyBidTurn} className="btn-primary" onClick={() => send({ action: "bid", value: bidValue })}>Bid</button>
                      <button disabled={!isMyBidTurn} className="btn-secondary" onClick={() => send({ action: "pass" })}>Pass</button>
                      <button disabled={!isMyBidTurn} className="btn-secondary" onClick={() => send({ action: "take" })}>Take</button>
                    </div>
                  </div>
                )}

                {currentPhase === "choosing_trump" && (
                  <div className="grid gap-3 rounded-xl border border-lime-200 bg-lime-50/70 p-3 md:grid-cols-2 xl:grid-cols-3">
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-[0.2em] text-soft">Select Trump</p>
                      <select value={contractTrump} onChange={(e) => setContractTrump(e.target.value)} className="field">
                        {suits.map((s) => <option key={s}>{s}</option>)}
                      </select>
                    </div>
                    <div className="flex flex-wrap gap-2 md:col-span-2 xl:col-span-3">
                      <button disabled={!isMyTrumpTurn} className="btn-primary" onClick={() => send({ action: "choose_trump", trump: contractTrump })}>Confirm Trump</button>
                    </div>
                  </div>
                )}

                <div>
                  <h3 className="mb-2 text-base font-semibold">Your Hand</h3>
                  {handActionError && (
                    <div className="mb-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
                      {handActionError}
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                    {cards.map((card) => (
                      <button
                        key={card}
                        disabled={!isMyPlayTurn}
                        className={`rounded-xl border px-3 py-2 text-center text-sm font-semibold transition hover:-translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-50 ${cardTone(card)}`}
                        onClick={() => {
                          const cleaned = card.replace("*", "");
                          const suit = cleaned.slice(-1);
                          const rank = cleaned.slice(0, -1);
                          const map: Record<string, string> = { "♣": "c", "♦": "d", "♥": "h", "♠": "s" };
                          const token = `${rank}${map[suit] ?? ""}`;
                          if (token) send({ action: "play", card: token });
                        }}
                      >
                        {card}
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            )}
          </div>

          <section className="panel animate-enter">
            <h2 className="mb-3 text-lg font-semibold">Game Log</h2>
            <pre className="mono-block max-h-[24rem] overflow-auto whitespace-pre-wrap">{log.join("\n")}</pre>
          </section>
        </section>
      </div>

      {helpOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-emerald-950/45 p-4" onClick={() => setHelpOpen(false)}>
          <section
            className="w-full max-w-3xl rounded-2xl border border-emerald-200 bg-white p-5 text-emerald-950 shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-modal-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id="help-modal-title" className="text-xl font-semibold">Kaiser Paying Guide</h2>
                <p className="mt-1 text-sm text-emerald-800">Quick reference for gameplay and how to use this interface.</p>
              </div>
              <button className="btn-secondary" onClick={() => setHelpOpen(false)}>Close</button>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <article className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
                <h3 className="font-semibold">Rules Summary</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
                  <li>Kaiser is a 4-player partnership trick-taking game (Seat 1 and 3 vs Seat 2 and 4).</li>
                  <li>Each hand has bidding, then trick play.</li>
                  <li>In bidding, players can bid, pass, and the dealer can take with a trump suit/no-trump.</li>
                  <li>The highest bidder becomes declarer and sets the contract.</li>
                  <li>In play, follow suit when possible. Highest card of lead suit wins unless trump is played.</li>
                  <li>There are two special cards: 5 of hearts and 3 of spades. The 5H earns additional 5 points. 3S deducts 3 points.</li>
                  <li>Hand and game scoring is shown live in the scoreboard panel.</li>
                </ul>
              </article>

              <article className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
                <h3 className="font-semibold">Guide</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
                  <li>Top panel: enter a game name of your choice and your name, then Connect.</li>
                  <li>Share the name with any other people that want to play</li>
                  <li>The first person to connect becomes the host and assigns seats/teams.</li>
                  <li>Rules and Guide button: opens this help popup anytime.</li>
                  <li>Turn and Phase cards: show who acts now and current game stage.</li>
                  <li>Round Snapshot: tracks this hand, this trick, and active bid.</li>
                  <li>Action panel: bidding and dealer controls only appear when relevant.</li>
                  <li>Your Hand: click a card to play when it is your turn.</li>
                  <li>Game Log: newest event is at the top.</li>
                </ul>
              </article>

              <article className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
                <h3 className="font-semibold">History and AI</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
                  <li>The AI players use predefined strategies to make decisions during the game.</li>
                  <li>They are based on different profiles such as cautious, balanced, aggressive, and chaotic.</li>
                  <li>They are inspired by 4 siblings (now deceased) who were avid Kaiser players.</li>
                  <li>They grew up on a farm not far from Smutz Saskatchewan, Canada.</li>
                  <li>They played Kaiser together over many years, developing unique strategies.</li>
                 </ul>
              </article>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
