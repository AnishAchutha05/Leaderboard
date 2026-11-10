
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


BADGE_ID_PATTERN = re.compile(r"/(?:badges|badge)/([A-Za-z0-9_-]+)(?:/|$)", re.IGNORECASE)
EARNED_PATTERN = re.compile(
    r"Earned\s+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def _date_from_text(text: str) -> str | None:
    match = EARNED_PATTERN.search(text)
    return match.group(1).strip() if match else None


def badge_from_link(href: str, link_text: str, card_text: str) -> dict | None:
    """Build a badge only from an actual badge URL and identifiable title."""
    parsed_url = urlparse(href)
    match = BADGE_ID_PATTERN.search(parsed_url.path)
    if not match:
        return None

    title = (link_text or "").strip()
    generic_titles = {"badge", "view badge", "open badge", "share", "learn more"}
    if not title or title.casefold() in generic_titles:
        lines = [line.strip() for line in card_text.splitlines() if line.strip()]
        title = next(
            (line for line in lines
             if line.casefold() not in {"join", "sign in", *generic_titles}
             and not EARNED_PATTERN.search(line)),
            "",
        )
    if not title or title.casefold() in {"join", "sign in"}:
        return None

    return {
        "badge_id": match.group(1),
        "badge_name": title,
        "date": _date_from_text(card_text),
        "status": "Done",
        "url": href,
    }


def scrape_badges(url: str) -> list[dict]:
    """
    Scrape earned Google Skills badges from a public profile.
    Returns badge names and earned dates.
    """

    badges_by_id = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            page = browser.new_page()
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.locator("body").wait_for()
            page.wait_for_timeout(3000)

            anchors = page.locator("a[href]")
            for index in range(anchors.count()):
                anchor = anchors.nth(index)
                href = anchor.get_attribute("href") or ""
                link_text = (anchor.inner_text() or "").strip()
                card_text = link_text
                try:
                    card_text = anchor.locator("xpath=..").inner_text()
                except Exception:
                    pass
                badge = badge_from_link(href, link_text, card_text)
                if badge:
                    badges_by_id[badge["badge_id"]] = badge

            # Keep discovering anchors inside dynamically rendered badge cards.
            # Never synthesize an ID from a badge name; records without an actual
            # Google badge identifier are deliberately not returned for persistence.

        finally:
            browser.close()

    return list(badges_by_id.values())
