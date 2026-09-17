# Roon to Plex Playlist Sync

Synchronise playlists between Roon and Plex for self-hosted music libraries.

## Overview

This tool reads playlist data from Roon (via m3u export files), matches tracks to a Plex Media Server by file path, and creates/replaces playlists in Plex. It bridges the gap between Roon's excellent at-home experience and Plexamp's superior mobile playback.

## How It Works

```
Roon Playlists → m3u files → file paths → Plex track search → Plex playlists
```

Since both Roon and Plex reference the same local music files, the sync relies on **file path matching**. A configurable path-mapping table handles cases where the two services see different mount points (e.g., `/mnt/nas/music` in Roon vs `/data/music` in Plex).

## Setup

```bash
pip install -r requirements.txt
```

## Configuration

Create a `config.yaml` file:

```yaml
plex:
  url: "http://localhost:32400"
  token: "your-plex-token"
  music_library_name: "Music"  # Plex library section to search

roon:
  export_dir: "/path/to/roon/m3u/exports"  # Directory where Roon exports m3u files
  path_mappings:
    # Map Roon paths to Plex paths (optional, one or more entries)
    - roon_prefix: "/mnt/nas/music"
      plex_prefix: "/data/music"

sync:
  playlist_prefix: ""        # Optional prefix for synced playlist names
  playlist_suffix: ""        # Optional suffix for synced playlist names
  dry_run: false              # Preview changes without writing to Plex
  delete_missing: false       # Delete Plex playlists that no longer exist in Roon
```

### Finding Your Plex Token

See [Plex Token Guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

### Exporting from Roon

In Roon desktop:
1. Go to a Playlist
2. Click the three dots (⋮) → **Export** → **Export to File**
3. Choose `.m3u` format and save to the directory specified in `roon.export_dir`

Or automate with the Roon API via `node-roon-api` to iterate playlists and export each as m3u.

## Usage

```bash
# Sync all playlists from Roon export dir to Plex
python -m roon_to_plex_sync

# Dry run (preview what would change)
python -m roon_to_plex_sync --dry-run

# Sync a specific playlist file
python -m roon_to_plex_sync --file /path/to/playlist.m3u
```

## License

MIT
