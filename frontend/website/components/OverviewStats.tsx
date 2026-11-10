import { Award, Gauge, Layers, Users } from "lucide-react";
import type { LeaderboardData } from "@/lib/types";

interface Props {
  data: LeaderboardData | null;
}

export default function OverviewStats({ data }: Props) {
  const participantCount = data?.participants.length ?? 0;
  const available = data?.badges.length ?? 0;
  const earned = data?.participants.reduce(
    (sum, participant) => sum + participant.badges.filter((badge) => badge.earned).length,
    0,
  ) ?? 0;
  const possible = participantCount * available;
  const rate = possible > 0 ? (earned / possible) * 100 : 0;
  const ready = data !== null;

  const cards = [
    { label: "Participants", value: participantCount.toLocaleString("en-IN"), Icon: Users, dark: false },
    { label: "Badges available", value: available.toLocaleString("en-IN"), Icon: Layers, dark: false },
    { label: "Badges earned", value: earned.toLocaleString("en-IN"), Icon: Award, dark: false },
    { label: "Completion rate", value: `${rate.toFixed(1)}%`, Icon: Gauge, dark: true },
  ];

  return (
    <section aria-label="Overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
      {cards.map(({ label, value, Icon, dark }) => (
        <div
          key={label}
          className={`flex items-center justify-between gap-3 rounded-lg border p-4 shadow-card ${dark ? "border-ink bg-ink text-white" : "border-line bg-white"}`}
        >
          <div className="min-w-0">
            <p className="truncate text-2xl font-semibold tabular-nums leading-none sm:text-3xl">{ready ? value : "–"}</p>
            <p className={`mt-2 text-xs font-medium leading-tight ${dark ? "text-white/75" : "text-faint"}`}>{label}</p>
          </div>
          <span
            className={`hidden h-10 w-10 shrink-0 items-center justify-center rounded-sm min-[420px]:flex ${dark ? "bg-accent text-ink" : "bg-accent-tint text-accent-deep"}`}
            aria-hidden
          >
            <Icon className="h-5 w-5" />
          </span>
        </div>
      ))}
    </section>
  );
}
