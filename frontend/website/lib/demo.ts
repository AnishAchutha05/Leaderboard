import type { Badge, LeaderboardData, Participant } from "./types";

/* PREVIEW ONLY. Used when the API is unreachable, and always labelled "Demo data" in the UI. */

const BADGE_NAMES = [
  "Get Started with Cloud Storage",
  "Cloud Run Functions",
  "Networking Fundamentals on Google Cloud",
  "Build Infrastructure with Terraform",
  "Cloud IAM Essentials",
  "Google Kubernetes Engine Basics",
  "Cloud SQL for MySQL",
  "BigQuery for Data Analysis",
  "Vertex AI Fundamentals",
  "Implement Load Balancing",
  "Monitor and Log with Cloud Operations",
  "Prompt Design in Vertex AI",
];

const NAMES = [
  "Aarav Nair", "Diya Menon", "Rohan Kulkarni", "Ishita Rao", "Kabir Shetty", "Meera Iyer", "Arjun Hegde",
  "Sneha Patil", "Vihaan Reddy", "Ananya Gowda", "Nikhil Bhat", "Tanvi Joshi", "Aditya Murthy", "Kavya Prabhu",
  "Siddharth Kamath", "Pooja Naik", "Harsh Vardhan", "Riya Deshpande", "Manav Singh", "Lakshmi Narayan",
  "Yash Gupta", "Shreya Kini", "Dev Malhotra", "Navya Shenoy", "Pranav Rao", "Aisha Khan", "Varun Acharya",
  "Divya Pai", "Karthik Subramanian", "Neha Bhandari",
];

export function buildDemo(): LeaderboardData {
  const badges: Badge[] = BADGE_NAMES.map((name, i) => ({ id: `b${i}`, name, url: "https://www.cloudskillsboost.google/" }));
  const counts = [12, 12, 11, 10, 10, 9, 9, 8, 8, 7, 7, 6, 6, 6, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1, 0, 0];

  const participants: Participant[] = NAMES.map((name, i) => {
    const completed = counts[i];
    const map: Participant["badges"] = {};
    badges.forEach((b, j) => {
      // earn a deterministic subset of `completed` badges
      const earned = (j + i * 5) % badges.length < completed;
      const day = 1 + ((i * 3 + j * 2) % 27);
      map[b.id] = { earned, date: earned ? `2026-11-${String(day).padStart(2, "0")}` : null };
    });
    const earnedCount = Object.values(map).filter((b) => b.earned).length;
    return {
      key: `demo-${i}`,
      index: null,
      rank: i + 1,
      name,
      email: `${name.toLowerCase().replace(/\s+/g, ".")}@example.com`,
      profileUrl: "https://www.cloudskillsboost.google/",
      completed: earnedCount,
      total: badges.length,
      progress: (earnedCount / badges.length) * 100,
      badges: map,
    };
  });

  return { badges, participants, lastUpdated: new Date().toISOString(), demo: true };
}
