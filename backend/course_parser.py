
from pathlib import Path
from openpyxl import load_workbook


HEADER_ALIASES = {
    "lab_name": [
        "lab name", "course name", "activity name", "activity", "title", "name"
    ],
    "item_type": ["lab/course", "lab course", "item type", "type"],
    "badge_name": ["badge name", "google skills badge", "badge title"],
    "category": ["completion/skill", "completion skill", "category", "credential type"],
    "credits": [
        "total credits needed", "credits", "credit", "points"
    ],
    "lab_url": [
        "lab link", "lab url", "course link", "course url",
        "link", "url"
    ],
}


def normalize_header(value):
    if value is None:
        return ""

    return " ".join(str(value).strip().lower().replace("_", " ").split())


def find_columns(headers):
    columns = {}

    for index, header in enumerate(headers):
        normalized = normalize_header(header)

        for field, aliases in HEADER_ALIASES.items():
            if normalized in aliases:
                columns[field] = index
                break

    return columns


def parse_course(file_path="data/course.xlsx", sheet_name=None):
    """
    Read course/lab requirements from an Excel workbook.

    Returns:
        A list of dictionaries containing:
        lab_name, badge_name, lab_url, credits
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Course workbook not found: {path}")

    workbook = load_workbook(path, data_only=True)

    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"Sheet '{sheet_name}' not found.")

            worksheet = workbook[sheet_name]
        else:
            worksheet = workbook.active

        header_row = None
        columns = {}

        # Search the first 10 rows for the header.
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=1, max_row=min(10, worksheet.max_row),
                                values_only=True),
            start=1
        ):
            detected = find_columns(row)

            if {"lab_name", "item_type"}.issubset(detected):
                header_row = row_number
                columns = detected
                break

        if header_row is None:
            raise ValueError(
                "Could not identify a Lab/Course name column in the workbook."
            )
        required_fields = {"lab_name", "item_type", "credits", "category", "lab_url"}
        missing_fields = required_fields - columns.keys()
        if missing_fields:
            raise ValueError(
                "Course worksheet is missing required headers: "
                + ", ".join(sorted(missing_fields))
            )

        labs = []

        for excel_row, row in enumerate(
            worksheet.iter_rows(min_row=header_row + 1, values_only=False),
            start=header_row + 1,
        ):
            values = [cell.value for cell in row]

            name_index = columns["lab_name"]
            lab_name = values[name_index]

            if lab_name is None or not str(lab_name).strip():
                continue

            normalized_name = " ".join(str(lab_name).strip().lower().split())
            # Course spreadsheets may include footer rows alongside the labs.
            # They are not activities and should not inflate badge totals.
            if normalized_name in {"total credits", "total credit"} or normalized_name.startswith("note:"):
                continue

            badge_name = None
            if "badge_name" in columns:
                badge_name = values[columns["badge_name"]]

            lab_url = None
            if "lab_url" in columns:
                url_cell = row[columns["lab_url"]]
                lab_url = url_cell.value

                if url_cell.hyperlink:
                    lab_url = url_cell.hyperlink.target

            raw_type = values[columns["item_type"]]
            type_text = str(raw_type or "").strip().casefold()
            if type_text in {"course", "courses"}:
                item_type = "Course"
            elif type_text in {"challenge lab", "challenge labs", "lab"}:
                item_type = "Challenge Lab"
            else:
                raise ValueError(
                    f"Row {excel_row}: unknown Lab/Course type {raw_type!r}; "
                    "expected Course or Challenge Lab."
                )

            raw_credits = values[columns["credits"]]
            try:
                numeric_credits = float(raw_credits)
                credits = int(numeric_credits)
            except (TypeError, ValueError):
                raise ValueError(f"Row {excel_row}: invalid Total Credits Needed {raw_credits!r}.")
            if numeric_credits != credits:
                raise ValueError(f"Row {excel_row}: Total Credits Needed must be a whole number, got {raw_credits!r}.")
            if credits < 0:
                raise ValueError(f"Row {excel_row}: Total Credits Needed cannot be negative.")

            category = None
            if "category" in columns:
                raw_category = values[columns["category"]]
                category = str(raw_category).strip() if raw_category is not None else None

            if "lab_url" in columns:
                url_cell = row[columns["lab_url"]]
                if url_cell.hyperlink:
                    lab_url = url_cell.hyperlink.target

            if not lab_url:
                raise ValueError(f"Row {excel_row}: missing Link for {lab_name!r}.")

            labs.append({
                "lab_name": str(lab_name).strip(),
                "item_type": item_type,
                "badge_name": (
                    str(badge_name).strip()
                    if badge_name is not None else None
                ),
                "category": category,
                "lab_url": (
                    str(lab_url).strip()
                    if lab_url is not None else None
                ),
                "credits": credits,
                "source_row": excel_row,
            })

        return labs

    finally:
        workbook.close()


if __name__ == "__main__":
    course_labs = parse_course()

    print(f"\nTotal labs found: {len(course_labs)}\n")

    for index, lab in enumerate(course_labs, start=1):
        print(f"{index}. {lab['lab_name']}")
        print(f"   Badge: {lab['badge_name']}")
        print(f"   Link: {lab['lab_url']}")
        print(f"   Credits: {lab['credits']}")
        print()
