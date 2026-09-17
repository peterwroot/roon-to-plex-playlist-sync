"""CLI entry point for Roon to Plex Playlist Sync."""

import argparse
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.panel import Panel

from .config import Config
from .sync_engine import SyncEngine

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rich formatting."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def print_summary(results: list) -> None:
    """Print a summary table of sync results."""
    if not results:
        console.print("\n[yellow]No playlists were processed.[/yellow]")
        return

    table = Table(title="Sync Results", show_lines=True)
    table.add_column("Playlist", style="cyan", overflow="fold")
    table.add_column("Status", justify="center", width=8)
    table.add_column("Matched", justify="right", width=10)
    table.add_column("Unmatched", justify="right", width=12)
    table.add_column("Total", justify="right", width=8)
    table.add_column("Details", overflow="fold")

    total_matched = 0
    total_unmatched = 0
    total_tracks = 0
    success_count = 0
    fail_count = 0

    for r in results:
        status_str = "[green]✓[/green]" if r.success else "[red]✗[/red]"
        if r.success:
            success_count += 1
        else:
            fail_count += 1
        total_matched += r.matched_count
        total_unmatched += r.unmatched_count
        total_tracks += r.total_tracks

        table.add_row(
            r.playlist_name,
            status_str,
            str(r.matched_count),
            str(r.unmatched_count),
            str(r.total_tracks),
            r.message,
        )

    # Summary row
    console.print(table)

    summary = (
        f"[bold green]{success_count}[/bold green] succeeded, "
        f"[bold red]{fail_count}[/bold red] failed | "
        f"Total: {total_matched} matched, {total_unmatched} unmatched, "
        f"{total_tracks} tracks in {len(results)} playlist(s)"
    )
    console.print(Panel(summary, title="Summary", border_style="blue"))


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="roon-to-plex-sync",
        description="Synchronise playlists from Roon (m3u exports) to Plex Media Server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Sync all playlists (dry-run by default)
  %(prog)s --sync                    # Sync all playlists (write to Plex)
  %(prog)s --file my_playlist.m3u    # Sync a single playlist file
  %(prog)s --name "My Top Tracks"    # Sync a single playlist by name
  %(prog)s --dry-run --verbose       # Preview with debug logging
        """,
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config.yaml (default: ./config.yaml or ./roon_to_plex_sync.yaml)",
    )
    parser.add_argument(
        "--file", "-f",
        default=None,
        help="Sync a single m3u file by path",
    )
    parser.add_argument(
        "--name", "-n",
        default=None,
        help="Sync a single playlist by name (looks for <name>.m3u in export dir)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Actually write to Plex (overrides config dry_run setting)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to Plex (default unless --sync is used)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    # Load configuration
    config = Config.load(args.config)

    # Determine dry-run mode
    if args.sync:
        config.sync.dry_run = False
    elif args.dry_run or (not args.sync and not args.dry_run):
        # Default to dry-run unless --sync explicitly given
        if not args.sync:
            config.sync.dry_run = True

    dry_run = config.sync.dry_run

    # Validate config
    if not config.plex.token or config.plex.token == "CHANGE_ME_YOUR_PLEX_TOKEN":
        console.print("[red]Error: Plex token not configured. Edit config.yaml.[/red]")
        console.print("  Copy config.example.yaml to config.yaml and set your Plex token.")
        return 1

    engine = SyncEngine(config)

    # Determine what to sync
    if args.file:
        results = [engine.sync_single(args.file, dry_run=dry_run)]
    elif args.name:
        result = engine.sync_by_name(args.name, dry_run=dry_run)
        results = [result] if result else []
    else:
        results = engine.sync_all(dry_run=dry_run)
        if not results:
            if not config.roon.export_dir:
                console.print(
                    "[red]Error: roon.export_dir is not configured in config.yaml[/red]"
                )
                return 1

    if not results:
        console.print("[yellow]No playlists to sync. Exiting.[/yellow]")
        return 0

    print_summary(results)

    # Exit with non-zero if any failed
    all_success = all(r.success for r in results)
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
