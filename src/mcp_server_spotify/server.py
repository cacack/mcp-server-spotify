"""FastMCP server exposing surgical Spotify playlist tools.

Nine tools: find_playlists, search_tracks, create_playlist, save_playlist,
get_playlist, add_tracks, remove_tracks, reorder_tracks, shuffle_playlist.
Together they let the model locate a playlist and resolve tracks to URIs, then
edit precisely — the curation taste comes from the model, the precise placement
comes from the Spotify Web API.
"""

from __future__ import annotations

import random

from mcp.server.fastmcp import FastMCP

from . import auth
from .normalize import (
    artist_spread_order,
    batched,
    compact_playlist,
    compact_track,
    resolve_id,
    to_uri,
)

mcp = FastMCP("spotify")

_TRACK_BATCH = 100  # Spotify caps add/remove at 100 items per request.


@mcp.tool()
def find_playlists(name: str = "") -> list[dict]:
    """Find the user's own playlists by name (case-insensitive substring match).

    Returns the user's library — owned and followed — as compact dicts:
    {name, uri, owner, tracks, public, owned}. An empty ``name`` returns all.

    Use this to resolve a playlist by title before get_playlist / editing, since
    the catalog search tool can't reliably find a user's own private playlists.
    """
    client = auth.get_client()
    me = client.current_user()["id"]
    needle = name.strip().lower()
    out: list[dict] = []
    offset = 0
    while True:
        page = client.current_user_playlists(limit=50, offset=offset)
        items = page.get("items", [])
        for pl in items:
            compact = compact_playlist(pl)
            if compact is None:
                continue
            if needle and needle not in (compact["name"] or "").lower():
                continue
            compact["owned"] = compact["owner"] == me
            out.append(compact)
        offset += len(items)
        if not page.get("next") or not items:
            break
    return out


