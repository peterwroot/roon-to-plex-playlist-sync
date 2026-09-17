"""Core sync engine: orchestrates Roon → Plex playlist synchronisation."""

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from .config import Config
from .m3u_parser import PlaylistFile, Track, discover_playlists, parse_m3u
from .plex_client import PlexClient

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of syncing a single playlist."""

    playlist_name: str
    source_file: str
    success: bool
    message: str
    matched_count: int = 0
    unmatched_count: int = 0
    total_tracks: int = 0
    unmatched_paths: List[str] = field(default_factory=list)


class SyncEngine:
    """Orchestrates synchronisation between Roon playlist exports and Plex."""

    def __init__(self, config: Config):
        self.config = config
        self.plex = PlexClient(config.plex)
        self._connected = False

    def _ensure_connected(self) -> None:
        """Connect to Plex if not already connected."""
        if not self._connected:
            self.plex.connect()
            self._connected = True

    def sync_single(
        self, m3u_path: str, dry_run: Optional[bool] = None
    ) -> SyncResult:
        """Sync a single m3u playlist file to Plex.

        Args:
            m3u_path: Path to the .m3u/.m3u8 file exported from Roon.
            dry_run: If True, only report what would happen (no Plex writes).
                     Falls back to config.sync.dry_run if None.

        Returns:
            SyncResult with details of what happened.
        """
        dry = dry_run if dry_run is not None else self.config.sync.dry_run

        # Parse the m3u file
        playlist: PlaylistFile = parse_m3u(m3u_path)
        plex_name = self.config.playlist_name(playlist.name)

        logger.info(
            "Processing playlist '%s' (%d tracks, source: %s)",
            playlist.name,
            playlist.track_count,
            m3u_path,
        )

        # Apply path mappings from Roon to Plex
        mapped_paths: List[str] = []
        for track in playlist.tracks:
            mapped = self.config.roon.map_path(track.file_path)
            mapped_paths.append(mapped)

        if dry:
            # In dry-run mode, try to match against Plex (if available) for
            # a realistic preview, but don't write anything.
            matched = 0
            unmatched_paths = list(mapped_paths)
            try:
                self._ensure_connected()
                match_results = self.plex.find_tracks_by_paths(mapped_paths)
                matched = sum(1 for r in match_results if r.matched)
                unmatched_paths = [
                    r.roon_track.file_path for r in match_results if not r.matched
                ]
            except Exception as e:
                logger.warning(
                    "Could not connect to Plex for dry-run matching (%s). "
                    "Showing unverified results.", e
                )

            return SyncResult(
                playlist_name=plex_name,
                source_file=m3u_path,
                success=True,
                message=f"[DRY RUN] Would sync {matched}/{len(mapped_paths)} tracks "
                f"to playlist '{plex_name}'",
                matched_count=matched,
                unmatched_count=len(unmatched_paths),
                total_tracks=len(mapped_paths),
                unmatched_paths=unmatched_paths,
            )

        # Real sync
        self._ensure_connected()
        success, message, match_results, unmatched = self.plex.sync_playlist(
            plex_name, mapped_paths
        )

        return SyncResult(
            playlist_name=plex_name,
            source_file=m3u_path,
            success=success,
            message=message,
            matched_count=sum(1 for r in match_results if r.matched),
            unmatched_count=len(unmatched),
            total_tracks=len(mapped_paths),
            unmatched_paths=unmatched,
        )

    def sync_all(self, dry_run: Optional[bool] = None) -> List[SyncResult]:
        """Sync all m3u files from the Roon export directory.

        Args:
            dry_run: If True, only report what would happen.

        Returns:
            List of SyncResults, one per playlist file.
        """
        if not self.config.roon.export_dir:
            logger.error("roon.export_dir is not configured")
            return []

        if not os.path.isdir(self.config.roon.export_dir):
            logger.error(
                "Export directory does not exist: %s", self.config.roon.export_dir
            )
            return []

        playlist_files = discover_playlists(self.config.roon.export_dir)

        if not playlist_files:
            logger.warning("No .m3u or .m3u8 files found in %s", self.config.roon.export_dir)
            return []

        logger.info("Found %d playlist file(s) to sync", len(playlist_files))

        results: List[SyncResult] = []
        for m3u_path in playlist_files:
            result = self.sync_single(m3u_path, dry_run=dry_run)
            results.append(result)

            if result.success:
                logger.info("✓ %s", result.message)
            else:
                logger.error("✗ %s", result.message)

        return results

    def sync_by_name(
        self, playlist_name: str, dry_run: Optional[bool] = None
    ) -> Optional[SyncResult]:
        """Sync a single playlist by name (looks for <name>.m3u in export dir).

        Args:
            playlist_name: The Roon playlist name (file stem without extension).

        Returns:
            SyncResult, or None if the file wasn't found.
        """
        if not self.config.roon.export_dir:
            logger.error("roon.export_dir is not configured")
            return None

        export_dir = self.config.roon.export_dir
        for ext in (".m3u", ".m3u8"):
            candidate = os.path.join(export_dir, playlist_name + ext)
            if os.path.isfile(candidate):
                return self.sync_single(candidate, dry_run=dry_run)

        logger.error(
            "Playlist '%s' not found in %s (looked for .m3u and .m3u8)",
            playlist_name,
            export_dir,
        )
        return None
