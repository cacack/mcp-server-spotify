"""Unit tests for normalize.py — pure logic, no I/O."""

from __future__ import annotations

import pytest

from mcp_server_spotify.normalize import (
    batched,
    compact_track,
    resolve_id,
    to_uri,
)


@pytest.mark.parametrize(
    "value,kind,expected",
    [
        ("spotify:track:abc123", "track", "abc123"),
        ("abc123", "track", "abc123"),
        ("https://open.spotify.com/track/abc123", "track", "abc123"),
        ("https://open.spotify.com/track/abc123?si=deadbeef", "track", "abc123"),
        ("spotify:playlist:xyz", "playlist", "xyz"),
        ("  abc123  ", "track", "abc123"),
    ],
)
def test_resolve_id(value, kind, expected):
    assert resolve_id(value, kind) == expected


def test_to_uri_roundtrips_all_forms():
    assert to_uri("abc", "track") == "spotify:track:abc"
    assert to_uri("spotify:track:abc", "track") == "spotify:track:abc"
    assert to_uri("https://open.spotify.com/track/abc?si=x", "track") == "spotify:track:abc"


def test_compact_track_raw_object():
    track = {
        "type": "track",
        "uri": "spotify:track:abc",
        "name": "Plowed",
        "artists": [{"name": "Sponge"}],
        "album": {"name": "Rotting Piñata", "release_date": "1994-08-30"},
    }
    assert compact_track(track) == {
        "name": "Plowed",
        "artist": "Sponge",
        "album": "Rotting Piñata",
        "year": "1994",
        "uri": "spotify:track:abc",
    }


def test_compact_track_unwraps_playlist_item():
    item = {
        "track": {
            "type": "track",
            "uri": "spotify:track:x",
            "name": "N",
            "artists": [{"name": "A"}],
            "album": {},
        }
    }
    out = compact_track(item)
    assert out["uri"] == "spotify:track:x"
    assert out["year"] is None  # missing release_date


def test_compact_track_joins_multiple_artists():
    track = {
        "type": "track",
        "uri": "u",
        "name": "N",
        "artists": [{"name": "A"}, {"name": "B"}],
        "album": {},
    }
    assert compact_track(track)["artist"] == "A, B"


@pytest.mark.parametrize("bad", [None, {}, {"type": "episode", "uri": "u"}])
def test_compact_track_skips_non_tracks(bad):
    assert compact_track(bad) is None


def test_batched_chunks_exactly():
    assert list(batched(range(5), 2)) == [[0, 1], [2, 3], [4]]


def test_batched_empty():
    assert list(batched([], 100)) == []


def test_batched_exact_multiple_has_no_trailing_empty():
    assert list(batched(range(4), 2)) == [[0, 1], [2, 3]]
