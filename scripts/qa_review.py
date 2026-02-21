"""Interactive QA review tool for generated bedtime content.

Review, approve, reject, or edit generated stories and poems.

Usage:
    python3 scripts/qa_review.py                    # Review all pending
    python3 scripts/qa_review.py --age-group 0-1    # Review specific age group
    python3 scripts/qa_review.py --lang hi           # Review Hindi only
    python3 scripts/qa_review.py --type poem         # Review poems only
    python3 scripts/qa_review.py --stats             # Show review progress
    python3 scripts/qa_review.py --auto-approve      # Auto-approve valid content
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content_expanded.json"

# ── ANSI Colors ────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_GREEN = "\033[42m"
BG_RED = "\033[41m"
BG_YELLOW = "\033[43m"

# Emotion marker colors
MARKER_COLORS = {
    "GENTLE": f"{MAGENTA}",
    "CALM": f"{BLUE}",
    "SLEEPY": f"{DIM}{BLUE}",
    "EXCITED": f"{YELLOW}",
    "CURIOUS": f"{CYAN}",
    "ADVENTUROUS": f"{GREEN}",
    "MYSTERIOUS": f"{MAGENTA}",
    "JOYFUL": f"{YELLOW}",
    "DRAMATIC": f"{RED}",
    "WHISPERING": f"{DIM}{MAGENTA}",
    "DRAMATIC_PAUSE": f"{DIM}{RED}",
    "RHYTHMIC": f"{CYAN}",
    "SINGING": f"{GREEN}",
    "HUMMING": f"{DIM}{GREEN}",
    "PAUSE": f"{DIM}",
    "laugh": f"{YELLOW}",
    "chuckle": f"{DIM}{YELLOW}",
}


def colorize_markers(text: str) -> str:
    """Highlight emotion markers with ANSI colors."""
    def replace_marker(match):
        marker = match.group(1)
        color = MARKER_COLORS.get(marker, CYAN)
        return f"{color}[{marker}]{RESET}"

    return re.sub(r"\[([\w_]+)\]", replace_marker, text)


def count_words(text: str) -> int:
    """Count words, ignoring emotion markers."""
    clean = re.sub(r"\[[\w_]+\]", "", text)
    return len(clean.split())


def wrap_text(text: str, width: int = 80) -> str:
    """Wrap text to terminal width while preserving emotion markers."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        if len(current_line) + len(word) + 1 > width:
            lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}" if current_line else word

    if current_line:
        lines.append(current_line)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def validate_content(item: Dict) -> List[str]:
    """Run quality checks on a content piece. Returns list of issues."""
    issues = []

    text = item.get("annotated_text", item.get("text", ""))
    content_type = item.get("type", "story")
    age_group = item.get("age_group", "")
    length = item.get("length", "MEDIUM")

    # Check for emotion markers
    markers = re.findall(r"\[([\w_]+)\]", text)
    if not markers:
        issues.append("⚠️  No emotion markers found")
    else:
        if content_type == "story":
            if markers[0] != "GENTLE":
                issues.append(f"⚠️  Story should start with [GENTLE], starts with [{markers[0]}]")
            if markers[-1] != "SLEEPY":
                issues.append(f"⚠️  Story should end with [SLEEPY], ends with [{markers[-1]}]")
        elif content_type == "poem":
            has_rhythmic = "RHYTHMIC" in markers
            if not has_rhythmic:
                issues.append("⚠️  Poem missing [RHYTHMIC] markers")

    # Check word count
    wc = count_words(text)
    # Reference word count ranges
    word_ranges = {
        ("0-1", "story", "SHORT"): (20, 80),
        ("0-1", "story", "MEDIUM"): (40, 150),
        ("2-5", "story", "SHORT"): (40, 300),
        ("2-5", "story", "MEDIUM"): (80, 600),
        ("2-5", "story", "LONG"): (350, 1000),
        ("6-8", "story", "SHORT"): (140, 500),
        ("6-8", "story", "MEDIUM"): (280, 900),
        ("6-8", "story", "LONG"): (500, 1500),
        ("9-12", "story", "SHORT"): (200, 650),
        ("9-12", "story", "MEDIUM"): (350, 1100),
        ("9-12", "story", "LONG"): (630, 2000),
        # Poems — wider tolerance
        ("0-1", "poem", "SHORT"): (10, 60),
        ("0-1", "poem", "MEDIUM"): (25, 100),
        ("2-5", "poem", "SHORT"): (15, 120),
        ("2-5", "poem", "MEDIUM"): (40, 180),
        ("2-5", "poem", "LONG"): (90, 260),
        ("6-8", "poem", "SHORT"): (40, 140),
        ("6-8", "poem", "MEDIUM"): (70, 240),
        ("6-8", "poem", "LONG"): (125, 400),
        ("9-12", "poem", "SHORT"): (55, 180),
        ("9-12", "poem", "MEDIUM"): (90, 300),
        ("9-12", "poem", "LONG"): (155, 520),
    }

    key = (age_group, content_type, length)
    if key in word_ranges:
        min_wc, max_wc = word_ranges[key]
        if wc < min_wc:
            issues.append(f"⚠️  Word count {wc} below minimum {min_wc}")
        elif wc > max_wc:
            issues.append(f"⚠️  Word count {wc} above maximum {max_wc}")

    # Check title
    title = item.get("title", "")
    if not title or len(title) < 3:
        issues.append("⚠️  Missing or too-short title")

    # Check description
    desc = item.get("description", "")
    if not desc or len(desc) < 10:
        issues.append("⚠️  Missing or too-short description")

    # Check for empty text
    if not text or len(text) < 20:
        issues.append("❌ Text is too short or missing")

    # Check Hindi Devanagari
    if item.get("lang") == "hi":
        devanagari = item.get("annotated_text_devanagari", "")
        if not devanagari:
            issues.append("⚠️  Hindi story missing Devanagari text")

    return issues


