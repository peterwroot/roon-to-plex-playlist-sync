"""Plex API integration for playlist operations.

Uses python-plexapi to connect to a Plex Media Server and manage playlists.
"""

import logging
from typing import Dict, List, Optional, Tuple

from plexapi.server import PlexServer

from .config import PlexConfig
from .m3u_parser import Track

logger = logging.getLogger(__name__)


class MatchResult:
    """Result of matching a Roon track to a Plex track."""

    def __init__(self, roon_track: Track, plex_key: Optional[str] = None):
        self.roon_track = roon_track
        self.plex_key = plex_key  # Plex ratingKey, if matched
        self.matched = plex_key is not None
        self.plex_path: Optional[str] = roon_track.file_path if matched else None

    def __repr__(self) -> str:
        status = "✓" if self.matched else "✗"
        return f"MatchResult[{status}] {self.roon_track.file_path} → {self.plex_key}"


class PlexClient:
    """Client for interacting with Plex Media Server for playlist sync."""

    def __init__(self, config: PlexConfig):
        self.config = config
        self._plex: Optional[PlexServer] = None
        self._library_section = None
        self._path_index: Dict[str, str] = {}  # file_path → ratingKey
        self._index_built = False

    def connect(self) -> None:
        """Establish a connection to the Plex server."""
        logger.info("Connecting to Plex at %s", self.config.url)
        self._plex = PlexServer(self.config.url, self.config.token)
        logger.info("Connected to Plex server")

    @property
    def plex(self) -> PlexServer:
        if self._plex is None:
            self.connect()
        assert self._plex is not None
        return self._plex

    def get_library_section(self):
        """Get the configured music library section."""
        if self._library_section is None:
            self._library_section = self.plex.library.section(
                self.config.music_library_name
            )
        return self._library_section

    def build_path_index(self) -> Dict[str, str]:
        """Build a lookup index of file paths → ratingKeys for the music library.

        Indexes all tracks in the library once, then caches. For very large
        libraries (>100k tracks) this may take some time on first run.
        """
        if self._index_built:
            return self._path_index

        logger.info(
            "Building path index for music library '%s'...",
            self.config.music_library_name,
        )
        section = self.get_library_section()
        count = 0

        # Iterate all tracks in the music library
        for item in section.search(libtype="track", title=""):
            for part in item.iterParts():
                if part.file:
                    # Index the exact path
                    if part.file not in self._path_index:
                        self._path_index[part.file] = str(item.ratingKey)
                    # Also index lowercased for case-insensitive fallback
                    lower = part.file.lower()
                    if lower not in self._path_index:
                        self._path_index[lower] = str(item.ratingKey)
                    count += 1

        logger.info("Indexed %d track file paths", count)
        self._index_built = True
        return self._path_index

    def find_track_by_path(self, file_path: str) -> Optional[str]:
        """Find a Plex track's ratingKey by file path.

        Returns the ratingKey (str) if found, None otherwise.
        """
        # Try the pre-built index first (fast)
        index = self.build_path_index()
        if file_path in index:
            return index[file_path]
        lower = file_path.lower()
        if lower in index:
            return self._path_index[lower]

        # Fallback: direct Plex search (handles paths the index missed)
        results = self.get_library_section().search(file=file_path)
        if results:
            return str(results[0].ratingKey)

        return None

    def find_tracks_by_paths(self, paths: List[str]) -> List[MatchResult]:
        """Find Plex tracks matching a list of file paths.

        Args:
            paths: List of file paths from the Roon playlist.

        Returns:
            List of MatchResult objects (one per input path).
        """
        results: List[MatchResult] = []
        index = self.build_path_index()

        for path in paths:
            roon_track = Track(file_path=path)
            plex_key = index.get(path) or index.get(path.lower())
            if plex_key is None:
                # Try a direct Plex search as fallback
                plex_key = self.find_track_by_path(path)
            results.append(MatchResult(roon_track, plex_key))
        return results

    def delete_playlist(self, title: str) -> bool:
        """Delete a playlist by title if it exists.

        Returns True if a playlist was deleted, False if not found.
        """
        try:
            playlist = self.plex.playlist(title)
            playlist.delete()
            logger.info("Deleted existing playlist '%s'", title)
            return True
        except Exception:
            return False

    def playlist_exists(self, title: str) -> bool:
        """Check if a playlist with the given title exists."""
        try:
            self.plex.playlist(title)
            return True
        except Exception:
            return False

    def list_playlists(self) -> List[str]:
        """Return titles of all existing playlists."""
        return [p.title for p in self.plex.playlists()]

    def create_playlist(
        self, title: str, rating_keys: List[str]
    ) -> Tuple[bool, str]:
        """Create a new playlist in Plex with the given track ratingKeys.

        Args:
            title: The playlist name.
            rating_keys: List of Plex ratingKey strings for the tracks.

        Returns:
            (success, message)
        """
        if not rating_keys:
            return False, f"No tracks to add for playlist '{title}'"

        section = self.get_library_section()
        try:
            self.plex.createPlaylist(
                title=title,
                items=rating_keys,
                section=section.key,
            )
            return True, f"Created playlist '{title}' with {len(rating_keys)} tracks"
        except Exception as e:
            return False, f"Error creating playlist '{title}': {e}"

    def sync_playlist(
        self,
        title: str,
        track_paths: List[str],
    ) -> Tuple[bool, str, List[MatchResult], List[str]]:
        """Create or replace a playlist in Plex.

        Args:
            title: The playlist name in Plex.
            track_paths: List of file paths from the Roon playlist.

        Returns:
            (success, message, match_results, unmatched_paths)
        """
        # Delete existing playlist if present (to recreate fresh)
        existed = self.playlist_exists(title)
        if existed:
            self.delete_playlist(title)

        # Match all paths to Plex tracks
        match_results = self.find_tracks_by_paths(track_paths)

        matched_keys = [r.plex_key for r in match_results if r.matched]
        unmatched_paths = [
            r.roon_track.file_path for r in match_results if not r.matched
        ]

        if not matched_keys:
            return (
                False,
                f"No tracks matched for playlist '{title}' "
                f"(out of {len(track_paths)} paths)",
                match_results,
                unmatched_paths,
            )

        success, message = self.create_playlist(title, matched_keys)
        action = "Replaced" if existed else "Created"
        if success:
            message = (
                f"{action} playlist '{title}' with {len(matched_keys)} tracks"
                f" ({len(unmatched_paths)} unmatched)"
            )

        return success, message, match_results, unmatched_paths
