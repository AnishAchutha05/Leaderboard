
from pathlib import Path
import re
from urllib.parse import urlparse
from openpyxl import load_workbook


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def load_participants(file_path: str, sheet_name: str | None = None) -> list[dict]:
    """
    Read participant records from an Excel workbook.

    Expected columns:
        Your Full Name
        Email
        Google Skills Public Profile URL
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Participant workbook not found: {path}")

    workbook = load_workbook(path, data_only=True, read_only=True)

    try:
        if sheet_name and sheet_name not in workbook.sheetnames:
            raise ValueError(f"Sheet '{sheet_name}' not found.")

        worksheet = workbook[sheet_name] if sheet_name else workbook.active

        # Find the header row/columns instead of assuming a fixed sheet name
        # and column order. Uploaded workbooks commonly use headers such as
        # Name, Email, and Public Profile URL.
        header_row = None
        columns = {}
        aliases = {
            "name": {"name", "full name", "your full name", "participant name"},
            "email": {"email", "email address"},
            "profile_url": {
                "profile url", "public profile url", "google skills public profile url",
                "google skills profile url", "skills profile url", "profile link"
            },
        }

        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=1, max_row=min(10, worksheet.max_row), values_only=True),
            start=1,
        ):
            found = {}
            for index, value in enumerate(row):
                header = " ".join(str(value or "").strip().lower().replace("_", " ").split())
                for field, names in aliases.items():
                    if header in names:
                        found[field] = index
                        break
            if {"name", "profile_url"}.issubset(found):
                header_row = row_number
                columns = found
                break

        if header_row is None:
            raise ValueError(
                "Participant worksheet is missing required headers: Name and Public Profile URL. "
                f"Available worksheets: {workbook.sheetnames}."
            )

        participants = []
        issues = []
        seen_profiles = set()

        for excel_row, row in enumerate(
            worksheet.iter_rows(min_row=header_row + 1, values_only=True),
            start=header_row + 1,
        ):
            values = list(row)

            if not any(values):
                continue

            name = values[columns["name"]] if len(values) > columns["name"] else None
            email_index = columns.get("email")
            email = values[email_index] if email_index is not None and len(values) > email_index else None
            profile_index = columns.get("profile_url")
            profile_url = values[profile_index] if profile_index is not None and len(values) > profile_index else None

            name = str(name).strip() if name is not None else ""
            email = str(email).strip().lower() if email is not None and str(email).strip() else None
            profile_url = str(profile_url).strip() if profile_url is not None else ""

            if not name:
                issues.append(f"Row {excel_row}: missing participant name; skipped.")
                continue
            if email and not EMAIL_PATTERN.fullmatch(email):
                issues.append(f"Row {excel_row}: malformed email address; skipped ({email!r}).")
                continue

            parsed_url = urlparse(profile_url)
            if (
                parsed_url.scheme.lower() != "https"
                or parsed_url.netloc.lower() not in {"skills.google", "www.skills.google"}
                or not re.fullmatch(r"/public_profiles/[A-Za-z0-9-]+/?", parsed_url.path)
            ):
                issues.append(f"Row {excel_row}: invalid public profile URL; skipped ({profile_url!r}).")
                continue

            profile_key = profile_url.rstrip("/").lower()
            if profile_key in seen_profiles:
                issues.append(f"Row {excel_row}: duplicate public profile URL; skipped.")
                continue
            seen_profiles.add(profile_key)

            participants.append({
                "name": name,
                "email": email,
                "profile_url": profile_url,
                "badges": [],
                "progress": {},
                "last_checked": None,
                "status": "Not Checked",
                "source_row": excel_row,
            })

        if issues:
            # Keep valid records importable while making skipped rows visible to callers.
            load_participants.last_issues = issues
        else:
            load_participants.last_issues = []

        return participants

    finally:
        workbook.close()


load_participants.last_issues = []
