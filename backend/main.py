from datetime import datetime, timezone
import os
from pathlib import Path
import logging
import re
import tempfile
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

logger = logging.getLogger(__name__)

if __package__:
    from .course_parser import parse_course
    from .database.database import SessionLocal
    from .database.models import Badge, Completion, Lab, ScrapeLog, User
    from .excel_manager import load_participants
    from .leaderboard import get_leaderboard
    from .participant_manager import validate_profile_url
    from .scraper import (
        DEFAULT_LAUNCH_TIMEOUT_MS,
        DEFAULT_NAVIGATION_TIMEOUT_MS,
        DEFAULT_OPERATION_TIMEOUT_MS,
        scrape_badges,
    )
else:  # Keep `uvicorn main:app` from the backend directory working.
    from course_parser import parse_course
    from database.database import SessionLocal
    from database.models import Badge, Completion, Lab, ScrapeLog, User
    from excel_manager import load_participants
    from leaderboard import get_leaderboard
    from participant_manager import validate_profile_url
    from scraper import (
        DEFAULT_LAUNCH_TIMEOUT_MS,
        DEFAULT_NAVIGATION_TIMEOUT_MS,
        DEFAULT_OPERATION_TIMEOUT_MS,
        scrape_badges,
    )

app = FastAPI(
    title="Google Skills Badge Tracker",
    description="Track participant progress across Google Skills labs.",
    version="1.0.0",
)

def _parse_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins:
        origins = ["http://localhost:3000"]
    # Wildcard origins are not used with credentials enabled.
    if "*" in origins:
        logger.warning("Ignoring wildcard CORS origin because credentials are enabled.")
        origins = [origin for origin in origins if origin != "*"] or ["http://localhost:3000"]
    return origins


CORS_ALLOW_ORIGINS = _parse_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PARTICIPANT_SHEET = "Clean Participants"
COURSE_SHEET = "GCP Labs & Courses"


def _resolve_course_workbook_path() -> Path:
    configured = os.getenv("COURSE_WORKBOOK_PATH")
    if configured:
        return Path(configured).expanduser()
    for path in (
        DATA_DIR / "GCP_Labs_Courses_Professional.xlsx",
        DATA_DIR / "course.xlsx",
    ):
        if path.exists():
            return path
    # Sensible local default target path.
    return DATA_DIR / "course.xlsx"


def _resolve_participant_workbook_path() -> Path:
    configured = os.getenv("PARTICIPANT_WORKBOOK_PATH")
    if configured:
        return Path(configured).expanduser()
    return DATA_DIR / "clean_participants.xlsx"


COURSE_FILE = _resolve_course_workbook_path()
PARTICIPANT_FILE = _resolve_participant_workbook_path()


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


COURSE_BADGE_ALIASES = {
    _normalize_text("The Basics of Google Cloud Compute: Challenge Lab"): (
        "The Basics of Google Cloud Compute",
    ),
    _normalize_text("Develop with Apps Script and AppSheet: Challenge Lab"): (
        "Develop with Apps Script and AppSheet",
    ),
}


def _expected_badge_names(course_row: dict) -> set[str]:
    course_name = _normalize_text(course_row.get("lab_name"))
    aliases = COURSE_BADGE_ALIASES.get(course_name)
    if aliases:
        return {_normalize_text(name) for name in aliases}
    badge_name = course_row.get("badge_name")
    return {_normalize_text(badge_name or course_row.get("lab_name"))}


def _course_for_badge(course_rows: list[dict], badge_name: str) -> dict | None:
    normalized_name = _normalize_text(badge_name)
    matches = [
        row for row in course_rows
        if normalized_name in _expected_badge_names(row)
    ]
    return matches[0] if len(matches) == 1 else None


def _normalize_profile_url(value: str) -> str:
    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    return f"https://{host}{parsed.path.rstrip('/') }"


def _course_file_for_runtime() -> Path:
    # Re-resolve on each access so env/default discovery stays current.
    return _resolve_course_workbook_path()


