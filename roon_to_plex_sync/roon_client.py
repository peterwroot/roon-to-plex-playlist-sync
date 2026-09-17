"""Roon API client for browsing playlists and exporting m3u files.

Uses the official Roon Extension API (``node-roon-api``) via a lightweight
subprocess wrapper. The Roon Extension API is read-only for playlists —
you can browse and enumerate contents but cannot create or edit playlists
programmatically (see https://github.com/RoonLabs/node-roon-api/issues/23).

Two data sources are supported:

1. **Browse API** — Enumerates playlists and their tracks via the WebSocket
   browse service. Returns track titles and metadata but NOT file paths.
2. **m3u export** — Roon's built-in export feature writes m3u files with
   absolute file paths. This tool watches a directory for these files.

The m3u approach is the primary sync method because file paths are needed
to match tracks between Roon and Plex (which share the same local files).
The browse API is used for playlist discovery and metadata enrichment.

Usage:
    The Roon extension (see ``roon_extension.js``) must be installed and
    authorised in Roon Settings → Extensions. Once running, it provides
    a JSON-over-stdin/JSON-over-stdout interface.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RoonTrack:
    """A track from a Roon playlist."""

    title: str = ""
    subtitle: str = ""  # Artist or album depending on context
    image_key: str = ""
    item_key: str = ""
    file_path: str = ""  # Populated via m3u export or metadata lookup

    def __repr__(self) -> str:
        if self.file_path:
            return f"RoonTrack({self.title} @ {self.file_path})"
        return f"RoonTrack({self.title})"


@dataclass
class RoonPlaylist:
    """A Roon playlist with its tracks."""

    name: str
    item_key: str = ""
    tracks: List[RoonTrack] = field(default_factory=list)


class RoonExtensionClient:
    """Communicate with a Roon Extension that exposes playlist data.

    This wraps a Node.js script (``roon_extension.js``) that uses the
    official ``node-roon-api`` library to browse Roon's playlist hierarchy
    and output JSON to stdout.

    The extension must be placed in Roon's Extensions folder and authorised.
    See https://github.com/RoonLabs/node-roon-api for setup details.
    """

    def __init__(self, extension_script: Optional[str] = None, core_host: Optional[str] = None, core_port: Optional[int] = None):
        self.extension_script = extension_script or self._default_extension_path()
        self.core_host = core_host
        self.core_port = core_port

    def _build_command(self, command: str) -> list[str]:
        """Build the full node command with optional host/port flags."""
        cmd = ["node", self.extension_script]
        if self.core_host and self.core_port:
            cmd.extend(["--host", self.core_host, "--port", str(self.core_port)])
        cmd.append(command)
        return cmd

    def _default_extension_path(self) -> str:
        """Path to the bundled roon_extension.js script."""
        return str(Path(__file__).parent.parent / "roon_extension.js")

    def _run_extension(self, command: str) -> dict:
        """Run the Roon extension script with a command and parse JSON output.

        Args:
            command: A command string understood by the extension
                      (e.g., "list_playlists", "export_playlist:name").

        Returns:
            Parsed JSON response dict.
        """
        if not os.path.isfile(self.extension_script):
            raise FileNotFoundError(
                f"Roon extension script not found at {self.extension_script}. "
                "Ensure node-roon-api and its dependencies are installed."
            )

        cmd = self._build_command(command)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("Roon extension error: %s", result.stderr)
            return {"error": result.stderr}

        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Roon extension output: %s", e)
            return {"error": str(e)}


@dataclass
class RoonApiConfig:
    """Configuration for connecting to Roon Core."""

    core_ip: str = "localhost"
    core_port: int = 9410  # Default Roon Core websocket port
    # The extension ID registered in Roon
    extension_id: str = "com.github.ptroth.roon-to-plex-sync"
    token_file: str = "roon_api_token"


class RoonApiBrowser:
    """Browse Roon playlists using the node-roon-api browse service.

    This is a higher-level client that uses the browse API to enumerate
    playlists and their tracks. It works with an authorised Roon extension.

    For file paths, use the m3u export approach instead — the browse API
    does not expose local file paths for tracks.
    """

    def __init__(self, config: RoonApiConfig):
        self.config = config
        self._client: Optional[RoonExtensionClient] = None

    def list_playlists(self) -> List[str]:
        """List all Roon playlist names."""
        result = self._run("list_playlists")
        if "error" in result:
            raise RuntimeError(f"Roon API error: {result['error']}")
        return result.get("playlists", [])

    def get_playlist_tracks(self, playlist_name: str) -> List[RoonTrack]:
        """Get all tracks in a named playlist.

        Returns tracks with title/artist metadata but without file paths.
        For file paths, use the m3u export approach.
        """
        result = self._run(f"get_playlist:{playlist_name}")
        if "error" in result:
            raise RuntimeError(f"Roon API error: {result['error']}")
        tracks = []
        for t in result.get("tracks", []):
            tracks.append(RoonTrack(**t))
        return tracks

    def _run(self, command: str) -> dict:
        if self._client is None:
            self._client = RoonExtensionClient(
                core_host=self.config.core_ip,
                core_port=self.config.core_port,
            )
        return self._client._run_extension(command)


def export_all_playlists_to_m3u(
    export_dir: str, dry_run: bool = False
) -> List[str]:
    """Trigger m3u export of all Roon playlists.

    This requires a Roon extension that can iterate playlists and export
    each as m3u. Currently Roon's Extension API cannot trigger exports
    programmatically, so this function documents the manual process:

    1. In Roon desktop, go to each playlist
    2. Click ⋮ → Export → Export to File → M3U
    3. Save to ``export_dir``

    Future: A Roon extension using node-roon-api-browse can automate this
    by reading each playlist's track metadata and writing m3u files directly.

    Args:
        export_dir: Directory to write m3u files to.
        dry_run: If True, only list what would be done.

    Returns:
        List of playlist names that would be/were exported.
    """
    logger.warning(
        "Automated Roon m3u export requires a Roon Extension. "
        "See roon_extension.js for the prototype."
    )
    # In dry-run, we can't list playlists without the extension.
    # The actual sync engine will pick up files from export_dir once
    # they're placed there (manually via Roon GUI for now).
    return []


def watch_export_dir(export_dir: str, callback=None) -> None:
    """Watch a directory for new/modified m3u files.

    Uses watchdog if available, otherwise provides a polling fallback.

    Args:
        export_dir: Directory to watch for m3u files.
        callback: Function called with the file path when a new m3u is found.
    """
    logger.info("Watching %s for m3u files...", export_dir)

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class M3uHandler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory and event.src_path.endswith((".m3u", ".m3u8")):
                    logger.info("New playlist file detected: %s", event.src_path)
                    if callback:
                        callback(event.src_path)

        observer = Observer()
        observer.schedule(M3uHandler(), export_dir, recursive=False)
        observer.start()
        logger.info("Watchdog observer started (requires 'watchdog' package)")

    except ImportError:
        logger.info("watchdog not installed; using polling fallback")
        _poll_export_dir(export_dir, callback)


def _poll_export_dir(export_dir: str, callback=None, interval: int = 30) -> None:
    """Fallback polling implementation for watching the export directory."""
    import time

    seen: set[str] = set()
    while True:
        from ..m3u_parser import discover_playlists

        current = set(discover_playlists(export_dir))
        new_files = current - seen
        for f in new_files:
            logger.info("New playlist file detected: %s", f)
            if callback:
                callback(f)
        seen = current
        time.sleep(interval)
