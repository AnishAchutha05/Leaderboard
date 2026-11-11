import type { Badge, BadgeStatus, LeaderboardData, Participant } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

interface ApiCourseLab {
  lab_name: string;
  name?: string;
  badge_name: string | null;
  badge_id: string;
  badge_url?: string | null;
  lab_url: string | null;
  url?: string;
  credits: number;
  total_credits?: number;
  item_type: "Course" | "Challenge Lab";
  category: "Completion" | "Skill";
}

interface ApiCourseResponse {
  total_labs: number;
  labs: ApiCourseLab[];
}

interface ApiProgressLab {
  lab_name: string;
  badge_name: string;
  badge_id?: string;
  badge_url?: string | null;
  lab_url: string | null;
  item_type?: "Course" | "Challenge Lab";
  credits?: number;
  total_credits?: number;
  category?: "Completion" | "Skill";
  status: "Done" | "Pending";
  earned_badge: string | null;
  earned_date: string | null;
}

interface ApiCompletionBadge {
  badge_id: string;
  badge_name: string;
  badge_url?: string | null;
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

function buildBadgeCatalog(labs: ApiCourseLab[]): Badge[] {
  return labs.map((lab) => {
    const url = lab.lab_url ?? lab.url ?? undefined;
    const name = (lab.name ?? lab.lab_name).trim();
    return {
      key: url ?? `course:${normalizeName(name)}`,
      name,
      itemType: lab.item_type,
      credits: Number(lab.total_credits ?? lab.credits),
      category: lab.category,
      url,
      badgeId: lab.badge_id,
      badgeUrl: lab.badge_url ?? undefined,
    };
  });
}

function participantBadges(row: ApiParticipant, catalog: Badge[]): BadgeStatus[] {
  const progressLabs = row.progress?.labs ?? [];
  const completions = row.badges ?? [];
  return catalog.map((badge) => {
    const lab = progressLabs.find(
      (entry) => (entry.lab_url && entry.lab_url === badge.url)
        || (!entry.lab_url && normalizeName(entry.lab_name) === normalizeName(badge.name)),
    );
    // Per-user completions carry issuance-specific Google badge IDs. The
    // persisted completion.lab_id is authoritative for the catalogue row.
    const completion = completions.find(
      (entry) => entry.badge_id === lab?.badge_id
        || normalizeName(entry.badge_name) === normalizeName(lab?.earned_badge ?? ""),
    );
    const earned = lab?.status === "Done";
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
  const badges = buildBadgeCatalog(course.labs);
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