def validate_course_workbook_exists(path: Path | None = None) -> Path:
    course_path = path or _course_file_for_runtime()
    if not course_path.exists():
        raise FileNotFoundError(
            f"Course workbook not found at '{course_path}'. "
            "Set COURSE_WORKBOOK_PATH or provide the workbook at the configured path."
        )
    return course_path


def _load_course_rows(course_path: Path | str | None = None):
    path = Path(course_path) if course_path is not None else _course_file_for_runtime()
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Course workbook not found: {path}. "
                "Set COURSE_WORKBOOK_PATH or provide the workbook at the configured path."
            ),
        )
    try:
        return parse_course(str(path), sheet_name=COURSE_SHEET)
    except ValueError as error:
        # Support earlier workbook exports whose active sheet had another name.
        try:
            return parse_course(str(path))
        except Exception:
            raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _import_users(db: Session, rows: list[dict]) -> dict:
    inserted = updated = 0
    invalid = []
    seen = set()
    existing_users = db.scalars(select(User)).all()
    existing_by_profile = {
        _normalize_profile_url(user.public_profile_url): user
        for user in existing_users
    }
    for row in rows:
        profile_url = row.get("profile_url") or ""
        if not validate_profile_url(profile_url):
            invalid.append({"row": row.get("source_row"), "reason": "Invalid public profile URL"})
            continue
        key = _normalize_profile_url(profile_url)
        if key in seen:
            invalid.append({"row": row.get("source_row"), "reason": "Duplicate public profile URL in workbook"})
            continue
        seen.add(key)

        user = existing_by_profile.get(key)
        if user is None:
            user = User(name=row["name"], email=row.get("email"), public_profile_url=profile_url)
            db.add(user)
            existing_by_profile[key] = user
            inserted += 1
        else:
            user.name = row["name"]
            user.email = row.get("email")
            user.public_profile_url = profile_url
            updated += 1
    db.flush()
    return {"inserted": inserted, "updated": updated, "skipped": len(invalid), "issues": invalid}


def _import_course_rows(db: Session, course_rows: list[dict]) -> dict:
    imported = 0
    unresolved = []
    known_badges = db.scalars(select(Badge)).all()
    for row in course_rows:
        expected_names = _expected_badge_names(row)
        matches = [badge for badge in known_badges if _normalize_text(badge.name) in expected_names]
        if len(matches) != 1:
            # Multiple actual issuance IDs can refer to the same verified badge
            # title across profiles. They are equivalent for this one lab's
            # display association; retain a stable canonical representative.
            normalized_names = {_normalize_text(badge.name) for badge in matches}
            if matches and len(normalized_names) == 1:
                matches.sort(key=lambda badge: badge.id)
            else:
                unresolved.append({
                    "row": row.get("source_row"),
                    "name": row["lab_name"],
                    "reason": (
                        "No unique exact-name match to a badge ID scraped from a public profile."
                        if matches else
                        "No verified badge ID yet for the course's exact badge name/approved alias."
                    ),
                })
                continue
        badge = matches[0]

        lab = db.scalar(select(Lab).where(Lab.url == (row.get("lab_url") or "")))
        if lab is None:
            lab = Lab(
                name=row["lab_name"],
                item_type=row["item_type"],
                total_credits=row["credits"],
                url=row.get("lab_url") or "",
                badge_id=badge.id,
            )
            db.add(lab)
        else:
            # Keep the existing, verified FK association if another profile's
            # actual badge issuance ID is encountered for the same badge name.
            lab.name = row["lab_name"]
            lab.item_type = row["item_type"]
            lab.total_credits = row["credits"]
            if _normalize_text(lab.badge.name) not in expected_names:
                lab.badge_id = badge.id
        imported += 1
    db.flush()
    return {"imported": imported, "unresolved": unresolved}


