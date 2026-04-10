"""
Extract the release notes for a specific version tag from CHANGELOG.md.

Usage:
    python extract_notes.py v6.6 CHANGELOG.md output.txt

Reads between the heading matching the tag and the next ## heading.
Writes the extracted block to output.txt.
"""

import sys
import re

tag = sys.argv[1]          # e.g. "v6.6"
changelog = sys.argv[2]    # e.g. "CHANGELOG.md"
output = sys.argv[3]       # e.g. "release_notes.txt"

version = tag.lstrip("v")  # "6.6"

with open(changelog, encoding="utf-8") as f:
    content = f.read()

# Match the block starting at ## v{version} up to the next ## heading
pattern = rf"(## v{re.escape(version)}.*?)(?=\n## v|\Z)"
match = re.search(pattern, content, re.DOTALL)

if not match:
    notes = f"Release {tag}\n\nSee CHANGELOG.md for details."
    print(f"WARNING: No entry found in CHANGELOG.md for {tag}")
else:
    notes = match.group(1).strip()
    print(f"Extracted release notes for {tag} ({len(notes)} chars)")

with open(output, "w", encoding="utf-8") as f:
    f.write(notes)
