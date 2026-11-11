import { Gauge, Layers, Users } from "lucide-react";
import type { LeaderboardData } from "@/lib/types";

interface Props {
  data: LeaderboardData | null;
}

export default function OverviewStats({ data }: Props) {
  const participantCount = data?.participants.length ?? 0;
  const available = data?.badges.length ?? 0;
  const fullyCompletedParticipants = data?.participants.filter(
    (participant) => available > 0 && participant.completed >= available,
  ).length ?? 0;
  const remainingSeats = Math.max(0, 250 - fullyCompletedParticipants);
  const completionRate = data && participantCount > 0
    ? (data.participants.reduce((sum, participant) => sum + participant.progress, 0) / participantCount)
    : 0;
  const ready = data !== null;

  const cards = [
    { label: "Participants", value: participantCount.toLocaleString("en-IN"), Icon: Users, dark: false },
    { label: "Badges available", value: available.toLocaleString("en-IN"), Icon: Layers, dark: false },
    {
      label: "Seats remaining",
      value: remainingSeats === 0 ? "All seats are filled" : remainingSeats.toLocaleString("en-IN"),
      Icon: Users,
      dark: false,
      full: remainingSeats === 0,
    },
    { label: "Completion rate", value: `${completionRate.toFixed(1)}%`, Icon: Gauge, dark: true },
  ];

  return (
    <section aria-label="Overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
      {cards.map(({ label, value, Icon, dark, full }) => (
        <div
          key={label}
          className={`flex items-center justify-between gap-3 rounded-lg border p-4 shadow-card ${dark ? "border-ink bg-ink text-white" : "border-line bg-white"}`}
        >
          <div className="min-w-0">
            <p className={`truncate font-semibold leading-none ${full ? "text-sm sm:text-base" : "text-2xl tabular-nums sm:text-3xl"}`}>
              {ready ? value : "–"}
            </p>
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
