
import logging
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)

BADGE_ID_PATTERN = re.compile(r"/(?:badges|badge)/([A-Za-z0-9_-]+)(?:/|$)", re.IGNORECASE)
EARNED_PATTERN = re.compile(
    r"Earned\s+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

DEFAULT_LAUNCH_TIMEOUT_MS = 30_000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60_000
DEFAULT_OPERATION_TIMEOUT_MS = 120_000

_BADGE_CANDIDATE_SCRIPT = r"""
() => {
  const badgePathPattern = /\/(?:badges|badge)\/([A-Za-z0-9_-]+)(?:\/|$)/i;
  const results = [];
  const seen = new Set();

  const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const pushCandidate = (candidate) => {
    if (!candidate) return;
    const href = candidate.href || '';
    const linkText = normalize(candidate.linkText);
    const cardText = normalize(candidate.cardText);
    const key = `${href}|${linkText}|${cardText}`;
    if (seen.has(key)) return;
    seen.add(key);
    results.push({ href, linkText, cardText });
  };

  // Primary: actual profile badge-card structure.
  const badgeCards = Array.from(document.querySelectorAll(
    '.profile-badge, [class*="profile-badge"], ql-badge, [data-badge-id]'
  ));
  for (const card of badgeCards) {
    const anchor = card.querySelector(
      'a[href*="/badges/"], a[href*="/badge/"], a.badge-image, a[href]'
    );
    const titleEl = card.querySelector(
      '.ql-title-medium, .ql-headline-medium, [class*="title"], h1, h2, h3'
    );
    const dateEl = Array.from(card.querySelectorAll(
      '.ql-body-medium, [class*="body"], span, p, time'
    )).find((el) => /Earned/i.test((el.innerText || el.textContent || '')));
    const href = anchor ? (anchor.href || anchor.getAttribute('href') || '') : '';
    const title = normalize(
      (titleEl && (titleEl.innerText || titleEl.textContent)) || ''
    );
    const dateText = normalize(
      (dateEl && (dateEl.innerText || dateEl.textContent)) || ''
    );
    const cardText = normalize(card.innerText || card.textContent || '');
    const linkText = normalize(
      (anchor && (anchor.innerText || anchor.textContent)) || title
    );
    const combinedCardText = normalize([title, dateText, cardText].filter(Boolean).join('\n'));

    // Prefer genuine badge URLs when present; still emit card-structured data if
    // the card clearly represents an earned badge.
    if (badgePathPattern.test(href) || (/Earned/i.test(combinedCardText) && title)) {
      pushCandidate({
        href,
        linkText: linkText || title,
        cardText: combinedCardText || cardText,
      });
    }
  }

  // Fallback: any anchor that points to a genuine badge URL.
  const anchors = Array.from(document.querySelectorAll('a[href]'));
  for (const anchor of anchors) {
    const href = anchor.href || anchor.getAttribute('href') || '';
    if (!badgePathPattern.test(href)) {
      continue;
    }
    let cardText = normalize(anchor.innerText || anchor.textContent || '');
    try {
      const parent = anchor.closest('.profile-badge') || anchor.parentElement;
      if (parent && (parent.innerText || parent.textContent)) {
        cardText = normalize(parent.innerText || parent.textContent || '');
      }
    } catch (error) {
      // Ignore extraction issues for individual anchors.
    }
    pushCandidate({
      href,
      linkText: normalize(anchor.innerText || anchor.textContent || ''),
      cardText,
    });
  }

  return results;
}
"""


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
        lines = [line.strip() for line in (card_text or "").splitlines() if line.strip()]
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
        "date": _date_from_text(card_text or ""),
        "status": "Done",
        "url": href,
    }


def _extract_badges_from_candidates(candidates: list[dict]) -> list[dict]:
    badges_by_id = {}
    for candidate in candidates or []:
        badge = badge_from_link(
            candidate.get("href") or "",
            candidate.get("linkText") or "",
            candidate.get("cardText") or "",
        )
        if badge:
            badges_by_id[badge["badge_id"]] = badge
    return list(badges_by_id.values())


def scrape_badges(
    url: str,
    *,
    launch_timeout_ms: int = DEFAULT_LAUNCH_TIMEOUT_MS,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    operation_timeout_ms: int = DEFAULT_OPERATION_TIMEOUT_MS,
) -> list[dict]:
    """
    Scrape earned Google Skills badges from a public profile.

    Returns badge records for genuine badge links. A valid profile with no
    badges returns an empty list. Navigation, timeout, or browser failures raise
    exceptions so callers do not record a false successful empty result.
    """

    total_start = time.perf_counter()
    browser = None
    logger.info("Starting badge scrape for %s", url)

    try:
        with sync_playwright() as playwright:
            launch_start = time.perf_counter()
            try:
                browser = playwright.chromium.launch(
                    headless=True,
                    timeout=launch_timeout_ms,
                )
            except Exception as error:
                raise RuntimeError(f"Failed to launch browser for profile scrape: {error}") from error
            launch_duration = time.perf_counter() - launch_start
            logger.info("Browser launch completed in %.3fs", launch_duration)

            try:
                page = browser.new_page()
                page.set_default_timeout(operation_timeout_ms)
                page.set_default_navigation_timeout(navigation_timeout_ms)

                navigation_start = time.perf_counter()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout_ms)
                    page.locator("body").wait_for(state="attached", timeout=operation_timeout_ms)
                except PlaywrightTimeoutError as error:
                    raise TimeoutError(f"Timed out while loading profile page: {url}") from error
                except PlaywrightError as error:
                    raise RuntimeError(f"Failed to navigate to profile page: {error}") from error
                navigation_duration = time.perf_counter() - navigation_start
                logger.info("Navigation completed in %.3fs", navigation_duration)

                extraction_start = time.perf_counter()
                try:
                    candidates = page.evaluate(_BADGE_CANDIDATE_SCRIPT)
                except PlaywrightTimeoutError as error:
                    raise TimeoutError(f"Timed out while extracting badge data: {url}") from error
                except PlaywrightError as error:
                    raise RuntimeError(f"Browser error during badge extraction: {error}") from error
                extraction_duration = time.perf_counter() - extraction_start
                badges = _extract_badges_from_candidates(candidates)
                logger.info(
                    "DOM extraction completed in %.3fs (candidates=%d, badges=%d)",
                    extraction_duration,
                    len(candidates or []),
                    len(badges),
                )
            finally:
                close_start = time.perf_counter()
                try:
                    browser.close()
                except Exception:
                    logger.exception("Failed to close browser cleanly after scraping %s", url)
                logger.info("Browser closed in %.3fs", time.perf_counter() - close_start)

        total_duration = time.perf_counter() - total_start
        logger.info(
            "Scrape completed for %s in %.3fs with %d badge(s)",
            url,
            total_duration,
            len(badges),
        )
        return badges
    except Exception:
        total_duration = time.perf_counter() - total_start
        logger.exception("Scrape failed for %s after %.3fs", url, total_duration)
        raise