def _import_verified_badges(db: Session, records: list[dict]) -> dict:
    inserted = updated = 0
    rejected = []
    for record in records:
        badge_id = str(record.get("badge_id") or "").strip()
        badge_name = str(record.get("badge_name") or "").strip()
        badge_url = str(record.get("badge_url") or "").strip()
        parsed_url = urlparse(badge_url)
        actual_id = re.search(r"/badges/([A-Za-z0-9_-]+)/?$", parsed_url.path)
        if (
            not badge_id or not badge_name or not actual_id
            or actual_id.group(1) != badge_id
            or parsed_url.scheme != "https"
            or parsed_url.netloc.lower() not in {"skills.google", "www.skills.google"}
        ):
            rejected.append({"badge_id": badge_id or None, "name": badge_name or None,
                             "reason": "Badge ID and URL did not verify against an actual Google Skills badge link."})
            continue

        category = record.get("category")
        if category not in {"Completion", "Skill"}:
            rejected.append({"badge_id": badge_id, "name": badge_name,
                             "reason": "Missing valid category from the authoritative course catalogue."})
            continue
        badge = db.get(Badge, badge_id)
        if badge is None:
            db.add(Badge(id=badge_id, name=badge_name, category=category))
            inserted += 1
        else:
            badge.name = badge_name
            badge.category = category
            updated += 1
    db.flush()
    return {"inserted": inserted, "updated": updated, "rejected": rejected}


def _date_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    for pattern in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(str(value), pattern)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            continue
    return None


def _serialize_users(db: Session) -> list[dict]:
    users = db.scalars(select(User).options(
        joinedload(User.completions).joinedload(Completion.badge),
        joinedload(User.completions).joinedload(Completion.lab),
    ).order_by(User.id)).unique().all()
    labs_by_id = db.scalars(select(Lab).options(joinedload(Lab.badge)).order_by(Lab.id)).unique().all()
    latest_logs = {}
    for log in db.scalars(select(ScrapeLog).order_by(ScrapeLog.user_id, ScrapeLog.id)):
        latest_logs[log.user_id] = log
    course_rows = []
    for user in users:
        completions = [completion for completion in user.completions if completion.is_completed]
        labs = []
        for lab in labs_by_id:
            # Badge IDs are issuance IDs and differ between learners. The
            # verified association for a participant is the completion's FK
            # to this lab, not equality with the lab's canonical badge ID.
            completion = next((item for item in completions if item.lab_id == lab.id), None)
            labs.append({
                "lab_name": lab.name,
                "name": lab.name,
                "badge_name": lab.badge.name,
                "badge_id": lab.badge.id,
                "lab_url": lab.url,
                "url": lab.url,
                "credits": lab.total_credits,
                "total_credits": lab.total_credits,
                "item_type": lab.item_type,
                "category": "Completion" if lab.item_type == "Course" else "Skill",
                "status": "Done" if completion else "Pending",
                "earned_badge": lab.badge.name if completion else None,
                "earned_date": completion.earned_at.isoformat() if completion and completion.earned_at else None,
                "match_type": "database" if completion else None,
                "match_score": 1 if completion else 0,
            })
        progress = {
            "total_labs": len(labs),
            "completed_labs": sum(item["status"] == "Done" for item in labs),
            "pending_labs": sum(item["status"] != "Done" for item in labs),
            "progress_percentage": (sum(item["status"] == "Done" for item in labs) / len(labs) * 100) if labs else 0,
            "labs": labs,
        }
        course_rows.append({
            "name": user.name,
            "email": user.email,
            "profile_url": user.public_profile_url,
            "participant_index": user.id,
            "badges": [
                {"badge_id": item.badge_id, "badge_name": item.badge.name,
                 "date": item.earned_at.isoformat() if item.earned_at else None, "status": "Done"}
                for item in completions
            ],
            "progress": progress,
            "last_checked": latest_logs[user.id].finished_at if user.id in latest_logs else None,
            "status": latest_logs[user.id].status if user.id in latest_logs else "Not Checked",
        })
    return course_rows


