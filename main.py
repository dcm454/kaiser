from kaiser import KaiserGame


HELP_TEXT = """
Commands:
    help                Show this help
    rules               Show short game rules summary
    state               Show current game core state
    deal                Build + shuffle deck and deal 8 cards to each player
    hands               Show each player's hand
    bidding             Show bidding history and next bidder
    bid <n> <trump>     Bid for current bidder (trump: clubs|diamonds|hearts|spades|no-trump)
    pass                Pass for current bidder
    take <trump>        Dealer takes current highest number with chosen trump
    trick               Show trick/contract/team points state
    play <card>         Play card for current player (example: 10h, As, 7c)
    tricks              Alias for trick
    rotate              Rotate dealer to next player
    quit                Exit
""".strip()

RULES_TEXT = """
Kaiser short rules:
    - Deal starts bidding (left of dealer first).
    - Bid format: bid <7-12> <clubs|diamonds|hearts|spades|no-trump>.
    - Single bidding cycle: each player acts once; dealer is last.
    - If no one bids before dealer, dealer must bid.
    - Dealer may take current highest number with chosen trump: take <trump>.
    - Dealer may also keep high bid unchanged and close bidding by passing (only if a high bid exists).
    - No-trump contracts: contracting team scoring is doubled (made bid: 2x points won; failed bid: 2x bid penalty).
    - Winning team must bid out (contracting team must make its bid in the winning hand).
    - Winning score target is 52 if no no-trump bid has occurred; target becomes 64 if any no-trump bid occurs.
    - Dealer action closes bidding and starts play.
    - Play in turn. You must follow lead suit if you can.
""".strip()


def run_cli() -> None:
    game = KaiserGame.new_default()

    print("Kaiser CLI Core")
    print(HELP_TEXT)

    while True:
        try:
            raw = input("\nkaiser> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()

        if cmd == "help":
            print(HELP_TEXT)
        elif cmd == "rules":
            print(RULES_TEXT)
        elif cmd == "state":
            print(game.state_summary())
        elif cmd == "deal":
            game.deal_new_hand()
            print("Dealt 8 cards to each player.")
            print(game.state_summary())
        elif cmd == "hands":
            for player in game.players:
                print(f"{player.name}: {player.show_hand()}")
        elif cmd == "bidding":
            print(game.bidding_summary())
        elif cmd == "bid":
            if len(parts) != 3:
                print("Usage: bid <n> <trump>")
                continue
            try:
                value = int(parts[1])
            except ValueError:
                print("Bid value must be an integer")
                continue
            trump = parts[2].lower()
            try:
                result = game.place_bid(value=value, trump=trump)
                print(result)
                if game.phase == "playing":
                    print("Bidding complete. Play phase started.")
                    print(game.trick_summary())
            except ValueError as exc:
                print(str(exc))
        elif cmd == "pass":
            try:
                result = game.pass_bid()
                print(result)
                if game.phase == "playing":
                    print("Bidding complete. Play phase started.")
                    print(game.trick_summary())
            except ValueError as exc:
                print(str(exc))
        elif cmd == "take":
            if len(parts) != 2:
                print("Usage: take <trump>")
                continue
            try:
                trump = parts[1].lower()
                result = game.dealer_take_bid(trump=trump)
                print(result)
                if game.phase == "playing":
                    print("Bidding complete. Play phase started.")
                    print(game.trick_summary())
            except ValueError as exc:
                print(str(exc))
        elif cmd in ("trick", "tricks"):
            print(game.trick_summary())
        elif cmd == "play":
            if len(parts) != 2:
                print("Usage: play <card>")
                continue
            try:
                result = game.play_card(parts[1])
                print(result)
                print(game.trick_summary())
                if game.phase == "hand_over":
                    print("Hand complete.")
            except ValueError as exc:
                print(str(exc))
        elif cmd == "rotate":
            new_dealer = game.rotate_dealer()
            print(f"Dealer rotated to {new_dealer.name}.")
        elif cmd in ("quit", "exit"):
            print("bye")
            break
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'help' for available commands.")


if __name__ == "__main__":
    run_cli()