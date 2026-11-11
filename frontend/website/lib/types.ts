export interface Badge {
  /** Stable UI key for the course/lab row. */
  key: string;
  name: string;
  itemType: "Course" | "Challenge Lab";
  credits: number;
  category: "Completion" | "Skill";
  url?: string;
  badgeId?: string;
  badgeUrl?: string;
}

export interface BadgeStatus {
  /** Uses the course/lab key, not profile-specific badge issuance IDs. */
  badgeKey: string;
  earned: boolean;
  earnedDate?: string;
  url?: string;
}

export interface Participant {
  key: string;
  /** Database user ID used by POST /api/participants/{id}/refresh. */
  index?: number;
  rank: number;
  name: string;
  email?: string;
  profileUrl?: string;
  completed: number;
  total: number;
  progress: number; // 0-100
  badges: BadgeStatus[];
}

export interface LeaderboardData {
  badges: Badge[];
  participants: Participant[];
  updatedAt?: string;
  isDemo: boolean;
}
