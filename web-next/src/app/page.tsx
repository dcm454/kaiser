"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type SetupOption = { id: string; name: string; seat?: number };
type SetupState = { human_options?: SetupOption[]; bot_options?: SetupOption[]; current_assignments?: (string | null)[] };
type RoomPayload = {
  room?: {
    ready?: boolean;
    setup_complete?: boolean;
    host_player_index?: number;
    host_is_observer?: boolean;
    setup?: SetupState;
    roster?: Array<{ seat?: number; name?: string | null }>;
  };
};

const WS_URL = process.env.NEXT_PUBLIC_WS_URL;
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://kaiser-caaa4.web.app";
const GAME_TIMEOUT_MS = 60 * 60 * 1000;

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

function formatBotActionLog(botAction: Record<string, any>): string {
  const botName = typeof botAction.bot_name === "string" ? botAction.bot_name : "BOT";
  const action = typeof botAction.action === "string" ? botAction.action : "action";
  const reason = typeof botAction.reason === "string" ? botAction.reason : "";
  const debug = botAction.debug ?? {};

  const parts: string[] = [`BOT ${botName}: ${action}`];
  if (debug.bid_strength_best !== undefined && debug.bid_strength_best_trump) {
    parts.push(`strength=${debug.bid_strength_best} (${debug.bid_strength_best_trump})`);
  }
  if (debug.bid_strength_no_trump !== undefined && debug.bid_strength_best_suit_trump) {
    parts.push(`nt=${debug.bid_strength_no_trump} vs ${debug.bid_strength_best_suit} (${debug.bid_strength_best_suit_trump})`);
  }
  if (debug.bid_strength_best_trump === "no-trump") {
    const margin = action === "take" ? debug.no_trump_take_margin : debug.no_trump_bid_margin;
    if (debug.bid_strength_no_trump_advantage !== undefined && margin !== undefined) {
      parts.push(`why=no-trump +${debug.bid_strength_no_trump_advantage} over ${debug.bid_strength_best_suit_trump} (margin ${margin})`);
    } else {
      parts.push(`why=no-trump beat ${debug.bid_strength_best_suit_trump}`);
    }
  }
  if (Array.isArray(debug.hand_cards) && debug.hand_cards.length > 0) {
    parts.push(`hand=${debug.hand_cards.join(" ")}`);
  }
  if (typeof debug.play_reason === "string" && debug.play_reason.length > 0) {
    parts.push(`play_reason=${debug.play_reason}`);
  } else if (reason.length > 0) {
    parts.push(`reason=${reason}`);
  }

  return parts.join(" | ");
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

function GuideContent() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <article className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
        <h3 className="font-semibold">Rules Summary</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
          <li>Kaiser is a 4-player partnership trick-taking game: Seat 1 and 3 vs Seat 2 and 4.</li>
          <li>Each hand has staged bidding, trump selection by the winning bidder, then trick play.</li>
          <li>In bidding, players bid values only, pass, and the dealer can take the current value.</li>
          <li>Once the contract value is established, the winner chooses trump.</li>
          <li>In play, follow suit when possible. Highest card of lead suit wins unless trump is played.</li>
          <li>The 5H adds 5 points. The 3S subtracts 3 points.</li>
          <li>The winning target is 52, or 64 after a successful no-trump contract.</li>
          <li>Each game must be completed within 60 minutes.</li>
        </ul>
      </article>

      <article className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
        <h3 className="font-semibold">Guide</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
          <li>Enter a game name and your name, then connect.</li>
          <li>The first person in becomes host and assigns seats or AI players.</li>
          <li>Learning mode: if you are alone, use Watch 4 AI to host as observer and study every trick.</li>
          <li>Before setup is complete, the screen stays focused on the setup table.</li>
          <li>After setup, the game board opens with round status, controls, hand, and log.</li>
          <li>When a hand ends, any seated human can press Start Next Hand (dealer rotates automatically).</li>
          <li>Starting a new game resets the 60-minute timer.</li>
          <li>Use Playing Guide anytime to reopen these notes.</li>
          <li>On a phone, the layout stacks in play order so the hand stays easy to reach.</li>
        </ul>
      </article>

      <article className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3 md:col-span-2">
        <h3 className="font-semibold">History and AI</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-emerald-900">
          <li>The AI players each have distinct personalities and adapt to the table as hands unfold.</li>
          <li>Live game logs now include bid strength, hand snapshots, and play reasons for bot turns.</li>
          <li>The interface keeps setup focused first, then expands into the full table once the room is ready.</li>
        </ul>
      </article>
    </div>
  );
}

