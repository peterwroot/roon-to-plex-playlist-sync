# Roon to Plex Playlist Sync

Synchronise playlists between Roon and Plex for self-hosted music libraries.

## Overview

This tool reads playlist data from Roon, matches tracks to a Plex Media Server by file path, and creates/replaces playlists in Plex. It bridges the gap between Roon's excellent at-home experience and Plexamp's superior mobile playback.

## How It Works

```
Roon Playlists → m3u files → file paths → Plex track search → Plex playlists
```

Since both Roon and Plex reference the same local music files, the sync relies on **file path matching**. A configurable path-mapping table handles cases where the two services see different mount points (e.g., `/mnt/nas/music` in Roon vs `/data/music` in Plex).

### Two Data Sources

| Source | What it provides | Use case |
|---|---|---|
| **m3u export** (Roon GUI) | Track file paths + artist/title metadata | Primary sync method — reliable, includes paths |
| **Roon Extension API** (`roon_extension.js`) | Playlist names, track titles, artwork | Automated playlist discovery + m3u generation |

### Limitations

- **Roon API is read-only for playlists** — you cannot programmatically create/edit playlists in Roon via the Extension API (see [this feature request](https://github.com/RoonLabs/node-roon-api/issues/23)). The m3u export is the bridge.
- **m3u export is currently manual** — In Roon desktop: Playlist → ⋮ → Export → M3U. An optional Node.js extension (`roon_extension.js`) can automate listing playlists and exporting m3u files via the browse API (but cannot trigger Roon's native export).
- **Streaming tracks (Tidal/Qobuz)** — m3u export only includes local file paths. Tracks from streaming services will not be matched in Plex. This is a known limitation.

## Setup

```bash
pip install -r requirements.txt
```

### Optional: Roon Extension (for automated playlist discovery)

```bash
# Rename and install Node.js dependencies
cp extension-package.json package.json
npm install
# Place roon_extension.js in Roon's Extensions folder or run standalone
# Authorise in Roon Settings → Extensions
```

### Optional: Directory watching (auto-trigger on new m3u files)

```bash
pip install watchdog  # enables auto-detection of new m3u exports
```

## Configuration

Create a `config.yaml` file (see `config.example.yaml`):

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
  dry_run: true              # Preview changes without writing to Plex
  delete_missing: false      # Delete Plex playlists that no longer exist in Roon
```

### Finding Your Plex Token

See [Plex Token Guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

### Exporting from Roon

**Manual (recommended for now):**
1. In Roon desktop, go to a Playlist
2. Click the three dots (⋮) → **Export** → **Export to File**
3. Choose `.m3u` format and save to the directory specified in `roon.export_dir`

**Automated (experimental):**
```bash
node roon_extension.js export_all:/path/to/m3u/exports
```
Requires authorisation in Roon Settings → Extensions on first run.

## Usage

```bash
# Dry run (preview — default, no Plex writes)
python -m roon_to_plex_sync

# Sync all playlists from Roon export dir to Plex
python -m roon_to_plex_sync --sync

# Sync a specific m3u file
python -m roon_to_plex_sync --file /path/to/playlist.m3u --sync

# Sync by playlist name (looks for <name>.m3u in export_dir)
python -m roon_to_plex_sync --name "My Top Tracks" --sync

# Verbose output
python -m roon_to_plex_sync --verbose --dry-run
```

## Architecture

```
roon_to_plex_sync/
├── __init__.py          # Package init
├── __main__.py          # CLI entry point (argparse + rich output)
├── config.py            # YAML config management, path mapping
├── m3u_parser.py        # Roon m3u/m3u8 file parser
├── plex_client.py       # Plex API client (python-plexapi)
└── roon_client.py       # Roon API + extension wrapper

roon_extension.js        # Optional Node.js Roon Extension for auto-export
extension-package.json    # npm package for the extension
config.example.yaml       # Example configuration
requirements.txt          # Python dependencies
pyproject.toml            # Package metadata
```

### Sync Flow

1. **Parse** m3u files from `roon.export_dir` (or specified `--file`)
2. **Map paths** — Convert Roon file paths to Plex file paths via `path_mappings`
3. **Match tracks** — Build an index of Plex library file paths → ratingKeys, then look up each Roon track path
4. **Sync playlists** — For each playlist: delete existing Plex playlist with same name (if present), create new one with matched tracks
5. **Report** — Rich table showing matched/unmatched counts per playlist

## License

MIT
