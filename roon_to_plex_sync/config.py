"""Configuration management for Roon to Plex Playlist Sync."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class PlexConfig:
    """Plex server connection configuration."""

    url: str = "http://localhost:32400"
    token: str = ""
    music_library_name: str = "Music"


@dataclass
class PathMapping:
    """Maps file paths from Roon's view to Plex's view.

    When Roon and Plex run on the same server with the same mount points,
    this is not needed. When they differ (e.g., Docker containers with
    different volume mounts), use these mappings.

    Example:
        roon_prefix: "/mnt/nas/music"
        plex_prefix:  "/data/music"
    """

    roon_prefix: str = ""
    plex_prefix: str = ""

    def apply(self, roon_path: str) -> str:
        """Convert a Roon file path to a Plex file path."""
        if self.roon_prefix and roon_path.startswith(self.roon_prefix):
            return self.plex_prefix + roon_path[len(self.roon_prefix):]
        return roon_path


@dataclass
class RoonConfig:
    """Roon configuration."""

    export_dir: str = ""
    path_mappings: List[PathMapping] = field(default_factory=list)

    def map_path(self, roon_path: str) -> str:
        """Apply path mappings to convert a Roon path to a Plex path.

        Tries each mapping in order and returns the first match.
        If no mapping applies, returns the original path.
        """
        for mapping in self.path_mappings:
            mapped = mapping.apply(roon_path)
            if mapped != roon_path:
                return mapped
        return roon_path


@dataclass
class SyncConfig:
    """Playlist sync behavior configuration."""

    playlist_prefix: str = ""
    playlist_suffix: str = ""
    dry_run: bool = True
    delete_missing: bool = False


@dataclass
class Config:
    """Top-level configuration."""

    plex: PlexConfig = field(default_factory=PlexConfig)
    roon: RoonConfig = field(default_factory=RoonConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from a YAML file.

        Searches in this order:
        1. The path given by ``config_path``
        2. ./config.yaml
        3. ./roon_to_plex_sync.yaml

        If no file is found, returns defaults (suitable for --help / dry-run).
        """
        search_paths: List[str] = []
        if config_path:
            search_paths.append(config_path)
        search_paths.extend(["config.yaml", "roon_to_plex_sync.yaml"])

        config_file = None
        for p in search_paths:
            if os.path.isfile(p):
                config_file = p
                break

        if config_file is None:
            return cls()

        with open(config_file, "r") as f:
            data = yaml.safe_load(f) or {}

        config = cls()

        # Plex settings
        plex_data = data.get("plex", {})
        config.plex = PlexConfig(
            url=plex_data.get("url", "http://localhost:32400"),
            token=plex_data.get("token", ""),
            music_library_name=plex_data.get("music_library_name", "Music"),
        )

        # Roon settings
        roon_data = data.get("roon", {})
        path_mappings = [
            PathMapping(**m) for m in roon_data.get("path_mappings", [])
        ]
        config.roon = RoonConfig(
            export_dir=roon_data.get("export_dir", ""),
            path_mappings=path_mappings,
        )

        # Sync settings
        sync_data = data.get("sync", {})
        config.sync = SyncConfig(
            playlist_prefix=sync_data.get("playlist_prefix", ""),
            playlist_suffix=sync_data.get("playlist_suffix", ""),
            dry_run=sync_data.get("dry_run", True),
            delete_missing=sync_data.get("delete_missing", False),
        )

        return config

    def playlist_name(self, base_name: str) -> str:
        """Apply prefix/suffix to a playlist name."""
        return f"{self.sync.playlist_prefix}{base_name}{self.sync.playlist_suffix}"