def _process_user(
    user_id: int,
    *,
    launch_timeout_ms: int = DEFAULT_LAUNCH_TIMEOUT_MS,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    operation_timeout_ms: int = DEFAULT_OPERATION_TIMEOUT_MS,
    course_rows: list[dict] | None = None,
) -> dict:
    started_at = datetime.now(timezone.utc)
    logger.info("Participant lookup started for user_id=%s", user_id)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            logger.warning("Participant lookup failed: user_id=%s not found", user_id)
            raise HTTPException(status_code=404, detail="Participant not found.")
        profile_url = user.public_profile_url
    logger.info("Participant lookup completed for user_id=%s profile_url=%s", user_id, profile_url)

    try:
        if not validate_profile_url(profile_url):
            raise ValueError("Invalid public profile URL")
        logger.info("Scrape started for user_id=%s", user_id)
        earned_badges = scrape_badges(
            profile_url,
            launch_timeout_ms=launch_timeout_ms,
            navigation_timeout_ms=navigation_timeout_ms,
            operation_timeout_ms=operation_timeout_ms,
        )
        logger.info(
            "Scrape completed for user_id=%s with %d badge(s)",
            user_id,
            len(earned_badges),
        )

        if course_rows is None:
            logger.info("Course loading started for user_id=%s", user_id)
            course_rows = _load_course_rows()
            logger.info("Course loading completed for user_id=%s with %d row(s)", user_id, len(course_rows))
        else:
            logger.info("Using cached course rows for user_id=%s (%d row(s))", user_id, len(course_rows))

        finished_at = datetime.now(timezone.utc)
        new_badges = 0
        unresolved = []

        logger.info("Database persistence started for user_id=%s", user_id)
        with SessionLocal.begin() as db:
            user = db.get(User, user_id)
            seen_badge_ids = set()
            for earned in earned_badges:
                badge_id = str(earned.get("badge_id") or "").strip()
                badge_name = str(earned.get("badge_name") or "").strip()
                if not badge_id or not badge_name:
                    unresolved.append({"badge": badge_name or None, "reason": "Scraper found no actual Google badge ID or name."})
                    continue
                if badge_id in seen_badge_ids:
                    continue
                seen_badge_ids.add(badge_id)

                course_row = _course_for_badge(course_rows, badge_name)
                category = (course_row or {}).get("category") or "Unclassified"
                badge = db.get(Badge, badge_id)
                if badge is None:
                    badge = Badge(id=badge_id, name=badge_name, category=category)
                    db.add(badge)
                    db.flush()
                    new_badges += 1
                else:
                    badge.name = badge_name
                    if category != "Unclassified":
                        badge.category = category

                # The workbook does not supply badge IDs. Only create a lab
                # relation when its title exactly matches a real scraped badge
                # or one of the explicit Challenge Lab title aliases above.
                if course_row is not None:
                    lab = db.scalar(select(Lab).where(Lab.url == (course_row.get("lab_url") or "")))
                    if lab is None:
                        lab = Lab(
                            name=course_row["lab_name"], item_type=course_row["item_type"],
                            total_credits=course_row["credits"], url=course_row.get("lab_url") or "",
                            badge_id=badge.id,
                        )
                        db.add(lab)
                        db.flush()
                    elif _normalize_text(lab.badge.name) not in _expected_badge_names(course_row):
                        unresolved.append({"badge": badge_name, "reason": "Lab URL is associated with a different verified badge."})
                        continue

                    completion = db.scalar(select(Completion).where(
                        Completion.user_id == user_id,
                        Completion.badge_id == badge.id,
                    ))
                    earned_at = _date_value(earned.get("date"))
                    if completion is None:
                        completion = Completion(
                            user_id=user_id,
                            badge_id=badge.id,
                            lab_id=lab.id,
                            is_completed=True,
                            earned_at=earned_at,
                            first_detected_at=started_at,
                            last_verified_at=finished_at,
                        )
                        db.add(completion)
                    else:
                        completion.is_completed = True
                        completion.earned_at = earned_at or completion.earned_at
                        completion.last_verified_at = finished_at
                        completion.lab_id = lab.id
                else:
                    unresolved.append({
                        "badge": badge_name,
                        "badge_id": badge_id,
                        "reason": "No exact workbook lab-name match; badge saved, completion cannot be stored because schema requires a lab_id.",
                    })

            db.add(ScrapeLog(
                user_id=user_id,
                status="Success",
                badges_found=len(earned_badges),
                new_badges_found=new_badges,
                started_at=started_at,
                finished_at=finished_at,
            ))
            _import_course_rows(db, course_rows)
        logger.info(
            "Database persistence committed for user_id=%s (badges_found=%d, new_badges_found=%d, unresolved=%d)",
            user_id,
            len(earned_badges),
            new_badges,
            len(unresolved),
        )

        return {"user_id": user_id, "status": "Success", "badges_found": len(earned_badges),
                "new_badges_found": new_badges, "unresolved": unresolved}
    except Exception as error:
        finished_at = datetime.now(timezone.utc)
        logger.exception("Participant processing failed for user_id=%s", user_id)
        # Scrape data mutations roll back together. The failure log is committed
        # independently; no existing completion is deleted or overwritten.
        with SessionLocal.begin() as db:
            if db.get(User, user_id) is not None:
                db.add(ScrapeLog(
                    user_id=user_id,
                    status="Failed",
                    badges_found=0,
                    new_badges_found=0,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_message=str(error)[:4000],
                ))
        return {"user_id": user_id, "status": "Failed", "error": str(error)}


