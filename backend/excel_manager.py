
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
        if sheet_name and sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]
        elif sheet_name:
            # Fall back gracefully for workbooks that use a different sheet name.
            worksheet = workbook.active
        else:
            worksheet = workbook.active

        # Find the header row/columns instead of assuming a fixed sheet name
        # and column order. Workbooks may have slightly different/misaligned headers.
        header_row = None
        columns = {}
        aliases = {
            "name": {"name", "full name", "your full name", "participant name"},
            "email": {"email", "email address", "email id", "mail"},
            "profile_url": {
                "profile url", "public profile url", "google skills public profile url",
                "google skills profile url", "skills profile url", "profile link",
                "google cloud skills boost profile url", "cloud skills boost profile url",
            },
        }

        def _normalize_header(value):
            return " ".join(str(value or "").strip().lower().replace("_", " ").replace("\n", " ").split())

        def _match_field(header):
            for field, names in aliases.items():
                if header in names:
                    return field
            # Fallback substring heuristics for non-standard headers.
            if "profile" in header and "url" in header:
                return "profile_url"
            if "public" in header and "profile" in header:
                return "profile_url"
            if header == "email" or ("email" in header and "address" in header):
                return "email"
            if "name" in header and "mentor" not in header and "department" not in header:
                # Prefer explicit participant/name-like headers; avoid mentor name.
                if field_not_taken("name"):
                    return "name"
            return None

        def field_not_taken(field):
            return field not in columns

        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=1, max_row=min(10, (worksheet.max_row or 10)), values_only=True),
            start=1,
        ):
            found = {}
            for index, value in enumerate(row):
                header = _normalize_header(value)
                if not header:
                    continue
                # Exact alias match first.
                matched = None
                for field, names in aliases.items():
                    if header in names:
                        matched = field
                        break
                if matched is None:
                    # Substring heuristics for header labels (not data values).
                    looks_like_url = header.startswith("http") or header.startswith("www.")
                    if not looks_like_url:
                        if "profile" in header and ("url" in header or "link" in header):
                            matched = "profile_url"
                        elif "email" in header and "mentor" not in header:
                            matched = "email"
                        elif "name" in header and "mentor" not in header and "department" not in header and "user" not in header:
                            matched = "name"
                if matched and matched not in found:
                    found[matched] = index
            if "profile_url" in found:
                header_row = row_number
                columns = found
                break

        if header_row is None:
            # Last-resort: detect profile URL column by data values.
            for row_number, row in enumerate(
                worksheet.iter_rows(min_row=1, max_row=min(10, (worksheet.max_row or 10)), values_only=True),
                start=1,
            ):
                for index, value in enumerate(row):
                    text = str(value or "").strip()
                    parsed = urlparse(text)
                    if (
                        parsed.scheme.lower() == "https"
                        and parsed.netloc.lower() in {"skills.google", "www.skills.google"}
                        and re.fullmatch(r"/public_profiles/[A-Za-z0-9-]+/?", parsed.path)
                    ):
                        columns = {"profile_url": index}
                        header_row = row_number
                        break
                if header_row is not None:
                    break

        if header_row is None:
            raise ValueError(
                "Participant worksheet is missing required headers: Name and Public Profile URL. "
                f"Available worksheets: {workbook.sheetnames}."
            )

        # Infer name column if missing: pick a likely person-name column.
        if "name" not in columns:
            sample_rows = list(
                worksheet.iter_rows(min_row=header_row + 1, max_row=min(header_row + 20, (worksheet.max_row or (header_row + 20))), values_only=True)
            )
            best_index = None
            best_score = -1
            exclude = set(columns.values())
            for index in range(max((len(r) for r in sample_rows), default=0)):
                if index in exclude:
                    continue
                score = 0
                seen = 0
                for row in sample_rows:
                    if index >= len(row):
                        continue
                    value = row[index]
                    text = str(value or "").strip()
                    if not text:
                        continue
                    seen += 1
                    if re.search(r"https?://", text, re.IGNORECASE):
                        score -= 5
                        continue
                    if EMAIL_PATTERN.fullmatch(text.lower()):
                        score -= 3
                        continue
                    if re.fullmatch(r"[A-Za-z0-9/\-_. ]{2,30}", text) and any(ch.isdigit() for ch in text) and " " not in text.strip():
                        # Likely USN/code-like
                        score -= 1
                        continue
                    if re.search(r"[A-Za-z]", text):
                        score += 2
                        if " " in text.strip():
                            score += 2
                        if len(text.strip()) >= 3:
                            score += 1
                if seen > 0 and score > best_score:
                    best_score = score
                    best_index = index
            if best_index is not None and best_score > 0:
                columns["name"] = best_index

        if "name" not in columns or "profile_url" not in columns:
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
