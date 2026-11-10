from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

if __package__:
    from .course_parser import parse_course
    from .database.database import SessionLocal
    from .database.models import Badge, Completion, Lab, ScrapeLog, User
    from .excel_manager import load_participants
    from .leaderboard import get_leaderboard
    from .participant_manager import validate_profile_url
    from .scraper import scrape_badges
else:  # Keep `uvicorn main:app` from the backend directory working.
    from course_parser import parse_course
    from database.database import SessionLocal
    from database.models import Badge, Completion, Lab, ScrapeLog, User
    from excel_manager import load_participants
    from leaderboard import get_leaderboard
    from participant_manager import validate_profile_url
    from scraper import scrape_badges

app = FastAPI(
    title="Google Skills Badge Tracker",
    description="Track participant progress across Google Skills labs.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
COURSE_FILE = next(
    (path for path in (
        DATA_DIR / "GCP_Labs_Courses_Professional.xlsx",
        DATA_DIR / "course.xlsx",
    ) if path.exists()),
    DATA_DIR / "GCP_Labs_Courses_Professional.xlsx",
)
PARTICIPANT_FILE = next(
    (path for path in (
        DATA_DIR / "clean_participants.xlsx",
        DATA_DIR / "participants.xlsx",
    ) if path.exists()),
    DATA_DIR / "clean_participants.xlsx",
)
RESULTS_FILE = DATA_DIR / "results.xlsx"
PARTICIPANT_SHEET = "Clean Participants"
COURSE_SHEET = "GCP Labs & Courses"


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _normalize_profile_url(value: str) -> str:
    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    return f"https://{host}{parsed.path.rstrip('/') }"


def _load_course_rows():
    if not COURSE_FILE.exists():
        raise HTTPException(status_code=400, detail=f"Course workbook not found: {COURSE_FILE}")
    try:
        return parse_course(str(COURSE_FILE), sheet_name=COURSE_SHEET)
    except ValueError as error:
        # Support earlier workbook exports whose active sheet had another name.
        try:
            return parse_course(str(COURSE_FILE))
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


def _find_course_for_badge(course_rows: list[dict], badge_name: str) -> dict | None:
    exact = _normalize_text(badge_name)
    matches = [row for row in course_rows if _normalize_text(row.get("lab_name")) == exact]
    return matches[0] if len(matches) == 1 else None


def _import_course_rows(db: Session, course_rows: list[dict]) -> dict:
    imported = 0
    unresolved = []
    known_badges = db.scalars(select(Badge)).all()
    for row in course_rows:
        badge_name = row.get("badge_name") or row["lab_name"]
        matches = [badge for badge in known_badges
                   if _normalize_text(badge.name) == _normalize_text(badge_name)]
        if len(matches) != 1:
            unresolved.append({
                "row": row.get("source_row"),
                "name": row["lab_name"],
                "reason": (
                    "No unique exact-name match to a badge ID scraped from a public profile."
                    if matches else
                    "Workbook contains no Google badge ID; awaiting an exact name match to a badge ID scraped from a public profile."
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
        elif lab.badge_id == badge.id:
            lab.name = row["lab_name"]
            lab.item_type = row["item_type"]
            lab.total_credits = row["credits"]
        else:
            unresolved.append({
                "row": row.get("source_row"),
                "name": row["lab_name"],
                "reason": "URL already belongs to a different badge; association left unchanged.",
            })
            continue
        imported += 1
    db.flush()
    return {"imported": imported, "unresolved": unresolved}


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
            completion = next((item for item in completions if item.badge_id == lab.badge_id), None)
            labs.append({
                "lab_name": lab.name,
                "badge_name": lab.badge.name,
                "lab_url": lab.url,
                "credits": lab.total_credits,
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


def _process_user(user_id: int) -> dict:
    started_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Participant not found.")
        profile_url = user.public_profile_url

    try:
        if not validate_profile_url(profile_url):
            raise ValueError("Invalid public profile URL")
        earned_badges = scrape_badges(profile_url)
        course_rows = _load_course_rows()
        finished_at = datetime.now(timezone.utc)
        new_badges = 0
        unresolved = []

        with SessionLocal.begin() as db:
            user = db.get(User, user_id)
            for earned in earned_badges:
                badge_id = str(earned.get("badge_id") or "").strip()
                badge_name = str(earned.get("badge_name") or "").strip()
                if not badge_id or not badge_name:
                    unresolved.append({"badge": badge_name or None, "reason": "Scraper found no actual Google badge ID or name."})
                    continue

                course_row = _find_course_for_badge(course_rows, badge_name)
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
                # relation when its title exactly matches a real scraped badge.
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
                    elif lab.badge_id != badge.id:
                        unresolved.append({"badge": badge_name, "reason": "Exact-name lab URL is already associated with another badge."})
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

        return {"user_id": user_id, "status": "Success", "badges_found": len(earned_badges),
                "new_badges_found": new_badges, "unresolved": unresolved}
    except Exception as error:
        finished_at = datetime.now(timezone.utc)
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
    COURSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COURSE_FILE.write_bytes(content)
    rows = _load_course_rows()
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
    PARTICIPANT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARTICIPANT_FILE.write_bytes(content)
    try:
        records = load_participants(str(PARTICIPANT_FILE), sheet_name=PARTICIPANT_SHEET)
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
            {"lab_name": lab.name, "badge_name": lab.badge.name, "lab_url": lab.url,
             "credits": lab.total_credits, "item_type": lab.item_type}
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
    results = [_process_user(user_id) for user_id in user_ids]
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


@app.get("/api/results")
def get_results():
    if not RESULTS_FILE.exists():
        raise HTTPException(status_code=404, detail="Results are not available yet.")
    return {"message": "Results workbook is available.", "file": str(RESULTS_FILE)}


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
