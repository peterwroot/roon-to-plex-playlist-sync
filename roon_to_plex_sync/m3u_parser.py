"""Parse m3u/m3u8 playlist files exported from Roon.

Roon exports playlists as standard m3u files with absolute file paths.
This module reads those files and returns a structured representation.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class Track:
    """A single track in a playlist."""

    file_path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: int = 0  # seconds; 0 if unknown

    def __repr__(self) -> str:
        if self.title and self.artist:
            return f"Track({self.artist} - {self.title} @ {self.file_path})"
        return f"Track(@ {self.file_path})"


@dataclass
class PlaylistFile:
    """A parsed m3u playlist."""

    name: str
    tracks: List[Track] = field(default_factory=list)
    source_file: str = ""

    @property
    def track_count(self) -> int:
        return len(self.tracks)


def parse_m3u(file_path: str) -> PlaylistFile:
    """Parse an m3u or m3u8 playlist file.

    Supports both standard and extended (EXTM3U) formats.
    Extracts file paths and, for extended format, title/artist metadata.

    Args:
        file_path: Path to the .m3u or .m3u8 file.

    Returns:
        PlaylistFile with parsed tracks.
    """
    path = Path(file_path)
    playlist_name = path.stem  # filename without extension
    tracks: List[Track] = []

    # Determine encoding — try utf-8 first, fall back to latin-1
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        content = ""

    lines = content.splitlines()

    is_extended = content.startswith("#EXTM3U")

    if is_extended:
        tracks = _parse_extended_m3u(lines)
    else:
        tracks = _parse_standard_m3u(lines)

    return PlaylistFile(
        name=playlist_name,
        tracks=tracks,
        source_file=file_path,
    )


def _parse_extended_m3u(lines: List[str]) -> List[Track]:
    """Parse an EXTM3U playlist.

    Extended m3u format:
    ```
    #EXTM3U
    #EXTINF:231,Artist Name - Track Title
    /path/to/track.flac
    #EXTINF:187,Another Artist - Another Title
    /path/to/another.flac
    ```
    """
    tracks: List[Track] = []
    pending_extinf: Track = None  # type: ignore[assignment]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            # Parse: #EXTINF:<duration>,<artist> - <title>
            # Duration can be -1 if unknown
            parts = line[len("#EXTINF:"):].split(",", 1)
            duration = 0
            if len(parts) > 0:
                try:
                    duration = int(parts[0])
                except ValueError:
                    duration = 0

            title_info = parts[1].strip() if len(parts) > 1 else ""

            # Roon exports as "Artist - Title" format
            artist, track_title = _split_artist_title(title_info)

            pending_extinf = Track(
                file_path="",
                title=track_title,
                artist=artist,
                duration=max(duration, 0),
            )

        elif line.startswith("#"):
            # Skip other metadata tags (EXTGENRE, etc.)
            continue

        elif pending_extinf is not None:
            # This line is the file path for the pending EXTINF entry
            pending_extinf.file_path = line
            tracks.append(pending_extinf)
            pending_extinf = None

        else:
            # Standalone file path (no EXTINF preceding it)
            tracks.append(Track(file_path=line))

    return tracks


def _parse_standard_m3u(lines: List[str]) -> List[Track]:
    """Parse a standard m3u playlist (no EXTINF metadata)."""
    tracks: List[Track] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tracks.append(Track(file_path=line))
    return tracks


def _split_artist_title(title_info: str) -> tuple[str, str]:
    """Split 'Artist - Title' or 'Artist – Title' into (artist, title).

    Falls back to using the whole string as the title if no separator found.
    """
    for sep in [" - ", " – ", " — "]:
        if sep in title_info:
            parts = title_info.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    if " - " in title_info:  # fallback for edge cases
        parts = title_info.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", title_info.strip()


def discover_playlists(export_dir: str, pattern: str = "*.m3u") -> List[str]:
    """Find all m3u files in the export directory.

    Args:
        export_dir: Directory to scan.
        pattern: Glob pattern for playlist files (default: *.m3u).

    Returns:
        Sorted list of file paths.
    """
    if not export_dir or not os.path.isdir(export_dir):
        return []

    matches = []
    for root, _dirs, files in os.walk(export_dir):
        for f in files:
            # Match both .m3u and .m3u8
            if f.endswith(".m3u") or f.endswith(".m3u8"):
                matches.append(os.path.join(root, f))

    return sorted(matches)
