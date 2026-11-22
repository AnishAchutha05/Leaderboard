import { Check, SearchX, Users } from "lucide-react";
import type { Badge, Participant } from "@/lib/types";
import ProgressBar from "./ProgressBar";

interface Props {
  participants: Participant[];
  badges: Badge[];
  loading: boolean;
  searching: boolean;
  onSelect: (participant: Participant) => void;
}

// On phones the two pinned columns must stay narrow (168px) so the scrolling
// columns remain visible beside them; from `sm` up they use the roomier widths.
const RANK_TH = "sticky left-0 z-30 w-10 min-w-10 bg-panel sm:w-14 sm:min-w-14";
const NAME_TH = "sticky left-10 z-30 w-32 min-w-32 bg-panel sm:left-14 sm:w-56 sm:min-w-56";
const RANK_TD = "sticky left-0 z-10 w-10 min-w-10 bg-white group-hover:bg-accent-tint sm:w-14 sm:min-w-14";
const NAME_TD = "sticky left-10 z-10 w-32 min-w-32 bg-white group-hover:bg-accent-tint sm:left-14 sm:w-56 sm:min-w-56";
// The table uses auto layout, so a nowrap name would stretch its column to the
// longest name. A fixed-width label is what actually caps the column on phones.
const NAME_LABEL = "block w-[6.5rem] truncate text-left font-medium hover:underline sm:w-full";

function RankBadge({ rank }: { rank: number }) {
  if (rank > 3) return <span className="text-sm font-medium tabular-nums text-soft">{rank}</span>;
  const tone = rank === 1 ? "bg-accent text-ink" : rank === 2 ? "bg-ink text-white" : "bg-[#C9C9C9] text-ink";
  return <span className={`mx-auto flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold tabular-nums ${tone}`}>{rank}</span>;
}

export default function Leaderboard({ participants, badges, loading, searching, onSelect }: Props) {
  if (!loading && participants.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-sm bg-canvas text-faint" aria-hidden>
          {searching ? <SearchX className="h-6 w-6" /> : <Users className="h-6 w-6" />}
        </span>
        <p className="text-base font-semibold">{searching ? "No matches" : "No participants yet"}</p>
        <p className="max-w-sm text-sm text-faint">
          {searching ? "Nothing matches that search. Try another name or clear the search." : "Participant records from the backend will appear here."}
        </p>
      </div>
    );
  }

  const skeletonCols = badges.length > 0 ? badges.length : 8;
  return (
    <div className="thin-scroll max-h-[72vh] overflow-auto">
      <table className="w-max min-w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th scope="col" className={`${RANK_TH} sticky top-0 z-40 border-b border-line px-1 pb-3 text-center align-bottom text-[11px] font-semibold uppercase tracking-wider text-faint sm:px-2`}><span className="sm:hidden">#</span><span className="hidden sm:inline">Rank</span></th>
            <th scope="col" className={`${NAME_TH} sticky top-0 z-40 border-b border-line px-3 pb-3 text-left align-bottom text-[11px] font-semibold uppercase tracking-wider text-faint`}>Participant</th>
            <th scope="col" className="sticky top-0 z-20 w-14 min-w-14 border-b border-line bg-panel px-1 pb-3 text-center sm:w-20 sm:min-w-20 sm:px-3 align-bottom text-[11px] font-semibold uppercase tracking-wider text-faint">Done</th>
            <th scope="col" className="sticky top-0 z-20 hidden w-32 min-w-32 border-b border-line bg-panel px-3 pb-3 text-left sm:table-cell align-bottom text-[11px] font-semibold uppercase tracking-wider text-faint">Progress</th>
            {badges.map((badge, index) => (
              <th
                key={badge.key}
                scope="col"
                title={`${badge.name} · ${badge.itemType} · ${badge.credits} credits · ${badge.category}`}
                aria-label={`Task ${index + 1}: ${badge.name}`}
                className="sticky top-0 z-20 h-[76px] w-10 min-w-10 border-b border-line bg-panel px-0 pb-3 align-bottom sm:h-[170px] sm:w-12 sm:min-w-12"
              >
                <div className="vlabel mx-auto text-xs font-medium text-soft">
                  Task {index + 1}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: 8 }).map((_, row) => (
                <tr key={row}>
                  <td className={`${RANK_TD} border-b border-line px-1 py-3 sm:px-2`}><div className="shimmer mx-auto h-5 w-5 rounded-full" /></td>
                  <td className={`${NAME_TD} border-b border-line px-3 py-3`}><div className="shimmer h-4 w-3/4 rounded-sm" /></td>
                  <td className="border-b border-line px-1 py-3 sm:px-3"><div className="shimmer mx-auto h-4 w-10 rounded-sm" /></td>
                  <td className="hidden border-b border-line px-3 py-3 sm:table-cell"><div className="shimmer h-4 w-24 rounded-sm" /></td>
                  {Array.from({ length: skeletonCols }).map((__, col) => <td key={col} className="border-b border-line px-0 py-3"><div className="shimmer mx-auto h-4 w-4 rounded-sm" /></td>)}
                </tr>
              ))
            : participants.map((participant) => (
                <tr key={participant.key} onClick={() => onSelect(participant)} className="group cursor-pointer hover:bg-accent-tint">
                  <td className={`${RANK_TD} border-b border-line px-1 py-2.5 text-center sm:px-2`}><RankBadge rank={participant.rank} /></td>
                  <td className={`${NAME_TD} border-b border-line px-3 py-2.5`}>
                    <button
                      type="button"
                      onClick={(event) => { event.stopPropagation(); onSelect(participant); }}
                      className={NAME_LABEL}
                      title={participant.name}
                    >
                      {participant.name}
                    </button>
                  </td>
                  <td className="border-b border-line px-1 py-2.5 text-center font-medium tabular-nums sm:px-3">{participant.completed}/{participant.total}</td>
                  <td className="hidden border-b border-line px-3 py-2.5 sm:table-cell">
                    <div className="flex items-center gap-2">
                      <span className="w-9 shrink-0 text-xs tabular-nums text-soft">{Math.round(participant.progress)}%</span>
                      <ProgressBar value={participant.progress} label={`${participant.name} progress`} className="w-14" />
                    </div>
                  </td>
                  {participant.badges.map((status, index) => {
                    const name = badges[index]?.name ?? `Badge ${index + 1}`;
                    return (
                      <td key={status.badgeKey} className="border-b border-line px-0 py-2.5 text-center">
                        {status.earned ? (
                          <span className="mx-auto flex h-5 w-5 items-center justify-center rounded-[3px] bg-accent text-ink" role="img" aria-label={`${name}: earned`}>
                            <Check className="h-3.5 w-3.5" strokeWidth={3} aria-hidden />
                          </span>
                        ) : (
                          <span className="mx-auto block h-1.5 w-1.5 rounded-full bg-[#BDBDBD]" role="img" aria-label={`${name}: pending`} />
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}
