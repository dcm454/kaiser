const roomIdEl = document.getElementById("roomId");
const playerNameEl = document.getElementById("playerName");
const connectBtn = document.getElementById("connectBtn");
const connectionStatusEl = document.getElementById("connectionStatus");
const turnTextEl = document.getElementById("turnText");
const yourTurnEl = document.getElementById("yourTurn");
const logEl = document.getElementById("log");
const handButtonsEl = document.getElementById("handButtons");
const scoreboardSummaryEl = document.getElementById("scoreboardSummary");
const winningStatusEl = document.getElementById("winningStatus");
const gameScoreTextLegacyEl = document.getElementById("gameScoreText");
const thisHandTextEl = document.getElementById("thisHandText");
const thisHandLegacyEl = document.getElementById("handScoreText");
const handScoreTextEl = document.getElementById("handScoreText");
const bidTextEl = document.getElementById("bidText");
const setupPanelEl = document.getElementById("setupPanel");
const setupStatusEl = document.getElementById("setupStatus");
const virtualPlayerCardsEl = document.getElementById("virtualPlayerCards");
const seatAssignmentGridEl = document.getElementById("seatAssignmentGrid");
const startBotsBtn = document.getElementById("startBotsBtn");

const bidValueEl = document.getElementById("bidValue");
const bidTrumpEl = document.getElementById("bidTrump");
const bidBtn = document.getElementById("bidBtn");
const passBtn = document.getElementById("passBtn");
const takeTrumpEl = document.getElementById("takeTrump");
const takeBtn = document.getElementById("takeBtn");
const commandPanelEl = document.getElementById("commandPanel");
const dealControlsEl = document.getElementById("dealControls");
const biddingControlsEl = document.getElementById("biddingControls");
const playingHintEl = document.getElementById("playingHint");

let ws = null;
let playerIndex = null;
let playerName = null;
let currentTurnIndex = null;
let turnContext = null;
let trickPlayHistory = [];
let currentHandTrickNumber = 1;
let currentPhase = "idle";
let dealerIndex = null;
let roomReady = false;
let isHost = false;
let setupRequired = false;
let virtualPlayers = [];
let setupInfo = null;
let setupAssignments = [null, null, null, null];
const FIXED_SERVER_URL = "wss://kaiser-server-997088621734.us-central1.run.app/";

const commandButtons = [...document.querySelectorAll("button[data-action]")];

function setStatus(connected) {
  connectionStatusEl.textContent = connected ? "Connected" : "Disconnected";
  connectionStatusEl.className = `badge ${connected ? "ok" : "warn"}`;
}

