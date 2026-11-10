
from difflib import SequenceMatcher
import re


def normalize_name(name: str) -> str:
    """Normalize badge names for comparison."""
    if not name:
        return ""

    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", " ", name)

    return " ".join(name.split())


def similarity(first: str, second: str) -> float:
    """Calculate similarity between two normalized names."""
    return SequenceMatcher(
        None,
        normalize_name(first),
        normalize_name(second)
    ).ratio()


def match_badges(
    required_labs: list[dict],
    earned_badges: list[dict],
    fuzzy_threshold: float = 0.88
) -> dict:
    """
    Match required course labs against a participant's earned badges.

    Exact matches are preferred. Fuzzy matches are accepted only
    when their similarity reaches the configured threshold.
    """

    results = []
    used_badges = set()

    for lab in required_labs:
        expected_name = lab.get("badge_name") or lab.get("lab_name") or ""
        expected_normalized = normalize_name(expected_name)

        best_match = None
        best_score = 0
        best_index = None
        match_type = None

        # First, look for an exact match.
        for index, badge in enumerate(earned_badges):
            if index in used_badges:
                continue

            earned_name = badge.get("badge_name", "")

            if normalize_name(earned_name) == expected_normalized:
                best_match = badge
                best_index = index
                best_score = 1.0
                match_type = "exact"
                break

        # If no exact match exists, check for a sufficiently
        # similar badge name.
        if best_match is None:
            for index, badge in enumerate(earned_badges):
                if index in used_badges:
                    continue

                earned_name = badge.get("badge_name", "")
                score = similarity(expected_name, earned_name)

                if score > best_score:
                    best_score = score
                    best_match = badge
                    best_index = index

            if best_match and best_score >= fuzzy_threshold:
                match_type = "fuzzy"
            else:
                best_match = None
                best_index = None

        if best_match:
            used_badges.add(best_index)

        results.append({
            "lab_name": lab.get("lab_name"),
            "badge_name": expected_name,
            "lab_url": lab.get("lab_url"),
            "credits": lab.get("credits", 0),
            "status": "Done" if best_match else "Pending",
            "earned_badge": (
                best_match.get("badge_name") if best_match else None
            ),
            "earned_date": (
                best_match.get("date") if best_match else None
            ),
            "match_type": match_type,
            "match_score": round(best_score, 2) if best_match else 0
        })

    total_labs = len(results)
    completed_labs = sum(
        1 for result in results if result["status"] == "Done"
    )

    total_credits = sum(
        (lab.get("credits") or 0) for lab in required_labs
    )

    earned_credits = sum(
        (result.get("credits") or 0)
        for result in results
        if result["status"] == "Done"
    )

    progress = (
        round((completed_labs / total_labs) * 100, 2)
        if total_labs else 0
    )

    return {
        "total_labs": total_labs,
        "completed_labs": completed_labs,
        "pending_labs": total_labs - completed_labs,
        "progress_percentage": progress,
        "total_credits": total_credits,
        "earned_credits": earned_credits,
        "labs": results
    }
