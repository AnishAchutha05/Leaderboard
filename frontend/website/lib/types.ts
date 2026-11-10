export interface Badge {
  /** Stable UI key. Uses a Google badge ID when supplied, otherwise a source lab URL key. */
  key: string;
  id: string;
  name: string;
  url?: string;
}

export interface BadgeStatus {
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