function addLog(message) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  logEl.textContent = `${logEl.textContent}${line}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function setTextIfPresent(element, text) {
  if (element) {
    element.textContent = text;
  }
}

function updateControlVisibility() {
  if (!roomReady) {
    dealControlsEl.style.display = "none";
    biddingControlsEl.style.display = "none";
    playingHintEl.style.display = "none";
    commandPanelEl.style.display = "none";
    return;
  }

  let showDealControls = false;
  let showBiddingControls = false;
  let showPlayingHint = false;

  if (currentPhase === "bidding") {
    showBiddingControls = true;
  } else if (currentPhase === "playing") {
    showPlayingHint = false;
  } else {
    const isDealer = dealerIndex !== null && playerIndex !== null && dealerIndex === playerIndex;
    showDealControls = isDealer;
  }

  dealControlsEl.style.display = showDealControls ? "flex" : "none";
  biddingControlsEl.style.display = showBiddingControls ? "flex" : "none";
  playingHintEl.style.display = showPlayingHint ? "flex" : "none";
  commandPanelEl.style.display = (showDealControls || showBiddingControls || showPlayingHint) ? "block" : "none";
}

function renderSetupPanel() {
  if (!setupPanelEl) {
    return;
  }

  const showPanel = !roomReady;
  setupPanelEl.style.display = showPanel ? "block" : "none";
  if (!showPanel) {
    return;
  }

  const statusText = isHost
    ? (setupRequired ? "You are host. Review virtual players, then start setup." : "Setup complete. Waiting for deal.")
    : "Waiting for host to finish setup...";
  setTextIfPresent(setupStatusEl, statusText);
  if (startBotsBtn) {
    startBotsBtn.style.display = isHost && setupRequired ? "inline-block" : "none";
  }

  if (virtualPlayerCardsEl) {
    virtualPlayerCardsEl.innerHTML = "";
    virtualPlayers.forEach((vp) => {
      const card = document.createElement("div");
      card.className = "setup-card";
      card.innerHTML = `<b>${vp.name} (${vp.profile})</b><div class="subtle">${vp.bio || ""}</div>`;
      virtualPlayerCardsEl.appendChild(card);
    });
  }

  if (seatAssignmentGridEl) {
    seatAssignmentGridEl.innerHTML = "";
    for (let seat = 0; seat < 4; seat += 1) {
      const card = document.createElement("div");
      card.className = "setup-card";
      const teamLabel = seat % 2 === 0 ? "Team 1" : "Team 2";
      const title = document.createElement("b");
      title.textContent = `Seat ${seat + 1} (${teamLabel})`;
      card.appendChild(title);

      if (isHost && setupRequired && setupInfo) {
        const select = document.createElement("select");
        select.style.width = "100%";
        const options = [];
        (setupInfo.human_options || []).forEach((h) => {
          options.push({ value: h.id, label: `${h.name} (human)` });
        });
        (setupInfo.bot_options || []).forEach((b) => {
          options.push({ value: b.id, label: `${b.name} (${b.profile})` });
        });

        options.forEach((opt) => {
          const optionEl = document.createElement("option");
          optionEl.value = opt.value;
          optionEl.textContent = opt.label;
          select.appendChild(optionEl);
        });

        if (!setupAssignments[seat] && setupInfo.current_assignments && setupInfo.current_assignments[seat]) {
          setupAssignments[seat] = setupInfo.current_assignments[seat];
        }
        if (setupAssignments[seat]) {
          select.value = setupAssignments[seat];
        }

        select.addEventListener("change", () => {
          setupAssignments[seat] = select.value;
        });

        card.appendChild(select);
      } else {
        const assignment = setupInfo?.current_assignments?.[seat] || "";
        const matchHuman = (setupInfo?.human_options || []).find((h) => h.id === assignment);
        const matchBot = (setupInfo?.bot_options || []).find((b) => b.id === assignment);
        const label = matchHuman ? `${matchHuman.name} (human)` : matchBot ? `${matchBot.name} (${matchBot.profile})` : "Unassigned";
        const text = document.createElement("div");
        text.className = "subtle";
        text.textContent = label;
        card.appendChild(text);
      }

      seatAssignmentGridEl.appendChild(card);
    }
  }
}

function applyRoomPayload(payload) {
  const room = payload.room;
  if (!room) {
    return;
  }
  roomReady = room.ready === true;
  if (room.setup) {
    setupInfo = room.setup;
    if (Array.isArray(setupInfo.current_assignments) && setupInfo.current_assignments.length === 4) {
      setupAssignments = [...setupInfo.current_assignments];
    }
  }
  if (Array.isArray(room.available_virtual_players)) {
    virtualPlayers = room.available_virtual_players;
  }
  if (typeof room.setup_complete === "boolean") {
    setupRequired = !room.setup_complete && isHost;
  }
  renderSetupPanel();
  updateControlVisibility();
}

function updateTurn(payload) {
  if (typeof payload.current_player_index !== "number") {
    yourTurnEl.style.display = "none";
    yourTurnEl.classList.remove("your-turn-badge");
    return;
  }
  currentTurnIndex = payload.current_player_index;
  const currentName = payload.current_player_name || `Player ${currentTurnIndex + 1}`;
  turnContext = payload.turn_context || turnContext;

  if (turnContext === "idle") {
    turnTextEl.textContent = `Dealer - ${currentName}`;
  } else {
    turnTextEl.textContent = currentName;
  }

  const isMine = playerIndex !== null && currentTurnIndex === playerIndex;
  yourTurnEl.style.display = isMine ? "inline-block" : "none";
  if (isMine) {
    yourTurnEl.classList.add("your-turn-badge");
  } else {
    yourTurnEl.classList.remove("your-turn-badge");
  }

  if (isMine) {
    addLog(">>> Your turn");
  }

  // Light client-side guidance; server still enforces all rules.
  if (turnContext === "bidding") {
    bidBtn.disabled = !isMine;
    passBtn.disabled = !isMine;
    takeBtn.disabled = !isMine;
  } else if (turnContext === "playing") {
    bidBtn.disabled = true;
    passBtn.disabled = true;
    takeBtn.disabled = true;
  }

  updateHandCardButtonsEnabled();
}

function shortCardToToken(cardLabel) {
  const cleaned = (cardLabel || "").trim().replace("*", "");
  if (!cleaned) {
    return null;
  }
  const suitSymbol = cleaned.slice(-1);
  const rank = cleaned.slice(0, -1);
  const suitMap = {
    "♣": "c",
    "♦": "d",
    "♥": "h",
    "♠": "s",
  };
  const suit = suitMap[suitSymbol];
  if (!rank || !suit) {
    return null;
  }
  return `${rank}${suit}`;
}

function updateHandCardButtonsEnabled() {
  const isMyTurnToPlay = turnContext === "playing" && playerIndex !== null && currentTurnIndex === playerIndex;
  const buttons = handButtonsEl.querySelectorAll("button.card-btn");
  buttons.forEach((button) => {
    button.disabled = !isMyTurnToPlay;
  });
}

function renderHandCards(cardsText) {
  handButtonsEl.innerHTML = "";
  const cards = (cardsText || "").trim() ? cardsText.trim().split(/\s+/) : [];
  if (cards.length === 0) {
    const empty = document.createElement("div");
    empty.className = "subtle";
    empty.textContent = "No cards";
    handButtonsEl.appendChild(empty);
    return;
  }

  cards.forEach((cardLabel) => {
    const token = shortCardToToken(cardLabel);
    const button = document.createElement("button");
    button.className = "card-btn";
    button.textContent = cardLabel;
    if (!token) {
      button.disabled = true;
      handButtonsEl.appendChild(button);
      return;
    }
    button.addEventListener("click", () => {
      send({ action: "play", card: token });
    });
    handButtonsEl.appendChild(button);
  });

  updateHandCardButtonsEnabled();
}

function renderThisHandSection() {
  const handIsComplete = currentPhase === "hand_over" || currentHandTrickNumber > 8;
  const lines = [handIsComplete ? "Hand completed" : `Trick Number: ${currentHandTrickNumber}`];
  if (trickPlayHistory.length === 0) {
    lines.push(handIsComplete ? "No active trick" : "No cards played in this trick yet");
  } else {
    lines.push(...trickPlayHistory);
  }
  setTextIfPresent(handScoreTextEl, lines.join("\n"));
}

function updateScoreboard(payload) {
  const scoreboard = payload.scoreboard;
  if (!scoreboard) {
    return;
  }

  const teamLabels = scoreboard.team_labels || {};
  const team0Label = teamLabels.team0 || "Team 1";
  const team1Label = teamLabels.team1 || "Team 2";

  const gameScore = scoreboard.game_score || {};
  const hand = scoreboard.hand || {};
  const tricks = hand.tricks || {};
  const points = hand.points || {};
  const winning = scoreboard.winning || {};

  currentPhase = scoreboard.phase || currentPhase;
  if (typeof scoreboard.dealer_index === "number") {
    dealerIndex = scoreboard.dealer_index;
  }
  updateControlVisibility();

  const summaryText = `${team0Label} (${gameScore.team0 ?? 0}), ${team1Label} (${gameScore.team1 ?? 0})`;
  if (scoreboardSummaryEl) {
    setTextIfPresent(scoreboardSummaryEl, summaryText);
  } else {
    setTextIfPresent(gameScoreTextLegacyEl, `${team0Label}: ${gameScore.team0 ?? 0}\n${team1Label}: ${gameScore.team1 ?? 0}`);
  }

  if (winningStatusEl) {
    const target = winning.target ?? 52;
    const noTrumpSeen = winning.no_trump_bid_seen === true;
    const winnerTeamLabel = winning.winner_team_label || null;
    const base = `Target ${target} (${noTrumpSeen ? "no-trump bid seen" : "no no-trump bids yet"})`;
    const statusText = winnerTeamLabel ? `${base} | Winner: ${winnerTeamLabel} (bid out)` : `${base} | No winner yet`;
    setTextIfPresent(winningStatusEl, statusText);
  }

  const thisHandText = [
    `${team0Label}: ${tricks.team0 ?? 0} tricks (${points.team0 ?? 0} points)`,
    `${team1Label}: ${tricks.team1 ?? 0} tricks (${points.team1 ?? 0} points)`,
  ].join("\n");
  if (thisHandTextEl) {
    setTextIfPresent(thisHandTextEl, thisHandText);
  } else {
    setTextIfPresent(thisHandLegacyEl, thisHandText);
  }

  currentHandTrickNumber = hand.trick_number ?? 1;
  renderThisHandSection();

  const bid = scoreboard.bid || scoreboard.contract;
  if (!bid) {
    setTextIfPresent(bidTextEl, "No bid yet");
    return;
  }

  const bidTeamLabel = bid.team_label || bid.team || "Unknown team";
  setTextIfPresent(bidTextEl, `${bid.value} ${bid.trump} by ${bid.declarer} (${bidTeamLabel})`);
}

function send(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addLog("Not connected.");
    return;
  }
  ws.send(JSON.stringify(payload));
}

function handleMessage(data) {
  if (data.error) {
    addLog(`Error: ${data.error}`);
    updateTurn(data);
    return;
  }

  switch (data.type) {
    case "joined":
      playerIndex = data.player_index;
      isHost = data.is_host === true;
      setupRequired = data.setup_required === true;
      trickPlayHistory = [];
      currentHandTrickNumber = 1;
      renderThisHandSection();
      addLog(`Joined room '${data.room_id}' as ${data.player_name} (Player ${playerIndex + 1}).`);
      addLog(`Human players in room: ${data.players_count}/4`);
      break;
    case "seat_assigned":
      if (typeof data.player_index === "number") {
        playerIndex = data.player_index;
      }
      isHost = data.is_host === true;
      setupRequired = data.setup_required === true;
      addLog(`Seat assignment updated. You are now Seat ${playerIndex + 1}.`);
      break;
    case "player_joined":
      addLog(`${data.player_name} joined (Player ${data.player_index + 1}).`);
      addLog(`Human players in room: ${data.players_count}/4`);
      break;
    case "player_left":
      addLog(`${data.player_name} left.`);
      addLog(`Human players in room: ${data.players_count}/4`);
      break;
    case "setup_complete":
      setupRequired = false;
      addLog(data.message || "Setup complete.");
      break;
    case "hand":
      renderHandCards(data.cards || "");
      break;
    case "state":
    case "bidding":
    case "trick":
      addLog(data.content || "");
      break;
    case "game_update":
      addLog(data.message || "");
      if (typeof data.message === "string") {
        if (data.message.startsWith("Dealt 8 cards")) {
          trickPlayHistory = [];
          currentHandTrickNumber = 1;
          renderThisHandSection();
        } else if (data.message.includes(" played ")) {
          const playedLine = data.message.split("|")[0].trim();
          trickPlayHistory.push(playedLine);
          if (data.message.includes("| Trick won by ")) {
            trickPlayHistory = [];
          }
          renderThisHandSection();
        }
      }
      if (data.state) addLog(data.state);
      if (data.bidding) addLog(data.bidding);
      if (data.trick) addLog(data.trick);
      if (data.bot_action && data.bot_action.bot_name) {
        addLog(`🤖 ${data.bot_action.bot_name}: ${data.bot_action.action}`);
      }
      break;
    case "phase_change":
      addLog(data.message || "");
      if (data.trick) addLog(data.trick);
      break;
    case "hand_complete":
      addLog(data.message || "Hand complete.");
      if (data.trick) addLog(data.trick);
      if (data.state) addLog(data.state);
      break;
    default:
      addLog(JSON.stringify(data));
  }

  updateTurn(data);
  updateScoreboard(data);
  applyRoomPayload(data);
}

connectBtn.addEventListener("click", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
    return;
  }

  const serverUrl = FIXED_SERVER_URL;
  const roomId = roomIdEl.value.trim() || "myroom";
  playerName = playerNameEl.value.trim() || `Player-${Math.floor(Math.random() * 1000)}`;

  ws = new WebSocket(serverUrl);
  ws.onopen = () => {
    setStatus(true);
    connectBtn.textContent = "Disconnect";
    addLog(`Connected to ${serverUrl}`);
    send({ action: "join", room_id: roomId, name: playerName });
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleMessage(data);
    } catch (err) {
      addLog(`Bad message: ${event.data}`);
    }
  };

  ws.onerror = () => {
    addLog("WebSocket error.");
  };

  ws.onclose = () => {
    setStatus(false);
    connectBtn.textContent = "Connect";
    addLog("Disconnected.");
    ws = null;
  };
});

commandButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const action = btn.getAttribute("data-action");
    send({ action });
  });
});

bidBtn.addEventListener("click", () => {
  const value = Number(bidValueEl.value);
  const trump = bidTrumpEl.value;
  send({ action: "bid", value, trump });
});

passBtn.addEventListener("click", () => {
  send({ action: "pass" });
});

takeBtn.addEventListener("click", () => {
  send({ action: "take", trump: takeTrumpEl.value });
});

if (startBotsBtn) {
  startBotsBtn.addEventListener("click", () => {
    const values = setupAssignments.filter((item) => typeof item === "string" && item.length > 0);
    if (values.length !== 4) {
      addLog("Setup error: all 4 seats must be assigned.");
      return;
    }
    const uniqueCount = new Set(values).size;
    if (uniqueCount !== 4) {
      addLog("Setup error: seat assignments must be unique.");
      return;
    }
    send({ action: "setup_game", seat_assignments: values });
  });
}

setStatus(false);
updateControlVisibility();
addLog("Ready. Enter server URL, room, name, then Connect.");
