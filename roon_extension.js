/**
 * Roon Extension for Roon-to-Plex Playlist Sync.
 *
 * This extension connects to Roon Core and provides commands to enumerate
 * playlists and export them as m3u files.
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
 *   # Or connect directly to a known Core (skip UDP discovery)
 *   node roon_extension.js --host 192.168.1.100 --port 9330 list_playlists
 *
 * The extension auto-discovers Roon Cores on the local network, or connects
 * directly if --host and --port are provided.
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

// Store the paired core reference
let currentCore = null;

// Parse CLI args for optional host/port (direct connect instead of discovery)
const cliArgs = process.argv.slice(2);
const hostIdx = cliArgs.indexOf('--host');
const portIdx = cliArgs.indexOf('--port');
const directHost = hostIdx !== -1 ? cliArgs[hostIdx + 1] : null;
const directPort = portIdx !== -1 && hostIdx !== -1 ? parseInt(cliArgs[portIdx + 1], 10) : null;

// Filter out --host/--port and their values from command args
const commandOnlyArgs = [];
for (let i = 0; i < cliArgs.length; i++) {
    // Must check hostIdx/portIdx >= 0 to avoid -1 + 1 === 0 matching the command arg
    if ((hostIdx >= 0 && (i === hostIdx || i === hostIdx + 1)) ||
        (portIdx >= 0 && (i === portIdx || i === portIdx + 1))) continue;
    commandOnlyArgs.push(cliArgs[i]);
}
const command = commandOnlyArgs[0];

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
        const level = 1; // playlists are at level 0, tracks at level 1

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

            let m3u = '#EXTM3U\n';
            for (const t of tracks) {
                const display = t.subtitle ? `${t.subtitle} - ${t.title}` : t.title;
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

/**
 * Process CLI commands after Roon Core is connected.
 */
function processCommand(core, cmd) {
    if (!cmd) {
        console.log(JSON.stringify({
            error: 'No command specified.',
            commands: ['list_playlists', 'export_all:<dir>', 'get_playlist:<name>'],
        }));
        process.exit(1);
    }

    if (cmd === 'list_playlists') {
        return listPlaylists(core)
            .then(playlists => {
                console.log(JSON.stringify({ playlists: playlists }));
            });
    }

    if (cmd.startsWith('export_all:')) {
        const exportDir = cmd.substring('export_all:'.length);
        return exportAllToM3u(exportDir)
            .then(results => {
                console.log(JSON.stringify({
                    exported: results.length,
                    results: results,
                }));
            });
    }

    if (cmd.startsWith('get_playlist:')) {
        const name = cmd.substring('get_playlist:'.length);
        return listPlaylists(core)
            .then(playlists => {
                const found = playlists.find(p => p.name === name);
                if (!found) {
                    console.log(JSON.stringify({
                        error: `Playlist '${name}' not found`,
                    }));
                    return;
                }
                return loadPlaylistTracks(core, found.item_key)
                    .then(tracks => {
                        console.log(JSON.stringify({
                            playlist: name,
                            tracks: tracks,
                        }));
                    });
            });
    }

    console.log(JSON.stringify({
        error: `Unknown command: ${cmd}`,
    }));
    process.exit(1);
}

// --- Main execution ---
// Callback: called when Roon pairs us (extension authorisation accepted)
function onCorePaired(core) {
    currentCore = core;
    // Debug: log the parsed command for troubleshooting
    if (process.env.DEBUG_ROON) {
        console.error(`[DEBUG] process.argv: ${JSON.stringify(process.argv)}`);
        console.error(`[DEBUG] command: "${command}"`);
    }
    processCommand(core, command)
        .then(() => process.exit(0))
        .catch(e => {
            console.log(JSON.stringify({ error: e.message }));
            process.exit(1);
        });
}

// Callback: called when Roon unpairs us
function onCoreUnpaired(core) {
    console.log(JSON.stringify({ error: 'Roon Core disconnected' }));
    process.exit(1);
}

// The RoonApi constructor takes the callback handlers directly, so they're
// stored in this.extension_opts — which init_services checks for core_paired.
const roon = new RoonApi(Object.assign({}, appinfo, {
    core_paired: onCorePaired,
    core_unpaired: onCoreUnpaired,
}));

// Init services — browse is required for reading playlists
roon.init_services({
    required_services: [RoonApiBrowse],
});

// Connect: use direct ws_connect if --host/--port provided, otherwise discover
if (directHost && directPort) {
    roon.ws_connect({ host: directHost, port: directPort });
} else {
    roon.start_discovery();
    // Timeout if discovery doesn't find a core within 30 seconds
    setTimeout(function () {
        if (!currentCore) {
            console.log(JSON.stringify({
                error: 'No Roon Core found within 30 seconds. ' +
                       'Ensure Roon Core is running on the same network, ' +
                       'or use --host <ip> --port <port> to connect directly.',
            }));
            process.exit(1);
        }
    }, 30000);
}
