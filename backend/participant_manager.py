
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

if __package__:
    from .scraper import scrape_badges
    from .course_parser import parse_course
    from .badge_matcher import match_badges
else:  # Preserve direct script/module use from the backend directory.
    from scraper import scrape_badges
    from course_parser import parse_course
    from badge_matcher import match_badges


def validate_profile_url(url: str) -> bool:
    """Check whether a Google Skills public profile URL is valid."""
    if not url:
        return False
    parsed = urlparse(url.strip())
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() in {"www.skills.google", "skills.google"}
        and bool(re.fullmatch(r"/public_profiles/[a-zA-Z0-9-]+/?", parsed.path))
    )


def create_participant(name: str, email: str, profile_url: str) -> dict:
    """Create a standardized participant record."""

    return {
        "name": name.strip(),
        "email": email.strip().lower(),
        "profile_url": profile_url.strip(),
        "badges": [],
        "progress": {},
        "last_checked": None,
        "status": "Not Checked"
    }


def process_participant(
    participant: dict,
    required_labs: list[dict] | None = None
) -> dict:
    """
    Scrape a participant's profile and calculate course progress.
    """

    profile_url = participant.get("profile_url", "")

    if not validate_profile_url(profile_url):
        participant["status"] = "Invalid Profile URL"
        return participant

    try:
        if required_labs is None:
            required_labs = parse_course()

        earned_badges = scrape_badges(profile_url)

        progress = match_badges(
            required_labs,
            earned_badges
        )

        participant["badges"] = earned_badges
        participant["progress"] = progress
        participant["last_checked"] = datetime.now(
            timezone.utc
        ).isoformat()
        participant["status"] = "Success"

    except Exception as error:
        participant["status"] = "Failed"
        participant["error"] = str(error)

    return participant


def process_participants(
    participants: list[dict],
    required_labs: list[dict] | None = None
) -> list[dict]:
    """Process multiple participants sequentially."""

    if required_labs is None:
        required_labs = parse_course()

    processed = []

    for participant in participants:
        result = process_participant(
            participant,
            required_labs
        )
        processed.append(result)

    return processed