# ═══════════════════════════════════════════════════════════════════════
# STATISTICS
# ═══════════════════════════════════════════════════════════════════════

def show_stats(content: List[Dict]):
    """Show review progress statistics."""
    total = len(content)
    approved = sum(1 for c in content if c.get("generation_quality") == "approved")
    rejected = sum(1 for c in content if c.get("generation_quality") == "rejected")
    pending = sum(1 for c in content if c.get("generation_quality") == "pending_review")

    print(f"\n{BOLD}{'═' * 60}")
    print(f"  QA REVIEW PROGRESS")
    print(f"{'═' * 60}{RESET}\n")

    print(f"  {BOLD}Total:{RESET}    {total}")
    print(f"  {GREEN}Approved:{RESET} {approved}")
    print(f"  {RED}Rejected:{RESET} {rejected}")
    print(f"  {YELLOW}Pending:{RESET}  {pending}")

    # By age group
    print(f"\n  {BOLD}By Age Group:{RESET}")
    for ag in ["0-1", "2-5", "6-8", "9-12"]:
        ag_items = [c for c in content if c.get("age_group") == ag]
        ag_approved = sum(1 for c in ag_items if c.get("generation_quality") == "approved")
        ag_rejected = sum(1 for c in ag_items if c.get("generation_quality") == "rejected")
        ag_pending = sum(1 for c in ag_items if c.get("generation_quality") == "pending_review")
        ag_total = len(ag_items)
        reviewed = ag_approved + ag_rejected
        bar_len = 20
        bar_fill = int(bar_len * reviewed / max(ag_total, 1))
        bar = f"{'█' * bar_fill}{'░' * (bar_len - bar_fill)}"
        print(f"    {ag:>4}: {bar} {reviewed}/{ag_total} "
              f"({GREEN}{ag_approved}✓{RESET} {RED}{ag_rejected}✗{RESET} {YELLOW}{ag_pending}?{RESET})")

    # By language
    print(f"\n  {BOLD}By Language:{RESET}")
    for lang in ["en", "hi"]:
        lang_items = [c for c in content if c.get("lang") == lang]
        lang_approved = sum(1 for c in lang_items if c.get("generation_quality") == "approved")
        lang_rejected = sum(1 for c in lang_items if c.get("generation_quality") == "rejected")
        lang_pending = sum(1 for c in lang_items if c.get("generation_quality") == "pending_review")
        lang_total = len(lang_items)
        reviewed = lang_approved + lang_rejected
        bar_len = 20
        bar_fill = int(bar_len * reviewed / max(lang_total, 1))
        bar = f"{'█' * bar_fill}{'░' * (bar_len - bar_fill)}"
        print(f"    {lang.upper():>4}: {bar} {reviewed}/{lang_total} "
              f"({GREEN}{lang_approved}✓{RESET} {RED}{lang_rejected}✗{RESET} {YELLOW}{lang_pending}?{RESET})")

    # By type
    print(f"\n  {BOLD}By Type:{RESET}")
    for ctype in ["story", "poem"]:
        type_items = [c for c in content if c.get("type") == ctype]
        type_approved = sum(1 for c in type_items if c.get("generation_quality") == "approved")
        type_pending = sum(1 for c in type_items if c.get("generation_quality") == "pending_review")
        type_total = len(type_items)
        print(f"    {ctype:>6}: {type_approved}/{type_total} approved, {type_pending} pending")

    # Quality issues overview
    print(f"\n  {BOLD}Auto-Validation:{RESET}")
    issues_count = 0
    clean_count = 0
    for c in content:
        issues = validate_content(c)
        if issues:
            issues_count += 1
        else:
            clean_count += 1
    print(f"    {GREEN}Clean (no issues):{RESET} {clean_count}")
    print(f"    {YELLOW}With issues:{RESET}       {issues_count}")

    print()


