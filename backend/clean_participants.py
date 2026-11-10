import re
import uuid
import argparse
from urllib.parse import urlsplit

from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

def clean_text(value):
    return "" if value is None else str(value).strip()

def normalize_profile_url(value):
    return re.sub(r"\s+", "", clean_text(value))

def is_valid_email(email):
    return bool(EMAIL_RE.fullmatch(email))

def is_valid_profile_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https":
            return False
        if parsed.netloc.lower() not in {"www.skills.google", "skills.google"}:
            return False
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "public_profiles":
            return False
        uuid.UUID(parts[1])
        return True
    except (ValueError, AttributeError):
        return False

def style_sheet(ws):
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for column in ws.columns:
        width = min(max(max((len(str(c.value or "")) for c in column), default=10) + 2, 14), 60)
        ws.column_dimensions[get_column_letter(column[0].column)].width = width

def main():
    parser = argparse.ArgumentParser(description="Clean the participant list in an Excel workbook.")
    parser.add_argument("input", help="Input registration .xlsx file")
    parser.add_argument("-o", "--output", default="clean_participants.xlsx")
    parser.add_argument("--sheet", default="Sheet1")
    args = parser.parse_args()

    source_wb = load_workbook(args.input, data_only=True)
    if args.sheet not in source_wb.sheetnames:
        raise ValueError(f"Worksheet '{args.sheet}' not found. Available: {source_wb.sheetnames}")
    source_ws = source_wb[args.sheet]

    clean_rows, review_rows, seen = [], [], set()

    # In this workbook: column A = name, B = email, C = public profile URL.
    for excel_row, row in enumerate(source_ws.iter_rows(min_row=2, values_only=True), start=2):
        name = clean_text(row[0] if len(row) > 0 else None)
        email = clean_text(row[1] if len(row) > 1 else None)
        url = normalize_profile_url(row[2] if len(row) > 2 else None)

        if not any((name, email, url)):
            continue

        reasons = []
        if not name:
            reasons.append("Missing participant name")
        if not is_valid_email(email):
            reasons.append("Invalid email format")
        if not is_valid_profile_url(url):
            reasons.append("Invalid Google Skills public profile URL")

        normalized_url = url.rstrip("/")
        if is_valid_profile_url(url):
            if normalized_url in seen:
                reasons.append("Duplicate public profile URL")
            else:
                seen.add(normalized_url)

        if reasons:
            review_rows.append([excel_row, name, email, url, "; ".join(reasons)])
        else:
            clean_rows.append([name, email, url])

    output_wb = Workbook()
    clean_ws = output_wb.active
    clean_ws.title = "Clean Participants"
    clean_ws.append(["Name", "Email", "Public Profile URL"])
    for row in clean_rows:
        clean_ws.append(row)
    style_sheet(clean_ws)

    review_ws = output_wb.create_sheet("Needs Review")
    review_ws.append(["Original Excel Row", "Name", "Email", "Public Profile URL", "Reason"])
    for row in review_rows:
        review_ws.append(row)
    style_sheet(review_ws)

    summary_ws = output_wb.create_sheet("Summary")
    summary_ws.append(["Metric", "Count"])
    summary_ws.append(["Valid unique participants", len(clean_rows)])
    summary_ws.append(["Rows needing review", len(review_rows)])
    summary_ws.append(["Total non-empty source rows", len(clean_rows) + len(review_rows)])
    style_sheet(summary_ws)

    output_wb.save(args.output)
    print(f"Clean participants: {len(clean_rows)}")
    print(f"Rows needing review: {len(review_rows)}")
    print(f"Saved workbook: {args.output}")

if __name__ == "__main__":
    main()