export default function Page() {
  const [gameName, setGameName] = useState("mygame");
  const [playerName, setPlayerName] = useState("");
  const [connected, setConnected] = useState(false);
  const [isHost, setIsHost] = useState(false);
  const [isObserver, setIsObserver] = useState(false);
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
  const [winningStatus, setWinningStatus] = useState("Target 52 (no successful no-trump contract yet)");
  const [newGameStatus, setNewGameStatus] = useState("No new game prompt yet.");
  const [startNewGameVisible, setStartNewGameVisible] = useState(false);
  const [startNewGameReady, setStartNewGameReady] = useState(false);
  const [startNewGameVoted, setStartNewGameVoted] = useState(false);
  const [thisHand, setThisHand] = useState("Team 1:0 tr (0 pts)\nTeam 2:0 tr (0 pts)");
  const [trickNumber, setTrickNumber] = useState(1);
  const [trickPlayHistory, setTrickPlayHistory] = useState<string[]>([]);
  const [trickCompleted, setTrickCompleted] = useState(false);
  const [bidText, setBidText] = useState("No bid yet");
  const [winningBidSummary, setWinningBidSummary] = useState("No bid yet");
  const [currentHighestBidValue, setCurrentHighestBidValue] = useState(0);
  const [bidProgression, setBidProgression] = useState<string[]>([]);
  const [winningBidPatterns, setWinningBidPatterns] = useState<string[]>([]);
  const [cards, setCards] = useState<string[]>([]);
  const [handRevision, setHandRevision] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  const [setupInfo, setSetupInfo] = useState<SetupState | null>(null);
  const [setupAssignments, setSetupAssignments] = useState<(string | null)[]>([null, null, null, null]);
  const [contractTrump, setContractTrump] = useState("clubs");
  const [bidNoTrump, setBidNoTrump] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [joinRejection, setJoinRejection] = useState<string | null>(null);
  const [handActionError, setHandActionError] = useState<string | null>(null);
  const [gameTimerEndsAt, setGameTimerEndsAt] = useState<number | null>(null);
  const [timerNow, setTimerNow] = useState(Date.now());
  const [debugDrawerOpen, setDebugDrawerOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [currentPlayerIndex, setCurrentPlayerIndex] = useState<number | null>(null);
  const [seatNames, setSeatNames] = useState<string[]>(["Seat 1", "Seat 2", "Seat 3", "Seat 4"]);
  const [winnerTeamIndex, setWinnerTeamIndex] = useState<number | null>(null);
  const [winnerTeamLabel, setWinnerTeamLabel] = useState<string | null>(null);
  const [showWinCelebration, setShowWinCelebration] = useState(false);
  const [celebrationKey, setCelebrationKey] = useState(0);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const trickCompletedRef = useRef(false);
  const handSectionRef = useRef<HTMLDivElement | null>(null);
  const previousWinnerTeamRef = useRef<number | null>(null);
  const trickLingerTimerRef = useRef<number | null>(null);
  const trickPlayHistoryRef = useRef<string[]>([]);
  const trickNumberRef = useRef<number>(1);
  const currentPhaseRef = useRef<string>("idle");
  const [trickLingering, setTrickLingering] = useState(false);
  const [lingeredTrickHistory, setLingeredTrickHistory] = useState<string[]>([]);
  const [lingeredTrickNumber, setLingeredTrickNumber] = useState(1);

  const homeSchema = useMemo(
    () => ({
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "WebSite",
          name: "Play Kaiser Online",
          url: SITE_URL,
          description: "Play Kaiser online free with no ads.",
          potentialAction: {
            "@type": "SearchAction",
            target: `${SITE_URL}/guide`,
            "query-input": "required name=search_term_string",
          },
        },
        {
          "@type": "Game",
          name: "Kaiser Online",
          url: SITE_URL,
          applicationCategory: "Game",
          genre: ["Card game", "Trick-taking", "Multiplayer"],
          playMode: ["MultiPlayer", "SinglePlayer"],
          description:
            "Play Kaiser online free with friends or AI. No ads, no downloads, and mobile-friendly gameplay.",
          offers: {
            "@type": "Offer",
            price: "0",
            priceCurrency: "USD",
          },
        },
      ],
    }),
    []
  );

  useEffect(() => {
    if (currentPhase !== "bidding") setBidNoTrump(false);
  }, [currentPhase]);

  useEffect(() => {
    if (!(connected && roomReady)) return;
    if (!["bidding", "playing", "hand_over"].includes(currentPhase)) return;
    if (typeof window === "undefined") return;
    if (!window.matchMedia("(max-width: 767px)").matches) return;

    const timer = window.setTimeout(() => {
      handSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);

    return () => window.clearTimeout(timer);
  }, [connected, roomReady, currentPhase, handRevision]);

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
    if (data.room.setup) {
      setSetupInfo(data.room.setup);
      if (Array.isArray(data.room.setup.current_assignments) && data.room.setup.current_assignments.length === 4) {
        setSetupAssignments(data.room.setup.current_assignments);
      }
    }

    if (Array.isArray(data.room.roster) && data.room.roster.length > 0) {
      const nextNames = ["Seat 1", "Seat 2", "Seat 3", "Seat 4"];
      for (const item of data.room.roster) {
        if (!item || typeof item.seat !== "number") continue;
        if (item.seat < 0 || item.seat > 3) continue;
        if (typeof item.name === "string" && item.name.trim().length > 0) {
          nextNames[item.seat] = item.name;
        }
      }
      setSeatNames(nextNames);
    }
  };

  const assignmentLabel = (assignment: string | null) => {
    if (!assignment) return "Unassigned";
    const human = (setupInfo?.human_options ?? []).find((h) => h.id === assignment);
    if (human) return `${human.name} (human)`;
    const bot = (setupInfo?.bot_options ?? []).find((b) => b.id === assignment);
    if (bot) return `${bot.name} (AI)`;
    return assignment;
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
    const winnerLabel = winning.winner_team_label;
    const base = `Target ${target} (${noTrumpSeen ? "successful no-trump contract seen" : "no successful no-trump contract yet"})`;
    setWinningStatus(winnerLabel ? `${base} | Winner: ${winnerLabel} (bid out)` : `${base} | No winner yet`);

    const nextWinnerTeamIndex = winning.winner_team_index === 0 || winning.winner_team_index === 1
      ? winning.winner_team_index
      : null;
    if (nextWinnerTeamIndex !== previousWinnerTeamRef.current) {
      if (nextWinnerTeamIndex !== null) {
        setCelebrationKey((value) => value + 1);
        setShowWinCelebration(true);
      }
      previousWinnerTeamRef.current = nextWinnerTeamIndex;
    }
    setWinnerTeamIndex(nextWinnerTeamIndex);
    setWinnerTeamLabel(typeof winnerLabel === "string" && winnerLabel.length > 0 ? winnerLabel : null);

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
      setWinningBidSummary("No bid yet");
      setCurrentHighestBidValue(0);
      setWinningBidPatterns([]);
    } else {
      setCurrentHighestBidValue(typeof bid.value === "number" ? bid.value : 0);
      if (bid.trump === "hidden") {
        setBidText(`${bid.value} by ${bid.declarer}`);
        setWinningBidSummary(`${bid.declarer}: ${bid.value}`);
      } else {
        setBidText(`${bid.value} ${bid.trump} by ${bid.declarer}`);
        setWinningBidSummary(`${bid.declarer}: ${bid.value} ${bid.trump}`);
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
    if (!WS_URL) {
      setJoinRejection("NEXT_PUBLIC_WS_URL is not configured. Set it in web-next/.env.local, then rebuild or restart the app.");
      return;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close();
      setWs(null);
      setConnected(false);
      setGameTimerEndsAt(null);
      return;
    }

    const socket = new WebSocket(WS_URL);
    socket.onopen = () => {
      setConnected(true);
      resetGameTimer();
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
      if (typeof data.current_player_index === "number") {
        setCurrentPlayerIndex(data.current_player_index);
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
          setIsObserver(data.is_observer === true);
          setSetupRequired(data.setup_required === true);
          setJoinRejection(null);
          if (typeof data.player_index === "number") {
            appendLog(`Joined game '${data.room_id}' as ${data.player_name} (Seat ${data.player_index + 1}).`);
          } else {
            appendLog(`Joined game '${data.room_id}' as ${data.player_name} (observer).`);
          }
          break;
        case "player_joined":
          if (data.is_observer === true) {
            appendLog(`${data.player_name} joined as observer.`);
          } else if (typeof data.player_index === "number") {
            appendLog(`${data.player_name} joined (Seat ${data.player_index + 1}).`);
          } else {
            appendLog(`${data.player_name} joined.`);
          }
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
            setIsObserver(false);
          } else if (data.player_index === null) {
            nextPlayerIndex = null;
            setPlayerIndex(null);
            setIsObserver(data.is_observer === true);
          }
          nextIsHost = data.is_host === true;
          setIsHost(nextIsHost);
          setSetupRequired(data.setup_required === true);
          if (typeof data.player_index === "number") {
            appendLog(`Seat assignment updated. You are now Seat ${data.player_index + 1}.`);
          } else if (data.is_observer === true) {
            appendLog("Observer mode enabled. You are now hosting as observer.");
          } else {
            appendLog("Seat assignment updated.");
          }
          break;
        case "hand":
          setCards((data.cards || "").trim() ? data.cards.trim().split(/\s+/) : []);
          setHandRevision((value) => value + 1);
          break;
        case "new_game_started":
          resetGameTimer();
          setBidProgression([]);
          setTrickPlayHistory([]);
          setTrickNumber(1);
          setWinnerTeamIndex(null);
          setWinnerTeamLabel(null);
          setShowWinCelebration(false);
          previousWinnerTeamRef.current = null;
          setStartNewGameVisible(false);
          setStartNewGameReady(false);
          setStartNewGameVoted(false);
          trickCompletedRef.current = false;
          setTrickCompleted(false);
          clearTrickLinger();
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
          clearTrickLinger();
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
        appendLog(formatBotActionLog(data.bot_action));
      }
    };

    socket.onclose = () => {
      setConnected(false);
      setGameTimerEndsAt(null);
      setWs(null);
      appendLog("Disconnected.");
    };

    socket.onerror = () => appendLog("WebSocket error.");
    setWs(socket);
  };

  const clearTrickLinger = () => {
    if (trickLingerTimerRef.current !== null) {
      window.clearTimeout(trickLingerTimerRef.current);
      trickLingerTimerRef.current = null;
    }
    setTrickLingering(false);
  };

  const suits = ["clubs", "diamonds", "hearts", "spades"];

  const thisTrickText = useMemo(() => {
    const effectiveHistory = trickLingering ? lingeredTrickHistory : trickPlayHistory;
    const effectiveNumber = trickLingering ? lingeredTrickNumber : trickNumber;
    const effectiveCompleted = trickLingering || trickCompleted;

    const displayTrickNumber = effectiveCompleted && effectiveNumber > 1 ? effectiveNumber - 1 : effectiveNumber;
    const header = effectiveCompleted ? `Trick Number: ${displayTrickNumber} (completed)` : `Trick Number: ${displayTrickNumber}`;
    const lines = [header];

    if (currentPhase === "playing") {
      const bySeat: Record<number, string> = {};
      for (const line of effectiveHistory) {
        const match = /^(.+?) played (.+)$/.exec(line.trim());
        if (!match) continue;
        const player = match[1].trim();
        const card = match[2].trim();
        const seat = seatNames.findIndex((name) => name === player);
        if (seat >= 0) bySeat[seat] = card;
      }

      let leader = currentPlayerIndex ?? 0;
      if (effectiveHistory.length > 0) {
        const first = effectiveHistory[0].trim();
        const match = /^(.+?) played /.exec(first);
        if (match) {
          const seat = seatNames.findIndex((name) => name === match[1].trim());
          if (seat >= 0) leader = seat;
        }
      }

      const order = [leader, (leader + 1) % 4, (leader + 2) % 4, (leader + 3) % 4];
      for (const seat of order) {
        const playerName = seatNames[seat] ?? `Seat ${seat + 1}`;
        const card = bySeat[seat];
        const isCurrent = !effectiveCompleted && seat === currentPlayerIndex;
        lines.push(card ? `${playerName} played ${card}` : (isCurrent ? `\x01${playerName}` : playerName));
      }
      return lines.join("\n");
    }

    if (effectiveHistory.length === 0) {
      lines.push(currentPhase === "hand_over" ? "No active trick" : "No cards played in this trick yet");
    } else {
      lines.push(...effectiveHistory);
    }
    return lines.join("\n");
  }, [trickNumber, trickPlayHistory, currentPhase, trickCompleted, seatNames, currentPlayerIndex, trickLingering, lingeredTrickHistory, lingeredTrickNumber]);

  const bidCardText = useMemo(() => {
    if (bidProgression.length > 0) return bidProgression;
    return ["No bids yet"];
  }, [bidProgression]);

  const biddingOrderLines = useMemo(() => {
    if (dealerIndex === null) {
      return bidProgression.length > 0
        ? bidProgression.map(line => ({ text: line, isCurrentBidder: false, hasBid: true }))
        : [{ text: "No bids yet", isCurrentBidder: false, hasBid: false }];
    }
    const order = [(dealerIndex + 1) % 4, (dealerIndex + 2) % 4, (dealerIndex + 3) % 4, dealerIndex];
    return order.map(seat => {
      const name = seatNames[seat] ?? `Seat ${seat + 1}`;
      const bidLine = bidProgression.find(line => line.startsWith(`${name}:`));
      const hasBid = !!bidLine;
      const isCurrent = currentPhase === "bidding" && seat === currentPlayerIndex && !hasBid;
      return { text: bidLine ?? name, isCurrentBidder: isCurrent, hasBid };
    });
  }, [dealerIndex, seatNames, bidProgression, currentPhase, currentPlayerIndex]);

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

  const startObserverMode = () => {
    send({ action: "setup_observer_mode" });
  };

  const seatDisplay = ["Seat 1 (Team 1)", "Seat 2 (Team 2)", "Seat 3 (Team 1)", "Seat 4 (Team 2)"];
  const isMyBidTurn = turnContext === "bidding";
  const isMyTrumpTurn = turnContext === "choosing_trump" && playerIndex === currentPlayerIndex;
  const isMyPlayTurn = turnContext === "playing";
  const phaseLabel = currentPhase.replaceAll("_", " ");
  const showLandingGuide = !connected;
  const showSetupStage = connected && !roomReady;
  const showActiveGame = connected && roomReady;
  const compactPlayingHeader = showActiveGame && currentPhase === "playing";
  const headerActionText = compactPlayingHeader ? `${phaseLabel}: ${turnName}` : null;
  const showSnapshotHand = currentPhase !== "bidding" && currentPhase !== "choosing_trump";
  const showSnapshotTrick = currentPhase !== "bidding" && currentPhase !== "choosing_trump";
  const showSnapshotBid = currentPhase !== "playing" && currentPhase !== "hand_over";
  const showDebugDrawerControl = connected && isHost;
  const canHostDealAsObserver = isHost && isObserver;
  const remainingTimerMs = gameTimerEndsAt === null ? GAME_TIMEOUT_MS : Math.max(0, gameTimerEndsAt - timerNow);
  const timerMinutes = Math.floor(remainingTimerMs / 60000);
  const timerSeconds = Math.floor((remainingTimerMs % 60000) / 1000);
  const gameTimerText = `${String(timerMinutes).padStart(2, "0")}:${String(timerSeconds).padStart(2, "0")}`;

  const resetGameTimer = () => {
    const now = Date.now();
    setTimerNow(now);
    setGameTimerEndsAt(now + GAME_TIMEOUT_MS);
  };

  useEffect(() => {
    if (!connected || gameTimerEndsAt === null) {
      return;
    }

    const intervalId = window.setInterval(() => {
      setTimerNow(Date.now());
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [connected, gameTimerEndsAt]);

  useEffect(() => {
    if (!showDebugDrawerControl) {
      setDebugDrawerOpen(false);
    }
  }, [showDebugDrawerControl]);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [currentPhase, connected, roomReady]);

  useEffect(() => { trickPlayHistoryRef.current = trickPlayHistory; }, [trickPlayHistory]);
  useEffect(() => { trickNumberRef.current = trickNumber; }, [trickNumber]);
  useEffect(() => { currentPhaseRef.current = currentPhase; }, [currentPhase]);

  useEffect(() => {
    if (!trickCompleted) return;
    setLingeredTrickHistory([...trickPlayHistoryRef.current]);
    setLingeredTrickNumber(trickNumberRef.current);
    setTrickLingering(true);
    if (trickLingerTimerRef.current !== null) window.clearTimeout(trickLingerTimerRef.current);
    trickLingerTimerRef.current = window.setTimeout(() => {
      setTrickLingering(false);
      trickLingerTimerRef.current = null;
      // If no new trick has started (no play has arrived to flip trickCompletedRef),
      // reset so the UI shows the fresh empty trick instead of the completed one.
      if (trickCompletedRef.current && currentPhaseRef.current === "playing") {
        trickCompletedRef.current = false;
        setTrickCompleted(false);
        setTrickPlayHistory([]);
      }
    }, 4000);
  }, [trickCompleted]);

  useEffect(() => {
    if (!showWinCelebration) return;
    const timer = window.setTimeout(() => setShowWinCelebration(false), 4200);
    return () => window.clearTimeout(timer);
  }, [showWinCelebration]);

  const phaseChipClasses = () => {
    if (currentPhase === "playing") return "chip border-emerald-300 bg-emerald-100 text-emerald-900";
    if (currentPhase === "bidding") return "chip border-lime-300 bg-lime-100 text-lime-900";
    if (currentPhase === "hand_over") return "chip border-teal-300 bg-teal-100 text-teal-900";
    return "chip border-emerald-200 bg-emerald-50 text-emerald-900";
  };

  const cardTone = (card: string) => {
    const suit = card.replace("*", "").slice(-1);
    if (suit === "♥" || suit === "♦") return "border-emerald-300 bg-emerald-50";
    if (suit === "♣" || suit === "♠") return "border-lime-300 bg-lime-50";
    return "border-emerald-200 bg-white";
  };

  const cardInk = (card: string) => {
    const suit = card.replace("*", "").slice(-1);
    if (suit === "♥" || suit === "♦") return "text-red-600";
    return "text-slate-900";
  };

  const renderSuitColoredLine = (line: string) => {
    return [...line].map((ch, index) => {
      if (ch === "♥" || ch === "♦") {
        return <span key={`${ch}-${index}`} className="text-red-600">{ch}</span>;
      }
      if (ch === "♣" || ch === "♠") {
        return <span key={`${ch}-${index}`} className="text-slate-900">{ch}</span>;
      }
      return <span key={`${ch}-${index}`}>{ch}</span>;
    });
  };

  return (
    <main className="relative mx-auto max-w-7xl px-4 pb-8 pt-6 sm:px-6 lg:px-8">
      {showWinCelebration && winnerTeamLabel && (
        <div key={celebrationKey} className="win-celebration pointer-events-none fixed inset-0 z-50">
          <div className="win-ribbon absolute left-1/2 top-16 -translate-x-1/2 rounded-full border border-amber-300 bg-amber-100/95 px-6 py-2 text-center text-sm font-semibold text-amber-900 shadow-xl">
            {winnerTeamLabel} wins the game!
          </div>
          {Array.from({ length: 28 }).map((_, index) => {
            const left = ((index * 37) % 100);
            const delay = (index % 7) * 0.08;
            const duration = 2.6 + (index % 5) * 0.18;
            const colors = ["#f59e0b", "#22c55e", "#0ea5e9", "#ef4444"];
            return (
              <span
                key={`confetti-${index}`}
                className="win-confetti"
                style={{
                  left: `${left}%`,
                  animationDelay: `${delay}s`,
                  animationDuration: `${duration}s`,
                  backgroundColor: colors[index % colors.length],
                }}
              />
            );
          })}
        </div>
      )}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(homeSchema) }} />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-48 bg-gradient-to-b from-emerald-300/35 to-transparent" />
      <div className="space-y-4">
        <section className="panel animate-enter">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              {!compactPlayingHeader && <p className="text-xs uppercase tracking-[0.24em] text-soft">Realtime Table</p>}
              <h1 className={`${compactPlayingHeader ? "" : "mt-1 "}flex items-center gap-3 text-2xl font-bold tracking-tight sm:text-3xl`}>
                <EightCardHandIcon />
                <span>Play Kaiser Online Free</span>
                <button
                  className="chip min-h-9 w-10 justify-center border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200 md:hidden"
                  onClick={() => setMobileMenuOpen((open) => !open)}
                  aria-label="Open header menu"
                  aria-expanded={mobileMenuOpen}
                >
                  <span className="flex flex-col items-center gap-1" aria-hidden="true">
                    <span className="block h-0.5 w-4 rounded bg-emerald-900" />
                    <span className="block h-0.5 w-4 rounded bg-emerald-900" />
                    <span className="block h-0.5 w-4 rounded bg-emerald-900" />
                  </span>
                </button>
              </h1>
              {compactPlayingHeader ? (
                <p className="mt-1 text-sm font-medium text-soft">{headerActionText}</p>
              ) : (
                <p className="mt-1 text-sm text-soft">No ads, no downloads. Fast multiplayer rounds with live bids, play-by-play trick state, and host setup controls.</p>
              )}
            </div>
            <div className="flex flex-col items-end gap-2 self-start md:flex-row md:items-center">
              <span className={`chip hidden min-h-9 min-w-24 justify-center md:inline-flex ${remainingTimerMs > 0 ? "border-sky-300 bg-sky-100 text-sky-900" : "border-amber-300 bg-amber-100 text-amber-900"}`}>
                {remainingTimerMs > 0 ? `Timer ${gameTimerText}` : "Time Expired"}
              </span>

              <div className="hidden md:flex flex-wrap items-center justify-end gap-2">
                {showDebugDrawerControl && (
                  <button
                    className={`chip min-h-9 justify-center transition ${debugDrawerOpen ? "border-sky-400 bg-sky-100 text-sky-900 hover:bg-sky-200" : "border-emerald-300 bg-emerald-100 text-emerald-900 hover:bg-emerald-200"}`}
                    onClick={() => setDebugDrawerOpen((open) => !open)}
                  >
                    {debugDrawerOpen ? "Hide Debug" : "Debug Log"}
                  </button>
                )}
                {connected && isHost && roomReady && (
                  <button className="chip min-h-9 justify-center border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200" onClick={() => send({ action: "restart_game" })}>Reset Game</button>
                )}
                <button
                  className="chip min-h-9 justify-center border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200"
                  onClick={() => setHelpOpen(true)}
                  aria-label="Open game help"
                >
                  Playing Guide
                </button>
                {connected && (
                  <button className="chip min-h-9 justify-center border-rose-300 bg-rose-100 text-rose-900 transition hover:bg-rose-200" onClick={connect}>Disconnect</button>
                )}
              </div>

              <div className="flex items-center gap-2 md:hidden">
                <span className={`chip min-h-9 min-w-24 justify-center ${remainingTimerMs > 0 ? "border-sky-300 bg-sky-100 text-sky-900" : "border-amber-300 bg-amber-100 text-amber-900"}`}>
                  {remainingTimerMs > 0 ? `Timer ${gameTimerText}` : "Time Expired"}
                </span>
                {connected && (
                  <button className="chip min-h-9 justify-center border-rose-300 bg-rose-100 text-rose-900 transition hover:bg-rose-200" onClick={connect}>Disconnect</button>
                )}
              </div>

              {mobileMenuOpen && (
                <div className="w-full rounded-xl border border-emerald-200 bg-white p-2 md:hidden">
                  <div className="grid gap-2">
                    {showDebugDrawerControl && (
                      <button
                        className={`chip min-h-9 justify-center transition ${debugDrawerOpen ? "border-sky-400 bg-sky-100 text-sky-900 hover:bg-sky-200" : "border-emerald-300 bg-emerald-100 text-emerald-900 hover:bg-emerald-200"}`}
                        onClick={() => {
                          setDebugDrawerOpen((open) => !open);
                          setMobileMenuOpen(false);
                        }}
                      >
                        {debugDrawerOpen ? "Hide Debug" : "Debug Log"}
                      </button>
                    )}
                    {connected && isHost && roomReady && (
                      <button
                        className="chip min-h-9 justify-center border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200"
                        onClick={() => {
                          send({ action: "restart_game" });
                          setMobileMenuOpen(false);
                        }}
                      >
                        Reset Game
                      </button>
                    )}
                    <button
                      className="chip min-h-9 justify-center border-emerald-300 bg-emerald-100 text-emerald-900 transition hover:bg-emerald-200"
                      onClick={() => {
                        setHelpOpen(true);
                        setMobileMenuOpen(false);
                      }}
                      aria-label="Open game help"
                    >
                      Playing Guide
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {!connected && (
            <div className="mt-4 grid gap-3 md:grid-cols-[1fr,1fr,auto]">
              <input className="field" value={gameName} onChange={(e) => setGameName(e.target.value)} placeholder="Game name" />
              <input className="field" value={playerName} onChange={(e) => setPlayerName(e.target.value)} placeholder="Your name" />
              <button className="btn-primary" onClick={connect} disabled={!WS_URL}>Connect</button>
            </div>
          )}

          {!connected && !WS_URL && (
            <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
              Missing NEXT_PUBLIC_WS_URL. Set it in web-next/.env.local and restart the frontend.
            </div>
          )}

          {joinRejection && (
            <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
              {joinRejection}
            </div>
          )}
        </section>

        {showLandingGuide && (
          <section className="panel animate-enter space-y-4">
            <div className="max-w-2xl">
              <p className="text-xs uppercase tracking-[0.2em] text-soft">Before You Join</p>
              <h2 className="mt-1 text-xl font-semibold sm:text-2xl">Quick Guide to Starting a Table</h2>
              <p className="mt-2 text-sm text-soft">
                The landing screen keeps things simple on phones: connect from the header, then move directly into seat setup.
              </p>
              <p className="mt-2 text-sm text-soft">
                Looking for a search-friendly rules page? <a className="underline decoration-emerald-500 underline-offset-2" href="/guide">Read the full Kaiser guide</a>.
              </p>
            </div>
            <GuideContent />
          </section>
        )}

        {showActiveGame && (
        <section className="grid gap-3">
          <article className="info-card animate-enter py-2.5">
            <p className="text-xs uppercase tracking-[0.2em] text-soft">Live Score</p>
            <p className="mt-1.5 text-base font-semibold">{scoreSummary}</p>
            <p className="mt-1 text-sm text-soft">Session Wins: {sessionWinsSummary}</p>
            <p className="mt-1 text-sm text-soft">{winningStatus}</p>
            <p className="mt-1 text-sm text-soft">{newGameStatus}</p>
          </article>
        </section>
        )}

        {showSetupStage && (
          <section className="panel animate-enter mx-auto w-full max-w-5xl space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Game Setup</h2>
              {isHost && setupRequired ? (
                <span className="flex items-center gap-2 text-sm text-soft">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-4 w-4"
                    aria-hidden="true"
                  >
                    <path d="M10 13a5 5 0 0 0 7.54.54l2.92-2.92a5 5 0 0 0-7.07-7.07L11.72 5.2" />
                    <path d="M14 11a5 5 0 0 0-7.54-.54L3.54 13.38a5 5 0 0 0 7.07 7.07l1.67-1.67" />
                  </svg>
                  <span>
                    You are host. Invite others with this link <a className="underline decoration-emerald-500 underline-offset-2" href="https://kaiser-caaa4.web.app/" target="_blank" rel="noreferrer">https://kaiser-caaa4.web.app/</a> and share this game name: <strong>{gameName.trim() || "mygame"}</strong>.
                  </span>
                </span>
              ) : (
                <span className="text-sm text-soft">
                  {isHost ? "Setup complete." : "Waiting for host setup..."}
                </span>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
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

            {isHost && setupRequired && (
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary" onClick={sendSetup}>Start Game with Selected Seats</button>
                <button className="btn-secondary" onClick={startObserverMode}>Learning Mode: Watch 4 AI</button>
              </div>
            )}
          </section>
        )}

        {showActiveGame && (
        <section className="space-y-4">
            <section className="panel animate-enter">
              <h2 className="mb-3 text-lg font-semibold">Round Snapshot</h2>
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  {showSnapshotHand && (
                    <pre className="mono-block whitespace-pre-wrap"><strong>This Hand</strong>{"\n"}{currentPhase !== "playing" ? `Turn: ${turnName}\n` : ""}Phase: {phaseLabel}{"\n"}Dealer: {dealerName}{"\n"}Winning Bid: {winningBidSummary}{"\n"}{thisHand}</pre>
                  )}
                  {showSnapshotTrick && (
                    <div className="mono-block whitespace-pre-wrap">
                      <strong>This Trick</strong>
                      <div className="mt-2 space-y-0.5">
                        {thisTrickText
                          .split("\n")
                          .map((line, index) => {
                            const isCurrent = line.startsWith("\x01");
                            const displayLine = isCurrent ? line.slice(1) : line;
                            return (
                              <div key={`${displayLine}-${index}`} className={isCurrent ? "font-bold italic" : undefined}>
                                {renderSuitColoredLine(displayLine)}
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  )}
                </div>
                {showSnapshotBid && (
                  <div className="mono-block whitespace-pre-wrap">
                    <strong>Bid</strong>
                    <div className="mt-2 space-y-1">
                      {biddingOrderLines.map((item, index) => (
                        <div
                          key={`${item.text}-${index}`}
                          className={
                            item.isCurrentBidder
                              ? "font-bold italic"
                              : isWinningBidLine(item.text)
                              ? "font-semibold text-emerald-700"
                              : !item.hasBid && item.text !== "No bids yet"
                              ? "text-slate-400"
                              : undefined
                          }
                        >
                          {item.text}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </section>

            {roomReady && (
              <section className="panel animate-enter space-y-4">
                <div className="flex flex-wrap gap-2">
                  {currentPhase === "idle" && dealerIndex === playerIndex && (
                    <button className="btn-primary" onClick={() => send({ action: "deal" })}>Deal</button>
                  )}
                  {currentPhase === "idle" && canHostDealAsObserver && (
                    <button className="btn-primary" onClick={() => send({ action: "deal" })}>Deal</button>
                  )}
                </div>

                {currentPhase === "bidding" && (
                  <div className="space-y-3 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3">
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-[0.2em] text-soft">Bid Value</p>
                      <div className="flex flex-wrap gap-2">
                        {[7, 8, 9, 10, 11, 12].map((n) => (
                          (() => {
                            const unavailable = bidNoTrump ? n < currentHighestBidValue : n <= currentHighestBidValue;
                            return (
                          <button
                            key={n}
                            type="button"
                            disabled={!isMyBidTurn || unavailable}
                            className={`min-w-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed ${
                              unavailable
                                ? "border-emerald-100 bg-emerald-50 text-emerald-300 opacity-55"
                                : "border-emerald-200 bg-white text-emerald-900 hover:border-emerald-400 hover:bg-emerald-100 disabled:opacity-50"
                            }`}
                            onClick={() => send({ action: "bid", value: n, ...(bidNoTrump ? { trump: "no-trump" } : {}) })}
                          >
                            {n}
                          </button>
                            );
                          })()
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={!isMyBidTurn}
                        onClick={() => setBidNoTrump((prev) => !prev)}
                        className={`rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
                          bidNoTrump
                            ? "border-purple-400 bg-purple-100 text-purple-900 hover:bg-purple-200"
                            : "border-emerald-200 bg-white text-emerald-700 hover:border-emerald-400 hover:bg-emerald-50"
                        }`}
                        aria-pressed={bidNoTrump}
                      >
                        No
                      </button>
                      <button disabled={!isMyBidTurn} className="btn-secondary" onClick={() => send({ action: "pass" })}>Pass</button>
                      <button disabled={!isMyBidTurn} className="btn-secondary" onClick={() => send({ action: "take" })}>Take</button>
                    </div>
                  </div>
                )}

                {currentPhase === "choosing_trump" && isMyTrumpTurn && (
                  <div className="grid gap-3 rounded-xl border border-lime-200 bg-lime-50/70 p-3 md:grid-cols-2 xl:grid-cols-3">
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-[0.2em] text-soft">Select Trump</p>
                      <select value={contractTrump} onChange={(e) => setContractTrump(e.target.value)} className="field">
                        {suits.map((s) => <option key={s}>{s}</option>)}
                      </select>
                    </div>
                    <div className="flex flex-wrap gap-2 md:col-span-2 xl:col-span-3">
                      <button className="btn-primary" onClick={() => send({ action: "choose_trump", trump: contractTrump })}>Confirm Trump</button>
                    </div>
                  </div>
                )}

                <div ref={handSectionRef}>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-base font-semibold">Your Hand</h3>
                    <div className="flex flex-wrap gap-2">
                      {roomReady && currentPhase === "hand_over" && !startNewGameVisible && (
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
                  </div>
                  {handActionError && (
                    <div className="mb-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
                      {handActionError}
                    </div>
                  )}
                  <div key={`hand-${handRevision}`} className="grid grid-cols-4 gap-2 lg:grid-cols-6">
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
                        <span className={cardInk(card)}>{card}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            )}
        </section>
        )}
      </div>

      {showDebugDrawerControl && (
        <>
          {debugDrawerOpen && (
            <button
              type="button"
              aria-label="Close debug drawer"
              className="fixed inset-0 z-40 bg-emerald-950/25"
              onClick={() => setDebugDrawerOpen(false)}
            />
          )}
          <aside
            className={`fixed inset-y-0 right-0 z-50 w-full max-w-md transform border-l border-emerald-200 bg-white/96 p-4 shadow-2xl backdrop-blur-xl transition duration-300 ease-out ${debugDrawerOpen ? "translate-x-0" : "translate-x-full"}`}
            aria-hidden={!debugDrawerOpen}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-soft">Host Only</p>
                <h2 className="text-lg font-semibold">Debug Log</h2>
              </div>
              <button className="btn-secondary" onClick={() => setDebugDrawerOpen(false)}>Close</button>
            </div>
            <p className="mt-2 text-sm text-soft">Use this hidden drawer to monitor bot decisions and gameplay events without exposing the log during play.</p>
            <pre className="mono-block mt-4 max-h-[calc(100vh-9rem)] overflow-auto whitespace-pre-wrap">{log.join("\n")}</pre>
          </aside>
        </>
      )}

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

            <div className="mt-4">
              <GuideContent />
              <p className="mt-3 text-sm text-emerald-800">
                Prefer a standalone page? <a className="underline decoration-emerald-500 underline-offset-2" href="/guide">Open the full Kaiser guide</a>.
              </p>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