@mcp.tool()
def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Search for tracks. Returns compact dicts: {name, artist, album, year, uri}.

    Use this to turn a request like "some upbeat Pearl Jam" into concrete track
    URIs that the edit tools can act on.
    """
    limit = max(1, min(limit, 50))
    results = auth.get_client().search(q=query, type="track", limit=limit)
    items = (results.get("tracks") or {}).get("items", [])
    return [t for t in (compact_track(i) for i in items) if t]


@mcp.tool()
def create_playlist(name: str, description: str = "", public: bool = False) -> dict:
    """Create a new, empty playlist owned by the authenticated user.

    Returns {playlist_id, uri, url}. Add tracks with add_tracks.
    """
    client = auth.get_client()
    pl = client.current_user_playlist_create(name, public=public, description=description)
    return {
        "playlist_id": pl["id"],
        "uri": pl["uri"],
        "url": (pl.get("external_urls") or {}).get("spotify"),
    }


@mcp.tool()
def save_playlist(uri: str) -> dict:
    """Add a playlist to the user's library — i.e. "Save"/follow it.

    Mainly for rescuing connector/AI-generated playlists, which are created in an
    unsaved state and don't appear in the library (or in find_playlists) until
    saved. Accepts a playlist URI, URL, or bare ID. Returns {playlist_id, saved}.
    """
    client = auth.get_client()
    pid = resolve_id(uri, "playlist")
    # spotipy's current_user_follow_playlist() currently routes through a
    # /me/library endpoint that returns repeated 500s; call the canonical
    # PUT /playlists/{id}/followers endpoint directly, which works. Follow
    # privately so saving doesn't expose the playlist on the user's profile.
    client._put(f"playlists/{pid}/followers", payload={"public": False})
    return {"playlist_id": pid, "saved": True}


@mcp.tool()
def get_playlist(playlist_id: str) -> dict:
    """Read a playlist's full tracklist WITH positions (handles >100 tracks).

    Returns {name, total, tracks: [{position, name, artist, album, year, uri}]}.
    Read this before editing so you know which index maps to which track.
    """
    client = auth.get_client()
    pid = resolve_id(playlist_id, "playlist")
    meta = client.playlist(pid, fields="name")
    tracks: list[dict] = []
    index = 0  # absolute playlist index, counts every item (matches reorder_tracks)
    while True:
        page = client.playlist_items(pid, offset=index, limit=100, additional_types=("track",))
        items = page.get("items", [])
        for item in items:
            compact = compact_track(item)
            if compact:
                # `position` is the true playlist index, so it can be passed
                # straight to reorder_tracks even when local files/podcasts are
                # interleaved (those are skipped from output but still counted).
                compact["position"] = index
                tracks.append(compact)
            index += 1
        if not page.get("next") or not items:
            break
    return {"name": meta.get("name"), "total": len(tracks), "tracks": tracks}


@mcp.tool()
def add_tracks(playlist_id: str, uris: list[str], position: int | None = None) -> dict:
    """Add tracks to a playlist, appending or inserting at ``position``.

    ``uris`` may be track URIs, URLs, or bare IDs. Auto-chunks to 100/request.
    Returns {snapshot_id, added}.
    """
    client = auth.get_client()
    pid = resolve_id(playlist_id, "playlist")
    track_uris = [to_uri(u, "track") for u in uris]
    snapshot_id = None
    pos = position
    for chunk in batched(track_uris, _TRACK_BATCH):
        resp = client.playlist_add_items(pid, chunk, position=pos)
        snapshot_id = resp.get("snapshot_id")
        if pos is not None:
            pos += len(chunk)  # keep insertion order across chunks
    return {"snapshot_id": snapshot_id, "added": len(track_uris)}


@mcp.tool()
def remove_tracks(playlist_id: str, uris: list[str]) -> dict:
    """Remove all occurrences of the given tracks from a playlist.

    ``uris`` may be track URIs, URLs, or bare IDs. Auto-chunks to 100/request.
    Returns {snapshot_id, removed}.
    """
    client = auth.get_client()
    pid = resolve_id(playlist_id, "playlist")
    track_uris = [to_uri(u, "track") for u in uris]
    snapshot_id = None
    for chunk in batched(track_uris, _TRACK_BATCH):
        resp = client.playlist_remove_all_occurrences_of_items(pid, chunk)
        snapshot_id = resp.get("snapshot_id")
    return {"snapshot_id": snapshot_id, "removed": len(track_uris)}


@mcp.tool()
def reorder_tracks(
    playlist_id: str, range_start: int, insert_before: int, range_length: int = 1
) -> dict:
    """Move a block of ``range_length`` tracks starting at ``range_start`` so it
    lands before index ``insert_before``. Returns {snapshot_id}.

    Example: move the track at index 7 to the top -> range_start=7, insert_before=0.
    """
    client = auth.get_client()
    pid = resolve_id(playlist_id, "playlist")
    resp = client.playlist_reorder_items(pid, range_start, insert_before, range_length=range_length)
    return {"snapshot_id": resp.get("snapshot_id")}


@mcp.tool()
def shuffle_playlist(uri: str) -> dict:
    """Reorder a playlist into a randomized, artist-spread order and persist it.

    Spreads each artist's tracks across the playlist so the same artist rarely
    lands back-to-back (a balanced shuffle, not pure random) — useful for
    un-grouping a playlist that was built artist-by-artist. Persists the new order
    in a single bulk replace. Note: only standard tracks are preserved; local
    files and podcast episodes are dropped. Returns {playlist_id, tracks}.
    """
    client = auth.get_client()
    pid = resolve_id(uri, "playlist")
    tracks = get_playlist(pid)["tracks"]
    if not tracks:
        return {"playlist_id": pid, "tracks": 0}
    ordered = artist_spread_order(tracks, random.Random())
    uris = [t["uri"] for t in ordered]
    # Replace the whole list in one call (<=100), then append any overflow in order.
    client.playlist_replace_items(pid, uris[:_TRACK_BATCH])
    for chunk in batched(uris[_TRACK_BATCH:], _TRACK_BATCH):
        client.playlist_add_items(pid, chunk)
    return {"playlist_id": pid, "tracks": len(uris)}


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
