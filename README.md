# mcp-server-spotify

An MCP server for **surgical Spotify playlist editing**. Where Spotify's built-in
"generate a playlist from a vibe" tooling can't make precise edits, this exposes the
Spotify Web API's granular playlist operations directly — so an LLM can search for
tracks, then add, remove, and reorder them at exact positions.

The curation taste comes from the model; the precise placement comes from the API.

## Tools

| Tool | What it does |
|------|--------------|
| `find_playlists(name)` | Find your own playlists by name (substring) → `{name, uri, owner, tracks, public, owned}` |
| `search_tracks(query, limit)` | Find tracks → `{name, artist, album, year, uri}` |
| `create_playlist(name, description, public)` | Create an empty playlist → `{playlist_id, uri, url}` |
| `save_playlist(uri)` | Add a playlist to your library ("Save"/follow) → `{playlist_id, saved}` |
| `get_playlist(playlist_id)` | Read full tracklist **with positions** (handles >100 tracks) |
| `add_tracks(playlist_id, uris, position?)` | Append or insert at a position (auto-chunks to 100) |
| `remove_tracks(playlist_id, uris)` | Remove all occurrences of the given tracks |
| `reorder_tracks(playlist_id, range_start, insert_before, range_length?)` | Move a block of tracks |
| `shuffle_playlist(uri)` | Persist a randomized, artist-spread order (de-clusters same-artist runs) |

URIs, `open.spotify.com` URLs, and bare IDs are all accepted interchangeably.

## Setup

### 1. Create a Spotify app

At the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), create an
app and add this **exact** redirect URI (the loopback IP literal — Spotify rejects
`localhost`):

```
http://127.0.0.1:8888/callback
```

A free Spotify account works for playlist editing; the recommendation/audio-features
endpoints (deprecated by Spotify in Nov 2024) are intentionally **not** used here.

### 2. Configure credentials

```bash
cp .env.example .env
# edit .env with your client id/secret, then:
source .env
```

### 3. Install

```bash
uv sync          # or: pip install -e .
```

### 4. First-run authorization

The first call opens a browser for OAuth consent. The refresh token is cached to
`~/.spotify-mcp/token.json`, so it only happens once.

## Register with Claude

Add to your Claude Desktop / Claude Code MCP config:

```json
{
  "mcpServers": {
    "spotify": {
      "command": "uv",
      "args": ["--directory", "/Users/chris/devel/home/mcp-server-spotify", "run", "mcp-server-spotify"],
      "env": {
        "SPOTIPY_CLIENT_ID": "your_client_id",
        "SPOTIPY_CLIENT_SECRET": "your_client_secret",
        "SPOTIPY_REDIRECT_URI": "http://127.0.0.1:8888/callback"
      }
    }
  }
}
```

## Security posture

- **Minimal scopes:** `playlist-read-private`, `playlist-modify-private`,
  `playlist-modify-public`. No playback, no library, no profile access — that is the
  entire trust surface.
- **Two dependencies only** (`mcp`, `spotipy`); pin them via the committed `uv.lock`
  and review diffs on update rather than auto-bumping.
- Credentials live in a gitignored `.env` / Claude config; the token cache is gitignored.

## Development

```bash
uv sync                      # install deps (incl. dev group)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pytest                # unit tests (acceptance auto-skipped)
uv run pytest --run-acceptance   # + live API lifecycle (needs SPOTIPY_* creds)
```

CI (GitHub Actions) runs the PR-title check, ruff lint/format, and the unit tests
on every PR; the `CI Success` job is the aggregate gate. Acceptance tests are not
run in CI — they require live Spotify credentials and stay local/manual.

## License

MIT — see [LICENSE](LICENSE).
