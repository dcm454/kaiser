import type { Metadata } from "next";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://kaiser-caaa4.web.app";

export const metadata: Metadata = {
  title: "Kaiser Game Guide and Rules",
  description:
    "Learn how to play Kaiser online: bidding, trump and no-trump contracts, trick scoring, and multiplayer setup.",
  alternates: {
    canonical: "/guide",
  },
  openGraph: {
    title: "Kaiser Game Guide and Rules",
    description:
      "Step-by-step guide to play Kaiser online, including bidding and no-trump strategy.",
    url: `${siteUrl}/guide`,
    siteName: "Play Kaiser Online",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "Kaiser Game Guide and Rules",
    description:
      "Learn the rules and strategy for playing Kaiser online with friends or AI.",
  },
};

const faqSchema = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "How do I play Kaiser online?",
      acceptedAnswer: {
        "@type": "Answer",
        text:
          "Create or join a game room, assign seats, bid a contract, choose trump (or declare no-trump during bidding), then play tricks while following suit.",
      },
    },
    {
      "@type": "Question",
      name: "How many players are needed for Kaiser?",
      acceptedAnswer: {
        "@type": "Answer",
        text:
          "Kaiser is a 4-player partnership card game: Seat 1 and Seat 3 versus Seat 2 and Seat 4.",
      },
    },
    {
      "@type": "Question",
      name: "How does no-trump affect the winning target?",
      acceptedAnswer: {
        "@type": "Answer",
        text:
          "The game target starts at 52 and changes to 64 only after a successful no-trump contract.",
      },
    },
  ],
};

type Suit = "clubs" | "diamonds" | "hearts" | "spades";

function SuitIcon({ suit, className = "" }: { suit: Suit; className?: string }) {
  const suitMap: Record<Suit, { symbol: string; label: string; tone: string }> = {
    clubs: { symbol: "\u2663", label: "Clubs", tone: "text-emerald-700" },
    diamonds: { symbol: "\u2666", label: "Diamonds", tone: "text-red-600" },
    hearts: { symbol: "\u2665", label: "Hearts", tone: "text-rose-600" },
    spades: { symbol: "\u2660", label: "Spades", tone: "text-slate-800" },
  };
  const { symbol, label, tone } = suitMap[suit];
  return (
    <span aria-label={label} title={label} className={`inline-block align-[-0.08em] font-semibold ${tone} ${className}`.trim()}>
      {symbol}
    </span>
  );
}

export default function GuidePage() {
  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-8 text-emerald-950 sm:px-6">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqSchema) }} />

      <header className="space-y-2">
        <p className="text-xs uppercase tracking-[0.2em] text-soft">Kaiser Card Game</p>
        <h1 className="text-3xl font-semibold sm:text-4xl">Play Kaiser Online: Rules, Setup, and Strategy</h1>
        <p className="text-sm text-soft sm:text-base">
          Learn how to play Kaiser online with live multiplayer rooms, AI seats, bidding strategy, and scoring rules.
        </p>
      </header>

      <section className="info-card space-y-3">
        <h2 className="text-xl font-semibold">Quick Start</h2>
        <ol className="list-decimal space-y-2 pl-5 text-sm sm:text-base">
          <li>Open the game lobby and enter a game name and player name.</li>
          <li>The first person connected becomes host.</li>
          <li>Share the Game Name with other players to join the room and then assign the seats.</li>
          <li>Dealer deals 8 cards each, then bidding begins.</li>
          <li>Winning bid sets the contract value; no-trump can be declared during bidding.</li>
          <li>Play tricks in turn and follow lead suit when possible.</li>
        </ol>
      </section>

      <section className="info-card space-y-3">
        <h2 className="text-xl font-semibold">Kaiser Rules Summary</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm sm:text-base">
          <li>Kaiser is a 4-player partnership trick-taking game.</li>
          <li>Teams are Seat 1 and 3 versus Seat 2 and 4.</li>
          <li>
            The 5<SuitIcon suit="hearts" className="text-[0.95em]" /> adds 5 points and the 3<SuitIcon suit="spades" className="text-[0.95em]" /> subtracts 3 points.
          </li>
          <li>Contracting team must make its bid to score positively.</li>
          <li>No-trump doubles contracting-team scoring for that hand.</li>
          <li>Winning target changes from 52 to 64 only after a successful no-trump contract.</li>
        </ul>
      </section>

      <section className="info-card space-y-3">
        <h2 className="text-xl font-semibold">Bidding and No-Trump</h2>
        <p className="text-sm sm:text-base">
          Bidding is single-cycle: each seat acts once and dealer closes. A no-trump declaration can be made during bidding.
          No-trump is strongest when you have high-card control in multiple suits, not just one long suit.
        </p>
        <p className="text-sm sm:text-base">
          Typical no-trump indicators include aces across suits, protected kings and queens, and reliable stoppers against
          opponent suit runs.
        </p>
      </section>

      <section className="info-card space-y-3">
        <h2 className="text-xl font-semibold">Play Kaiser Online with Friends or AI</h2>
        <p className="text-sm sm:text-base">
          You can fill seats with AI profiles for practice, or play full human tables. The browser app supports mobile and
          desktop play with live trick updates, score tracking, and in-game guide support.
        </p>
        <p className="text-sm sm:text-base">
          Return to the game lobby: <a className="underline decoration-emerald-500 underline-offset-2" href="/">Play Kaiser Online</a>
        </p>
      </section>
    </main>
  );
}
