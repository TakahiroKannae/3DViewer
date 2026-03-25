"""Sequential file grouping logic.

Detects frame sequences like:
  render.####.png  →  render.0001.png, render.0002.png, ...
  frame_0001.exr   →  frame_0001.exr, frame_0002.exr, ...

Rules:
  - Same directory, same extension
  - Name differs only by a contiguous block of digits
  - At least 2 files match the pattern

Files that are part of a sequence are grouped into a SequenceGroup object.
Standalone files are returned as-is (Path objects).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Regex: captures prefix, digit-block, suffix, extension
_SEQ_RE = re.compile(r"^(.*?)(\d+)(.*?)$")


@dataclass
class SequenceGroup:
    """Represents a group of sequentially numbered files."""
    pattern: str               # display pattern, e.g. "render.####.exr"
    directory: Path
    extension: str             # without dot
    members: list[Path] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return len(self.members)

    @property
    def first_frame(self) -> Path:
        return self.members[0]

    @property
    def display_name(self) -> str:
        return self.pattern

    @property
    def stat(self):
        """Use the first frame's stat for cache key purposes."""
        return self.first_frame.stat()


def _make_key(name: str) -> tuple[str, str, str] | None:
    """Return (prefix, suffix, ext) grouping key, or None if no digit block found."""
    stem, _, ext = name.rpartition(".")
    if not stem:
        stem = name
        ext = ""

    m = _SEQ_RE.match(stem)
    if not m:
        return None
    prefix, digits, suffix = m.groups()
    return (prefix, suffix, ext.lower())


def group_sequences(
    paths: list[Path],
    min_frames: int = 2,
) -> list[Path | SequenceGroup]:
    """Group a flat list of paths into sequences where applicable.

    Returns a list where sequential runs are replaced by SequenceGroup
    objects.  Standalone files remain as Path objects.

    Args:
        paths: flat list of file paths (all in same directory, or mixed)
        min_frames: minimum number of files to form a sequence (default 2)
    """
    # Group by (directory, prefix, suffix, ext)
    buckets: dict[tuple, list[tuple[int, Path]]] = {}

    for p in paths:
        key_parts = _make_key(p.name)
        if key_parts is None:
            continue
        prefix, suffix, ext = key_parts
        bucket_key = (str(p.parent), prefix, suffix, ext)
        stem = p.stem
        m = _SEQ_RE.match(stem)
        if not m:
            continue
        frame_num = int(m.group(2))
        buckets.setdefault(bucket_key, []).append((frame_num, p))

    # Identify which paths are in a valid sequence
    in_sequence: set[Path] = set()
    groups: list[SequenceGroup] = []

    for (dirstr, prefix, suffix, ext), items in buckets.items():
        if len(items) < min_frames:
            continue
        items.sort(key=lambda x: x[0])
        members = [p for _, p in items]

        # Build a display pattern using # for digits
        sample_name = members[0].name
        stem_m = _SEQ_RE.match(members[0].stem)
        num_digits = len(stem_m.group(2))
        hashes = "#" * num_digits
        if suffix:
            pattern_stem = f"{prefix}{hashes}{suffix}"
        else:
            pattern_stem = f"{prefix}{hashes}"
        pattern = f"{pattern_stem}.{ext}" if ext else pattern_stem

        grp = SequenceGroup(
            pattern=pattern,
            directory=Path(dirstr),
            extension=ext,
            members=members,
        )
        groups.append(grp)
        in_sequence.update(members)

    result: list[Path | SequenceGroup] = []
    seen_groups: set[int] = set()

    for p in paths:
        if p in in_sequence:
            # Attach the group the first time we see a member
            for i, grp in enumerate(groups):
                if p == grp.first_frame and i not in seen_groups:
                    result.append(grp)
                    seen_groups.add(i)
                    break
            # Other members are skipped (already represented by group)
        else:
            result.append(p)

    return result