# ═══════════════════════════════════════════════════════════════════════
# AUTO-APPROVE
# ═══════════════════════════════════════════════════════════════════════

def auto_approve(content: List[Dict], filters: Dict) -> int:
    """Auto-approve content that passes all validation checks."""
    approved_count = 0

    for item in content:
        if item.get("generation_quality") != "pending_review":
            continue

        # Apply filters
        if filters.get("lang") and item.get("lang") != filters["lang"]:
            continue
        if filters.get("age_group") and item.get("age_group") != filters["age_group"]:
            continue
        if filters.get("type") and item.get("type") != filters["type"]:
            continue

        issues = validate_content(item)
        if not issues:
            item["generation_quality"] = "approved"
            approved_count += 1

    return approved_count


# ═══════════════════════════════════════════════════════════════════════
# INTERACTIVE REVIEW
# ═══════════════════════════════════════════════════════════════════════

def display_content(item: Dict, index: int, total: int):
    """Display a content piece for review."""
    quality = item.get("generation_quality", "pending_review")
    quality_badge = {
        "pending_review": f"{BG_YELLOW}{BOLD} PENDING {RESET}",
        "approved": f"{BG_GREEN}{BOLD} APPROVED {RESET}",
        "rejected": f"{BG_RED}{BOLD} REJECTED {RESET}",
    }.get(quality, quality)

    # Get terminal width
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 80

    print(f"\n{'═' * term_width}")
    print(f"  [{index}/{total}] {quality_badge}")
    print(f"{'═' * term_width}")

    # Metadata
    print(f"\n  {BOLD}Title:{RESET}      {CYAN}{item.get('title', 'N/A')}{RESET}")
    print(f"  {BOLD}Type:{RESET}       {item.get('type', 'N/A')} | "
          f"Length: {item.get('length', 'N/A')} | "
          f"Lang: {item.get('lang', 'N/A')}")
    print(f"  {BOLD}Age Group:{RESET}  {item.get('age_group', 'N/A')} "
          f"(ages {item.get('age_min', '?')}-{item.get('age_max', '?')})")
    print(f"  {BOLD}Theme:{RESET}      {item.get('theme', 'N/A')}")
    print(f"  {BOLD}Words:{RESET}      {item.get('word_count', count_words(item.get('text', '')))}")

    # Diversity metadata
    print(f"  {BOLD}Universe:{RESET}   {item.get('universe', 'N/A')}")
    print(f"  {BOLD}Geography:{RESET}  {item.get('geography', 'N/A')}")
    print(f"  {BOLD}Archetype:{RESET}  {item.get('plot_archetype', 'N/A')}")
    print(f"  {BOLD}Lead:{RESET}       {item.get('lead_gender', 'N/A')}")

    # Description
    desc = item.get("description", "")
    if desc:
        print(f"\n  {BOLD}Description:{RESET} {DIM}{desc}{RESET}")

    # Morals
    morals = item.get("morals", [])
    if morals:
        print(f"  {BOLD}Morals:{RESET}      {DIM}{', '.join(morals)}{RESET}")

    # Categories
    cats = item.get("categories", [])
    if cats:
        print(f"  {BOLD}Categories:{RESET}  {DIM}{', '.join(cats)}{RESET}")

    # Text with highlighted markers
    text = item.get("annotated_text", item.get("text", ""))
    print(f"\n  {BOLD}{'─' * (term_width - 4)}{RESET}")
    print(f"  {BOLD}CONTENT:{RESET}\n")

    colored_text = colorize_markers(text)
    wrapped = wrap_text(colored_text, term_width - 4)
    for line in wrapped.split("\n"):
        print(f"  {line}")

    print(f"\n  {BOLD}{'─' * (term_width - 4)}{RESET}")

    # Validation issues
    issues = validate_content(item)
    if issues:
        print(f"\n  {BOLD}{YELLOW}Validation Issues:{RESET}")
        for issue in issues:
            print(f"    {issue}")
    else:
        print(f"\n  {GREEN}✓ All validation checks passed{RESET}")

    # Hindi Devanagari preview
    if item.get("lang") == "hi":
        dev = item.get("annotated_text_devanagari", "")
        if dev:
            print(f"\n  {BOLD}Devanagari Preview:{RESET}")
            dev_preview = dev[:200] + ("..." if len(dev) > 200 else "")
            print(f"  {dev_preview}")


