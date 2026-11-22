import { cacheLife } from "next/cache";
import { fetchLeaderboardData } from "./api";
import type { LeaderboardData } from "./types";

/**
 * Leaderboard snapshot baked into the page HTML and refreshed in the
 * background about once a minute, so visitors see the board immediately
 * instead of waiting on the API. The client re-fetches after hydration.
 */
async function cachedLeaderboard(): Promise<LeaderboardData> {
  "use cache";
  cacheLife("minutes");
  return fetchLeaderboardData({ signal: AbortSignal.timeout(15_000) });
}

/** Returns null when the API is unreachable; the client then loads the data itself. */
export async function getInitialLeaderboard(): Promise<LeaderboardData | null> {
  try {
    return await cachedLeaderboard();
  } catch (cause) {
    console.error("Leaderboard prefetch failed; falling back to client fetch.", cause);
    return null;
  }
}
