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
        return value[len(prefix):]
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
