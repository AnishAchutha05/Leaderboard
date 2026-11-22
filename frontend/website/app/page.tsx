import LeaderboardApp from "@/components/LeaderboardApp";
import { getInitialLeaderboard } from "@/lib/server-data";

export default async function Page() {
  const initialData = await getInitialLeaderboard();
  return <LeaderboardApp initialData={initialData} />;
}
