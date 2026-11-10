import { RefreshCw, Search, X } from "lucide-react";

export type Filter = "10" | "100" | "250" | "all";

const OPTIONS: { id: Filter; label: string }[] = [
  { id: "10", label: "Top 10" },
  { id: "100", label: "Top 100" },
  { id: "250", label: "Top 250" },
  { id: "all", label: "All" },
];

interface Props {
  filter: Filter;
  onFilter: (filter: Filter) => void;
  query: string;
  onQuery: (query: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
  visible: number;
  total: number;
  updatedLabel?: string;
}

export default function LeaderboardFilters({ filter, onFilter, query, onQuery, onRefresh, refreshing, visible, total, updatedLabel }: Props) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
      <div role="tablist" aria-label="Leaderboard size" className="grid w-full grid-cols-4 rounded-sm border border-line bg-panel p-0.5 lg:w-auto">
        {OPTIONS.map((option) => {
          const active = option.id === filter;
          return (
            <button
              key={option.id}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => onFilter(option.id)}
              className={`on-dark h-10 whitespace-nowrap rounded-[2px] px-3 text-sm font-medium transition-colors duration-150 lg:px-4 ${active ? "bg-ink text-white" : "text-soft hover:bg-black/5"}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      <div className="relative w-full lg:max-w-xs lg:flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search participant name"
          aria-label="Search participants by name"
          className="h-10 w-full rounded-sm border border-line bg-white pl-9 pr-10 text-sm placeholder:text-faint [&::-webkit-search-cancel-button]:hidden"
        />
        {query && (
          <button type="button" onClick={() => onQuery("")} aria-label="Clear search" className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-sm text-faint hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex items-center gap-3 lg:ml-auto">
        <p className="text-sm tabular-nums text-faint" aria-live="polite"><span className="font-semibold text-ink">{visible}</span> of {total}</p>
        {updatedLabel && <p className="text-xs text-faint md:hidden">Updated {updatedLabel}</p>}
      </div>

      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        className="on-dark inline-flex h-10 w-full items-center justify-center gap-2 rounded-sm bg-ink px-4 text-sm font-medium text-white transition-colors duration-150 hover:bg-accent hover:text-ink disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-ink disabled:hover:text-white lg:w-auto"
      >
        <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden />
        {refreshing ? "Refreshing…" : "Refresh"}
      </button>
    </div>
  );
}
