
from datetime import datetime, timezone


def parse_earned_date(date_value):
    """Convert an earned date into a comparable datetime."""

    if not date_value:
        return None

    if isinstance(date_value, datetime):
        return date_value.replace(tzinfo=timezone.utc) if date_value.tzinfo is None else date_value

    formats = [
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z"
    ]

    for date_format in formats:
        try:
            parsed = datetime.strptime(str(date_value), date_format)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed
        except ValueError:
            continue

    return None


def get_participant_stats(participant: dict) -> dict:
    """Calculate ranking statistics for one participant."""

    progress = participant.get("progress", {})
    labs = progress.get("labs", [])

    completed_labs = [
        lab for lab in labs
        if lab.get("status") == "Done"
    ]

    earned_dates = [
        parse_earned_date(lab.get("earned_date"))
        for lab in completed_labs
    ]

    valid_dates = [
        date for date in earned_dates
        if date is not None
    ]

    latest_completion = max(valid_dates) if valid_dates else None

    return {
        **participant,
        "completed_badges": len(completed_labs),
        "pending_badges": len(labs) - len(completed_labs),
        "total_badges": len(labs),
        "progress_percentage": (
            round(len(completed_labs) / len(labs) * 100, 2)
            if labs else 0
        ),
        "first_completion": min(valid_dates) if valid_dates else None,
        "latest_completion": latest_completion,
        "all_dates_available": (
            len(valid_dates) == len(completed_labs)
        )
    }


def rank_participants(participants: list[dict]) -> list[dict]:
    """
    Rank participants using:
    1. Highest completed badge count.
    2. Earliest date they completed their current badge count.
    3. Alphabetical name as deterministic tie-breaker.

    Participants with incomplete or missing earned dates are
    placed after participants with reliable timestamps when
    their badge counts are equal.
    """

    ranked = [
        get_participant_stats(participant)
        for participant in participants
    ]

    def sort_key(participant):
        count = participant["completed_badges"]

        if count == 0:
            completion_time = float("inf")
            missing_date = 0
        else:
            completion_time = (
                participant["latest_completion"].timestamp()
                if participant["all_dates_available"]
                and participant["latest_completion"]
                else float("inf")
            )
            missing_date = 0 if completion_time != float("inf") else 1

        return (
            -count,
            missing_date,
            completion_time,
            participant.get("name", "").casefold()
        )

    ranked.sort(key=sort_key)

    for position, participant in enumerate(ranked, start=1):
        participant["rank"] = position

        # Datetime objects are converted to strings for API/JSON output.
        for field in ("first_completion", "latest_completion"):
            if participant[field]:
                participant[field] = participant[field].isoformat()

        participant.pop("all_dates_available", None)

    return ranked


def get_leaderboard(
    participants: list[dict],
    limit: int | None = None
) -> dict:
    """Return the leaderboard, optionally limited to the top N."""

    ranked = rank_participants(participants)

    if limit is not None:
        if limit <= 0:
            raise ValueError("Leaderboard limit must be positive.")

        visible_participants = ranked[:limit]
    else:
        visible_participants = ranked

    return {
        "total_participants": len(ranked),
        "displayed_participants": len(visible_participants),
        "leaderboard": visible_participants
    }
