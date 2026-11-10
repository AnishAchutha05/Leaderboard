import type { Badge, BadgeStatus, LeaderboardData, Participant } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

interface ApiCourseLab {
  lab_name: string;
  badge_name: string | null;
  lab_url: string | null;
  credits: number;
  item_type: "Course" | "Challenge Lab";
}

interface ApiCourseResponse {
  total_labs: number;
  labs: ApiCourseLab[];
}

interface ApiProgressLab {
  lab_name: string;
  badge_name: string;
  lab_url: string | null;
  status: "Done" | "Pending";
  earned_badge: string | null;
  earned_date: string | null;
}

interface ApiCompletionBadge {
  badge_id: string;
  badge_name: string;
  date: string | null;
  status: "Done";
}

interface ApiParticipant {
  name: string;
  email: string | null;
  profile_url: string;
  participant_index: number;
  badges: ApiCompletionBadge[];
  progress: {
    total_labs: number;
    completed_labs: number;
    pending_labs: number;
    progress_percentage: number;
    labs: ApiProgressLab[];
  };
  last_checked: string | null;
  status: string;
  completed_badges: number;
  pending_badges: number;
  total_badges: number;
  progress_percentage: number;
  rank: number;
}

interface ApiLeaderboardResponse {
  total_participants: number;
  displayed_participants: number;
  leaderboard: ApiParticipant[];
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new Error(`Cannot reach the API at ${API_URL}. Check that the backend is running and CORS allows this site.`);
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : response.statusText;
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function expectArray<T>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) throw new Error(`Unexpected API response: ${label} must be an array.`);
  return value as T[];
}

function normalizeName(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/\s+/g, " ");
}

function readCourse(value: unknown): ApiCourseResponse {
  if (!isRecord(value) || !Array.isArray(value.labs)) {
    throw new Error("Unexpected /api/course response: expected { total_labs, labs }.");
  }
  return { total_labs: Number(value.total_labs) || 0, labs: value.labs as ApiCourseLab[] };
}

function readLeaderboard(value: unknown): ApiLeaderboardResponse {
  if (!isRecord(value) || !Array.isArray(value.leaderboard)) {
    throw new Error("Unexpected /api/leaderboard response: expected { total_participants, displayed_participants, leaderboard }.");
  }
  return {
    total_participants: Number(value.total_participants) || 0,
    displayed_participants: Number(value.displayed_participants) || 0,
    leaderboard: value.leaderboard as ApiParticipant[],
  };
}

function buildBadgeCatalog(labs: ApiCourseLab[], rows: ApiParticipant[]): Badge[] {
  const idsByName = new Map<string, Set<string>>();
  for (const participant of rows) {
    for (const earned of participant.badges ?? []) {
      const name = normalizeName(earned.badge_name);
      if (!name || !earned.badge_id) continue;
      const ids = idsByName.get(name) ?? new Set<string>();
      ids.add(earned.badge_id);
      idsByName.set(name, ids);
    }
  }

  const catalog = new Map<string, Badge>();
  for (const lab of labs) {
    const name = lab.badge_name?.trim();
    if (!name) continue;
    const matchingIds = idsByName.get(normalizeName(name));
    const actualId = matchingIds?.size === 1 ? [...matchingIds][0] : undefined;
    // The verified /api/course JSON has no badge_id. Use the actual ID if one
    // is supplied by a participant completion; otherwise the backend lab URL
    // is only a local React/matching key, never presented as a Google badge ID.
    const key = actualId ?? (lab.lab_url ? `lab:${lab.lab_url}` : `name:${normalizeName(name)}`);
    if (!catalog.has(key)) catalog.set(key, { key, id: actualId ?? key, name, url: lab.lab_url ?? undefined });
  }

  // Include genuine completed badge rows returned by the backend even if no
  // matching course row was returned. These IDs come directly from badges[].
  for (const participant of rows) {
    for (const earned of participant.badges ?? []) {
      if (!earned.badge_id || !earned.badge_name) continue;
      const alreadyPresent = [...catalog.values()].some(
        (badge) => badge.id === earned.badge_id || normalizeName(badge.name) === normalizeName(earned.badge_name),
      );
      if (!alreadyPresent) {
        catalog.set(earned.badge_id, { key: earned.badge_id, id: earned.badge_id, name: earned.badge_name });
      }
    }
  }
  return [...catalog.values()];
}

function participantBadges(row: ApiParticipant, catalog: Badge[]): BadgeStatus[] {
  const progressLabs = row.progress?.labs ?? [];
  const completions = row.badges ?? [];
  return catalog.map((badge) => {
    const completion = completions.find(
      (entry) => entry.badge_id === badge.id || normalizeName(entry.badge_name) === normalizeName(badge.name),
    );
    const lab = progressLabs.find(
      (entry) => (entry.lab_url && entry.lab_url === badge.url)
        || normalizeName(entry.badge_name) === normalizeName(badge.name),
    );
    const earned = Boolean(completion) || lab?.status === "Done";
    return {
      badgeKey: badge.key,
      earned,
      earnedDate: completion?.date ?? (earned ? lab?.earned_date ?? undefined : undefined),
      url: lab?.lab_url ?? badge.url,
    };
  });
}

function buildParticipants(rows: ApiParticipant[], catalog: Badge[]): Participant[] {
  return rows.map((row) => {
    const badges = participantBadges(row, catalog);
    const completed = badges.filter((badge) => badge.earned).length;
    const total = catalog.length;
    return {
      key: String(row.participant_index),
      index: row.participant_index,
      rank: row.rank,
      name: row.name,
      email: row.email ?? undefined,
      profileUrl: row.profile_url || undefined,
      completed,
      total,
      progress: total > 0 ? (completed / total) * 100 : 0,
      badges,
    };
  });
}

/** Fetch and normalize the exact response structures currently returned by FastAPI. */
export async function fetchLeaderboardData(): Promise<LeaderboardData> {
  const [courseRaw, leaderboardRaw] = await Promise.all([
    request<unknown>("/api/course"),
    request<unknown>("/api/leaderboard"),
  ]);
  const course = readCourse(courseRaw);
  const leaderboard = readLeaderboard(leaderboardRaw);
  const rows = expectArray<ApiParticipant>(leaderboard.leaderboard, "leaderboard");
  const badges = buildBadgeCatalog(course.labs, rows);
  const participants = buildParticipants(rows, badges);
  const updatedAt = rows
    .map((row) => row.last_checked)
    .filter((timestamp): timestamp is string => Boolean(timestamp))
    .sort()
    .at(-1);

  return { badges, participants, updatedAt, isDemo: false };
}

/** Source-compatible helper for display assertions and tests. */
export type { BadgeStatus };
