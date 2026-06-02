"""URI/ID coercion and compact projections.

The LLM will hand us a mix of bare IDs, ``spotify:track:...`` URIs, and open.spotify.com
URLs. Normalize everything on the way in, and project Spotify's large API objects down
to small dicts on the way out so we don't blow up the model's context.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator


def resolve_id(value: str, kind: str) -> str:
    """Return the bare Spotify ID for ``value``, accepting an ID, URI, or URL.

    ``kind`` is the entity type, e.g. "track" or "playlist".
    """
    value = value.strip()
    prefix = f"spotify:{kind}:"
    if value.startswith(prefix):
        return value[len(prefix) :]
    if "open.spotify.com" in value:
        # https://open.spotify.com/<kind>/<id>?si=...
        tail = value.split(f"/{kind}/", 1)[-1]
        return tail.split("?", 1)[0].split("/", 1)[0]
    return value


def to_uri(value: str, kind: str) -> str:
    """Return a canonical ``spotify:<kind>:<id>`` URI for ``value``."""
    return f"spotify:{kind}:{resolve_id(value, kind)}"


def compact_track(track: dict | None) -> dict | None:
    """Project a Spotify track object down to ``{name, artist, album, year, uri}``.

    Accepts either a raw track object or a playlist-item wrapper (``{"track": {...}}``).
    Returns ``None`` for unavailable/removed items (local files, podcasts, deleted tracks).
    """
    if track is None:
        return None
    if "track" in track and "uri" not in track:  # playlist-item wrapper
        track = track["track"]
    if not track or track.get("type") != "track":
        return None
    album = track.get("album") or {}
    return {
        "name": track.get("name"),
        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
        "album": album.get("name"),
        "year": (album.get("release_date") or "")[:4] or None,
        "uri": track.get("uri"),
    }


def compact_playlist(pl: dict | None) -> dict | None:
    """Project a Spotify playlist object down to ``{name, uri, owner, tracks, public}``.

    ``owner`` is the owner's user id. Returns ``None`` for empty/unavailable entries
    (the playlists endpoint can include null items).
    """
    if not pl:
        return None
    owner = (pl.get("owner") or {}).get("id")
    tracks = (pl.get("tracks") or {}).get("total")
    return {
        "name": pl.get("name"),
        "uri": pl.get("uri"),
        "owner": owner,
        "tracks": tracks,
        "public": pl.get("public"),
    }


def artist_spread_order(tracks: list[dict], rng) -> list[dict]:
    """Reorder tracks into a randomized, artist-spread order (a balanced shuffle).

    Each artist's tracks are placed at evenly-spaced positions with a random phase,
    so the same artist rarely lands back-to-back — unlike a pure shuffle, which can
    cluster. ``tracks`` items must have an ``artist`` key; ``rng`` is a
    ``random.Random``. Returns a new list containing exactly the same items.
    """
    groups: dict = {}
    for t in tracks:
        groups.setdefault(t.get("artist"), []).append(t)

    positioned: list[tuple[float, float, dict]] = []
    for items in groups.values():
        rng.shuffle(items)
        count = len(items)
        offset = rng.random()
        for i, track in enumerate(items):
            # Evenly space this artist's tracks across [0, 1) with a random phase;
            # the tiebreak keeps ordering stable-but-random on exact collisions.
            positioned.append(((i + offset) / count, rng.random(), track))

    positioned.sort(key=lambda x: (x[0], x[1]))
    return [track for _, _, track in positioned]


def batched(items: Iterable, size: int) -> Iterator[list]:
    """Yield successive lists of at most ``size`` items (Spotify caps most calls at 100)."""
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