@app.get("/")
def root():
    return {"message": "Google Skills Badge Tracker API is running."}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.post("/api/course/upload")
async def upload_course(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    target_path = _course_file_for_runtime()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    rows = _load_course_rows(target_path)
    with SessionLocal.begin() as db:
        result = _import_course_rows(db, rows)
    return {"message": "Course workbook uploaded and checked.", "total_labs": len(rows),
            "imported_labs": result["imported"], "unresolved": result["unresolved"]}


@app.post("/api/participants/upload")
async def upload_participants(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as temp_file:
        temp_file.write(content)
        temp_file.flush()
        try:
            records = load_participants(temp_file.name, sheet_name=PARTICIPANT_SHEET)
        except Exception as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    with SessionLocal.begin() as db:
        result = _import_users(db, records)
    return {"message": "Participant workbook imported.", "total_participants": len(records), **result,
            "issues": result["issues"] + load_participants.last_issues}


@app.get("/api/course")
def get_course():
    with SessionLocal() as db:
        labs = db.scalars(select(Lab).options(joinedload(Lab.badge)).order_by(Lab.id)).unique().all()
        return {"total_labs": len(labs), "labs": [
            {"lab_name": lab.name, "name": lab.name, "badge_name": lab.badge.name,
             "badge_id": lab.badge.id,
             "lab_url": lab.url, "url": lab.url, "credits": lab.total_credits,
             "total_credits": lab.total_credits, "item_type": lab.item_type,
             "category": "Completion" if lab.item_type == "Course" else "Skill"}
            for lab in labs
        ]}


@app.get("/api/participants")
def get_participants():
    with SessionLocal() as db:
        users = _serialize_users(db)
        return {"total_participants": len(users), "participants": users}


@app.post("/api/participants/process")
def process_all_participants():
    with SessionLocal() as db:
        user_ids = list(db.scalars(select(User.id).order_by(User.id)).all())
    if not user_ids:
        raise HTTPException(status_code=400, detail="Import a participant workbook first.")
    course_rows = _load_course_rows()
    results = [_process_user(user_id, course_rows=course_rows) for user_id in user_ids]
    return {
        "message": "Participant processing completed.",
        "total_participants": len(results),
        "successful": sum(result["status"] == "Success" for result in results),
        "failed": sum(result["status"] == "Failed" for result in results),
        "results": results,
    }


@app.post("/api/participants/{participant_index}/refresh")
def refresh_participant(participant_index: int):
    return _process_user(participant_index)


@app.get("/api/leaderboard")
def get_full_leaderboard():
    with SessionLocal() as db:
        records = _serialize_users(db)
    return get_leaderboard(records)


@app.get("/api/leaderboard/top/{limit}")
def get_top_leaderboard(limit: int):
    if limit not in (10, 100, 250):
        raise HTTPException(status_code=400, detail="Limit must be 10, 100, or 250.")
    with SessionLocal() as db:
        records = _serialize_users(db)
    return get_leaderboard(records, limit)