def edit_content(item: Dict) -> bool:
    """Open content in editor for editing. Returns True if modified."""
    editor = os.environ.get("EDITOR", "nano")

    text = item.get("annotated_text", item.get("text", ""))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(f"# Title: {item.get('title', '')}\n")
        f.write(f"# Description: {item.get('description', '')}\n")
        f.write(f"# Morals: {json.dumps(item.get('morals', []))}\n")
        f.write(f"# Categories: {json.dumps(item.get('categories', []))}\n")
        f.write(f"# --- Edit content below this line ---\n\n")
        f.write(text)
        tmp_path = f.name

    try:
        subprocess.run([editor, tmp_path])

        with open(tmp_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Parse header lines
        content_start = 0
        for i, line in enumerate(lines):
            if line.startswith("# --- Edit content"):
                content_start = i + 1
                break
            elif line.startswith("# Title: "):
                new_title = line[9:].strip()
                if new_title:
                    item["title"] = new_title
            elif line.startswith("# Description: "):
                new_desc = line[15:].strip()
                if new_desc:
                    item["description"] = new_desc
            elif line.startswith("# Morals: "):
                try:
                    item["morals"] = json.loads(line[10:].strip())
                except json.JSONDecodeError:
                    pass
            elif line.startswith("# Categories: "):
                try:
                    item["categories"] = json.loads(line[14:].strip())
                except json.JSONDecodeError:
                    pass

        # Get edited content
        new_text = "".join(lines[content_start:]).strip()

        if new_text and new_text != text:
            item["text"] = new_text
            item["annotated_text"] = new_text
            item["word_count"] = count_words(new_text)
            print(f"  {GREEN}✓ Content updated ({item['word_count']} words){RESET}")
            return True
        else:
            print(f"  {DIM}No changes made{RESET}")
            return False

    finally:
        os.unlink(tmp_path)


def interactive_review(content: List[Dict], filters: Dict):
    """Run interactive review session."""
    # Filter content to review
    review_items = []
    for i, item in enumerate(content):
        if item.get("generation_quality") != "pending_review":
            continue
        if filters.get("lang") and item.get("lang") != filters["lang"]:
            continue
        if filters.get("age_group") and item.get("age_group") != filters["age_group"]:
            continue
        if filters.get("type") and item.get("type") != filters["type"]:
            continue
        review_items.append((i, item))

    if not review_items:
        print(f"\n{GREEN}No pending content to review with current filters.{RESET}")
        show_stats(content)
        return

    print(f"\n{BOLD}Starting review of {len(review_items)} pending items...{RESET}")
    print(f"{DIM}Commands: [a]pprove  [r]eject  [e]dit  [s]kip  [q]uit{RESET}\n")

    reviewed = 0

    for idx, (content_idx, item) in enumerate(review_items):
        display_content(item, idx + 1, len(review_items))

        while True:
            try:
                choice = input(f"\n  {BOLD}Action [a/r/e/s/q]:{RESET} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"

            if choice == "a":
                item["generation_quality"] = "approved"
                print(f"  {GREEN}✓ Approved{RESET}")
                reviewed += 1
                break

            elif choice == "r":
                reason = input(f"  {BOLD}Rejection reason:{RESET} ").strip()
                item["generation_quality"] = "rejected"
                item["rejection_reason"] = reason
                print(f"  {RED}✗ Rejected: {reason}{RESET}")
                reviewed += 1
                break

            elif choice == "e":
                modified = edit_content(item)
                if modified:
                    display_content(item, idx + 1, len(review_items))
                # Don't break — let user approve/reject after editing

            elif choice == "s":
                print(f"  {DIM}Skipped{RESET}")
                break

            elif choice == "q":
                save_content(content)
                print(f"\n{BOLD}Session saved.{RESET} Reviewed {reviewed} items this session.")
                show_stats(content)
                return

            else:
                print(f"  {DIM}Unknown command. Use: [a]pprove [r]eject [e]dit [s]kip [q]uit{RESET}")

        # Save after each review
        save_content(content)

    print(f"\n{BOLD}Review complete!{RESET} Reviewed {reviewed} items.")
    show_stats(content)


def save_content(content: List[Dict]):
    """Save content back to JSON file."""
    CONTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="QA review for generated bedtime content")
    parser.add_argument("--age-group", help="Filter by age group (0-1, 2-5, 6-8, 9-12)")
    parser.add_argument("--lang", help="Filter by language (en/hi)")
    parser.add_argument("--type", help="Filter by content type (story/poem)")
    parser.add_argument("--stats", action="store_true", help="Show review progress stats")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve content that passes all validation checks")
    parser.add_argument("--validate", action="store_true",
                        help="Run validation on all content and show issues")
    args = parser.parse_args()

    # Load content
    if not CONTENT_PATH.exists():
        print(f"{RED}Content file not found: {CONTENT_PATH}{RESET}")
        print(f"Run generate_content_matrix.py first to generate content.")
        sys.exit(1)

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)

    if not content:
        print(f"{YELLOW}No content found in {CONTENT_PATH}{RESET}")
        sys.exit(0)

    filters = {
        "lang": args.lang,
        "age_group": args.age_group,
        "type": args.type,
    }

    if args.stats:
        show_stats(content)
        return

    if args.validate:
        print(f"\n{BOLD}Running validation on {len(content)} items...{RESET}\n")
        issues_found = 0
        for item in content:
            # Apply filters
            if filters.get("lang") and item.get("lang") != filters["lang"]:
                continue
            if filters.get("age_group") and item.get("age_group") != filters["age_group"]:
                continue
            if filters.get("type") and item.get("type") != filters["type"]:
                continue

            issues = validate_content(item)
            if issues:
                issues_found += 1
                print(f"  {YELLOW}{item.get('title', 'N/A')}{RESET} "
                      f"({item.get('lang')}/{item.get('age_group')}/{item.get('type')})")
                for issue in issues:
                    print(f"    {issue}")

        if issues_found == 0:
            print(f"  {GREEN}✓ All content passed validation!{RESET}")
        else:
            print(f"\n  {YELLOW}{issues_found} items have validation issues{RESET}")
        return

    if args.auto_approve:
        count = auto_approve(content, filters)
        save_content(content)
        print(f"\n{GREEN}Auto-approved {count} items that passed all validation checks.{RESET}")
        show_stats(content)
        return

    # Interactive review
    interactive_review(content, filters)


if __name__ == "__main__":
    main()
