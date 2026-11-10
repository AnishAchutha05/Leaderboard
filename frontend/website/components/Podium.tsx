import { Trophy } from "lucide-react";
import type { Participant } from "@/lib/types";
import { initials, ordinal } from "@/lib/format";
import ProgressBar from "./ProgressBar";

interface Props {
  top: Participant[];
  loading: boolean;
  onSelect: (participant: Participant) => void;
}

export default function Podium({ top, loading, onSelect }: Props) {
  const three = top.slice(0, 3);
  return (
    <section aria-label="Top three" className="bg-accent">
      <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 sm:py-8">
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.18em] text-ink">Top 3</p>
        {loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
            {[0, 1, 2].map((item) => <div key={item} className="shimmer h-[132px] rounded-lg" />)}
          </div>
        ) : three.length === 0 ? (
          <p className="rounded-lg bg-white/90 p-4 text-sm text-soft">The podium fills up once participants earn badges.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
            {three.map((participant, index) => {
              const first = index === 0;
              return (
                <button
                  key={participant.key}
                  type="button"
                  onClick={() => onSelect(participant)}
                  className={`group relative flex min-h-[132px] flex-col justify-between rounded-lg p-4 text-left shadow-card transition-transform duration-150 hover:-translate-y-0.5 ${first ? "on-dark bg-ink text-white" : "bg-white text-ink"}`}
                >
                  <div className="flex items-start gap-3">
                    <div className="relative shrink-0">
                      <span className={`flex h-12 w-12 items-center justify-center rounded-sm text-base font-semibold ${first ? "bg-white text-ink" : "bg-canvas text-ink"}`}>
                        {initials(participant.name)}
                      </span>
                      <span className={`absolute -left-2 -top-2 flex h-6 w-6 items-center justify-center rounded-sm text-xs font-bold tabular-nums ${first ? "bg-accent text-ink" : "bg-ink text-white"}`}>
                        {participant.rank}
                      </span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-base font-semibold leading-tight">{participant.name}</p>
                      <p className={`mt-0.5 text-xs ${first ? "text-white/75" : "text-faint"}`}>{ordinal(participant.rank)} place</p>
                    </div>
                    {first && <Trophy className="h-5 w-5 shrink-0 text-accent" aria-label="Leader" />}
                  </div>
                  <div className="mt-4">
                    <div className="mb-1.5 flex items-baseline justify-between tabular-nums">
                      <span className="text-xl font-semibold leading-none">{participant.completed}/{participant.total}</span>
                      <span className={`text-xs font-medium ${first ? "text-white/75" : "text-faint"}`}>{Math.round(participant.progress)}%</span>
                    </div>
                    <ProgressBar value={participant.progress} label={`${participant.name} progress`} tone={first ? "dark" : "light"} />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
