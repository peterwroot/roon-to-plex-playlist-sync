/**
 * Roon Extension for Roon-to-Plex Playlist Sync.
 *
 * This extension connects to Roon Core and provides a JSON-over-stdout
 * interface to enumerate playlists and their tracks. It can also export
 * playlists as m3u files to a specified directory.
 *
 * Setup:
 *   1. Install Node.js (>= 10.x)
 *   2. npm install
 *   3. Place this file in Roon's Extensions folder or run standalone
 *   4. Authorise in Roon Settings → Extensions
 *
 * Usage:
 *   node roon_extension.js list_playlists
 *   node roon_extension.js export_all:/path/to/m3u/exports
 *   node roon_extension.js get_playlist:"My Playlist Name"
 *
 * The extension auto-discovers Roon Cores on the local network.
 * On first run, Roon will prompt you to authorise this extension.
 */

'use strict';

const RoonApi = require('node-roon-api');
const RoonApiBrowse = require('node-roon-api-browse');

// Extension metadata — Roon displays this in Settings → Extensions
const appinfo = {
    extension_id: 'com.github.ptroth.roon-to-plex-sync',
    display_name: 'Roon to Plex Playlist Sync',
    display_version: '0.1.0',
    publisher: 'Peter Wroot',
    email: 'peter@example.com',
    website: 'https://github.com/peterwroot/roon-to-plex-playlist-sync',
};

const roon = new RoonApi(appinfo);

// Store the paired core reference
let currentCore = null;

/**
 * Browse the playlists hierarchy and return all playlist names + item keys.
 */
function listPlaylists(core) {
    return new Promise((resolve, reject) => {
        const browse = new RoonApiBrowse(core);
        const playlists = [];

        browse.browse({
            hierarchy: 'playlists',
            pop_all: true,
        }, function (err, body) {
            if (err) {
                reject(err);
                return;
            }

            // Load items at the current level (top-level playlists)
            browse.load({
                hierarchy: 'playlists',
                count: 1000,
            }, function (err, body) {
                if (err) {
                    reject(err);
                    return;
                }

                const items = body.items || [];
                items.forEach(function (item) {
                    if (item.title && item.item_key) {
                        playlists.push({
                            name: item.title,
                            item_key: item.item_key,
                        });
                    }
                });

                resolve(playlists);
            });
        });
    });
}

/**
 * Load all tracks from a specific playlist by item_key.
 */
function loadPlaylistTracks(core, itemKey) {
    return new Promise((resolve, reject) => {
        const browse = new RoonApiBrowse(core);
        const tracks = [];
        let level = 1; // playlists are at level 0, tracks at level 1

        browse.browse({
            hierarchy: 'playlists',
            item_key: itemKey,
        }, function (err, body) {
            if (err) {
                reject(err);
                return;
            }

            function loadLevel(offset) {
                browse.load({
                    hierarchy: 'playlists',
                    level: level,
                    offset: offset || 0,
                    count: 500,
                }, function (err, body) {
                    if (err) {
                        reject(err);
                        return;
                    }

                    const items = body.items || [];
                    items.forEach(function (item) {
                        tracks.push({
                            title: item.title || '',
                            subtitle: item.subtitle || '',
                            image_key: item.image_key || '',
                            item_key: item.item_key || '',
                        });
                    });

                    // Check if there are more items
                    const list = body.list;
                    if (list && list.count && (offset || 0) + items.length < list.count) {
                        loadLevel((offset || 0) + items.length);
                    } else {
                        resolve(tracks);
                    }
                });
            }

            loadLevel(0);
        });
    });
}

/**
 * Export all playlists as m3u files to the specified directory.
 */
async function exportAllToM3u(exportDir) {
    if (!currentCore) {
        throw new Error('No Roon Core connected');
    }

    const fs = require('fs');
    const path = require('path');

    const playlists = await listPlaylists(currentCore);

    if (!fs.existsSync(exportDir)) {
        fs.mkdirSync(exportDir, { recursive: true });
    }

    const results = [];
    for (const pl of playlists) {
        try {
            const tracks = await loadPlaylistTracks(currentCore, pl.item_key);

            // Build m3u content
            let m3u = '#EXTM3U\n';
            for (const t of tracks) {
                // Roon browse doesn't include file paths, so we use the
                // track metadata (artist - title) as fallback.
                // For file paths, the user should use Roon's manual export.
                const artistTitle = t.subtitle ? `${t.subtitle} - ${t.title}` : t.title;
                const display = artistTitle || t.title || 'Unknown';
                m3u += `#EXTINF:-1,${display}\n# Unknown path\n`;
            }

            const safeName = pl.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
            const filePath = path.join(exportDir, `${safeName}.m3u`);
            fs.writeFileSync(filePath, m3u, 'utf-8');

            results.push({
                name: pl.name,
                file: filePath,
                track_count: tracks.length,
                success: true,
            });
        } catch (e) {
            results.push({
                name: pl.name,
                error: e.message,
                success: false,
            });
        }
    }

    return results;
}

// --- Main execution ---

roon.init_services({
    required_services: [RoonApiBrowse],
    provided_services: [],
});

roon.start_discovery({
    // If you want to auto-reject cores you're not interested in,
    // you can do it here. Usually you just want to accept all.
    core_paired: function (core) {
        currentCore = core;

        // Process command-line arguments
        const args = process.argv.slice(2);
        if (args.length === 0) {
            console.log(JSON.stringify({
                error: 'No command specified. Usage: node roon_extension.js <command>',
                commands: ['list_playlists', 'export_all:<dir>', 'get_playlist:<name>'],
            }));
            process.exit(0);
        }

        const command = args[0];

        (async function () {
            try {
                if (command === 'list_playlists') {
                    const playlists = await listPlaylists(core);
                    console.log(JSON.stringify({
                        playlists: playlists,
                    }));
                } else if (command.startsWith('export_all:')) {
                    const exportDir = command.substring('export_all:'.length);
                    const results = await exportAllToM3u(exportDir);
                    console.log(JSON.stringify({
                        exported: results.length,
                        results: results,
                    }));
                } else if (command.startsWith('get_playlist:')) {
                    const name = command.substring('get_playlist:'.length);
                    const playlists = await listPlaylists(core);
                    const found = playlists.find(p => p.name === name);
                    if (!found) {
                        console.log(JSON.stringify({
                            error: `Playlist '${name}' not found`,
                        }));
                    } else {
                        const tracks = await loadPlaylistTracks(core, found.item_key);
                        console.log(JSON.stringify({
                            playlist: name,
                            tracks: tracks,
                        }));
                    }
                } else {
                    console.log(JSON.stringify({
                        error: `Unknown command: ${command}`,
                    }));
                }
            } catch (e) {
                console.log(JSON.stringify({ error: e.message }));
            }
            process.exit(0);
        })();
    },

    core_unpaired: function (core) {
        console.log(JSON.stringify({ error: 'Roon Core disconnected' }));
        process.exit(1);
    },
});

// Timeout: if we don't connect within 30 seconds, give up
setTimeout(function () {
    if (!currentCore) {
        console.log(JSON.stringify({
            error: 'No Roon Core found within 30 seconds. ' +
                   'Ensure Roon Core is running and on the same network.',
        }));
        process.exit(1);
    }
}, 30000);
