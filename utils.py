import re

GOTO_TIMEOUT = 60_000

VALID_CATEGORIES = [
    "Where they live",
    "Where they studied",
    "What they studied",
    "What they are skilled at",
    "What they do",
    "How they got there",
]

JUNK = {
    "add", "+ add", "show more", "see more", "follow", "connect",
    "message", "search employees by title, keyword or school",
    "people you may know", "cards updated", "associated members",
}

CLASS_TO_CATEGORY = {
    "geo-region":       "Where they live",
    "organization":     "Where they studied",
    "field-of-study":   "What they studied",
    "skill":            "What they are skilled at",
    "current-function": "What they do",
    "degree":           "How they got there",
}


def parse_entries(lines: list) -> list:
    results = []
    seen    = set()
    i       = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.lower() in JUNK or line in VALID_CATEGORIES:
            i += 1
            continue
        m = re.match(r"^([\d,]+)\s*\|\s*(.+)$", line)
        if m:
            count = m.group(1).replace(",", "")
            label = m.group(2).strip()
            if label and label.lower() not in JUNK and label not in seen:
                results.append({"count": count, "label": label})
                seen.add(label)
            i += 1
            continue
        if re.match(r"^[\d,]+$", line):
            count = line.replace(",", "")
            label = None
            for offset in range(1, 4):
                if i + offset >= len(lines):
                    break
                cand = lines[i + offset].strip()
                if not cand:
                    continue
                if re.match(r"^[\d,]+$", cand):
                    break
                if cand.lower() in JUNK or cand in VALID_CATEGORIES:
                    break
                label = cand
                i += offset + 1
                break
            else:
                i += 1
                continue
            if label and label not in seen:
                results.append({"count": count, "label": label})
                seen.add(label)
            if label is None:
                i += 1
            continue
        i += 1
    return results