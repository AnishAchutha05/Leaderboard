"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CheckCircle2, TriangleAlert } from "lucide-react";
import { fetchLeaderboardData } from "@/lib/api";
import { formatUpdated } from "@/lib/format";
import type { LeaderboardData } from "@/lib/types";
import Header from "@/components/Header";
import OverviewStats from "@/components/OverviewStats";
import Podium from "@/components/Podium";
import LeaderboardFilters, { type Filter } from "@/components/LeaderboardFilters";
import Leaderboard from "@/components/Leaderboard";
import ParticipantDetails from "@/components/ParticipantDetails";

interface ToastState {
  kind: "ok" | "err";
  text: string;
}

export default function Page() {
  const [data, setData] = useState<LeaderboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backgroundError, setBackgroundError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const showToast = useCallback((nextToast: ToastState) => setToast(nextToast), []);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

  const load = useCallback(async () => {
    try {
      const next = await fetchLeaderboardData();
      setData(next);
      setError(null);
      setBackgroundError(null);
      setFetchedAt(new Date());
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the leaderboard.");
      setData(null);
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Loading remote API data is an effect; state updates occur after the fetch settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  /** Refresh is a read-only re-fetch; it never triggers a bulk profile scrape. */
  const refresh = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const next = await fetchLeaderboardData();
      setData(next);
      setError(null);
      setBackgroundError(null);
      setFetchedAt(new Date());
      showToast({ kind: "ok", text: "Leaderboard updated." });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Refresh failed.";
      if (data) {
        setBackgroundError(message);
      } else {
        setError(message);
      }
      showToast({ kind: "err", text: message });
    } finally {
      setRefreshing(false);
    }
  }, [refreshing, showToast, data]);

  // Automatic read-only leaderboard refresh every 60 seconds.
  useEffect(() => {
    let disposed = false;
    let inFlight = false;

    const poll = async () => {
      if (disposed || inFlight) return;
      inFlight = true;
      try {
        const next = await fetchLeaderboardData();
        if (disposed) return;
        setData(next);
        setError(null);
        setBackgroundError(null);
        setFetchedAt(new Date());
      } catch (cause) {
        // Keep the existing displayed leaderboard when a background poll fails,
        // but surface a subtle stale-data indication.
        if (disposed) return;
        setBackgroundError(
          cause instanceof Error ? cause.message : "Automatic refresh failed.",
        );
      } finally {
        inFlight = false;
      }
    };

    const intervalId = window.setInterval(() => {
      void poll();
    }, 60_000);

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const all = useMemo(() => data?.participants ?? [], [data]);
  const sliced = useMemo(() => filter === "all" ? all : all.slice(0, Number(filter)), [all, filter]);
  const visible = useMemo(() => {
    const value = query.trim().toLocaleLowerCase();
    if (!value) return sliced;
    return sliced.filter((participant) => participant.name.toLocaleLowerCase().includes(value));
  }, [sliced, query]);
  const selected = selectedKey ? all.find((participant) => participant.key === selectedKey) ?? null : null;
  const updatedLabel = formatUpdated(data?.updatedAt) ?? formatUpdated(fetchedAt ?? undefined);
  const closeDetails = useCallback(() => setSelectedKey(null), []);

  return (
    <>
      <Header lastUpdated={updatedLabel} />

      <main>
        <div className="mx-auto max-w-[1400px] px-4 sm:px-6">
          <section className="flex items-end justify-between gap-6 pb-6 pt-8 sm:pb-8 sm:pt-12">
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-faint">
                Google Cloud Skills Boost · Live
              </p>
              <h1 className="mt-3 text-[64px] font-bold leading-[0.9] tracking-tighter sm:text-[104px] lg:text-[136px]">
                <span className="sr-only">Google Skills Leaderboard </span>
                <span aria-hidden>skills<span className="text-accent">.</span></span>
              </h1>
              <p className="mt-4 max-w-md text-sm text-soft sm:text-base">
                Every lab finished, every badge earned, ranked live. Tap anyone to see exactly where they stand.
              </p>
            </div>
            <p
              className="hidden shrink-0 border-r-2 border-ink pr-3 text-right text-[11px] font-bold uppercase leading-snug tracking-[0.18em] sm:block"
              style={{ writingMode: "vertical-rl" }}
              aria-hidden
            >
              Track — Learn — Achieve
            </p>
          </section>

          {error && (
            <div role="alert" className="mb-4 flex items-start gap-3 rounded-lg border border-[#E93E32] bg-[#FDECEA] p-3 text-sm text-[#9B1C12]">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <div className="min-w-0">
                <p className="font-semibold">Couldn&apos;t load the leaderboard</p>
                <p className="break-words">{error}</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setLoading(true);
                  void load();
                }}
                className="ml-auto h-9 shrink-0 rounded-sm border border-[#9B1C12] px-3 font-medium hover:bg-[#9B1C12] hover:text-white"
              >
                Retry
              </button>
            </div>
          )}

          {!loading && data && backgroundError && !error && (
            <div role="status" className="mb-4 flex items-start gap-3 rounded-lg border border-[#B45309] bg-[#FFFBEB] p-3 text-sm text-[#92400E]">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <div className="min-w-0">
                <p className="font-semibold">Showing last successfully loaded leaderboard</p>
                <p className="break-words">Automatic refresh failed: {backgroundError}</p>
              </div>
            </div>
          )}

          {data?.isDemo && (
            <div role="status" className="mb-4 flex items-start gap-3 rounded-lg border border-ink bg-[#FFD84D] p-3 text-sm text-ink">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <p><span className="font-semibold">Demo preview. </span>This data is generated and is not from the backend.</p>
            </div>
          )}

          <OverviewStats data={loading ? null : data} />
        </div>

        <div className="mt-6 sm:mt-8">
          <Podium top={all} loading={loading} onSelect={(participant) => setSelectedKey(participant.key)} />
        </div>

        <div className="mx-auto max-w-[1400px] px-4 pb-10 pt-6 sm:px-6 sm:pt-8">
          <section aria-label="Ranking" className="overflow-hidden rounded-xl border border-line bg-white shadow-card">
            <div className="space-y-4 border-b border-line p-4 sm:p-5">
              <div className="flex items-end justify-between">
                <h2 className="text-3xl font-bold tracking-tighter sm:text-4xl">ranking<span className="text-accent">.</span></h2>
                <ArrowUpRight className="hidden h-6 w-6 text-ink sm:block" aria-hidden />
              </div>
              <LeaderboardFilters
                filter={filter}
                onFilter={setFilter}
                query={query}
                onQuery={setQuery}
                onRefresh={refresh}
                refreshing={refreshing}
                visible={visible.length}
                total={all.length}
                updatedLabel={updatedLabel}
              />
            </div>

            <Leaderboard
              participants={visible}
              badges={data?.badges ?? []}
              loading={loading}
              searching={query.trim().length > 0}
              onSelect={(participant) => setSelectedKey(participant.key)}
            />
          </section>

          <p className="mt-6 text-center text-xs text-faint">GDG on Campus · JSSATE-B · Rankings come straight from the backend.</p>
        </div>
      </main>

      {selected && data && <ParticipantDetails participant={selected} badges={data.badges} onClose={closeDetails} />}

      {toast && (
        <div
          role="status"
          className={`anim-toast fixed bottom-6 left-1/2 z-[60] flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-2 rounded-sm px-4 py-3 text-sm font-medium shadow-pop ${
            toast.kind === "ok" ? "bg-ink text-white" : "bg-[#E93E32] text-white"
          }`}
        >
          {toast.kind === "ok" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden /> : <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />}
          <span className="min-w-0 break-words">{toast.text}</span>
        </div>
      )}
    </>
  );
}
