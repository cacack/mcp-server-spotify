"""Acceptance tests against the live Spotify API.

Gated: skipped unless run with ``--run-acceptance`` and valid SPOTIPY_* credentials
(see conftest.py). These create a real, private, temporary playlist and delete it
afterwards, so they require a one-time OAuth consent on first run.

Run with:
    uv run pytest --run-acceptance
"""

from __future__ import annotations

import pytest

from mcp_server_spotify import auth, server

pytestmark = pytest.mark.acceptance


@pytest.fixture
def temp_playlist():
    """Create a private throwaway playlist and unfollow (delete) it on teardown."""
    pl = server.create_playlist(
        "[mcp-server-spotify] acceptance — safe to delete",
        description="Temporary playlist created by the acceptance test suite.",
        public=False,
    )
    try:
        yield pl
    finally:
        # "Deleting" a playlist on Spotify means the owner unfollows it.
        auth.get_client().current_user_unfollow_playlist(pl["playlist_id"])


@pytest.fixture(scope="session")
def two_track_uris():
    """Resolve two real track URIs via search (also exercises search_tracks)."""
    a = server.search_tracks("Nirvana Smells Like Teen Spirit", limit=1)
    b = server.search_tracks("Pearl Jam Alive", limit=1)
    assert a and b, "search returned no results — check credentials/connectivity"
    return [a[0]["uri"], b[0]["uri"]]


def test_full_playlist_lifecycle(temp_playlist, two_track_uris):
    pid = temp_playlist["playlist_id"]
    uri_a, uri_b = two_track_uris

    # add
    added = server.add_tracks(pid, [uri_a, uri_b])
    assert added["added"] == 2

    got = server.get_playlist(pid)
    assert got["total"] == 2
    assert [t["uri"] for t in got["tracks"]] == [uri_a, uri_b]
    assert [t["position"] for t in got["tracks"]] == [0, 1]

    # reorder: move the 2nd track (index 1) to the front
    server.reorder_tracks(pid, range_start=1, insert_before=0)
    reordered = server.get_playlist(pid)
    assert [t["uri"] for t in reordered["tracks"]] == [uri_b, uri_a]

    # remove one
    removed = server.remove_tracks(pid, [uri_b])
    assert removed["removed"] == 1
    final = server.get_playlist(pid)
    assert [t["uri"] for t in final["tracks"]] == [uri_a]


def test_find_playlists_locates_own_playlist_by_name(temp_playlist):
    # The whole point: a freshly created private playlist is findable by name via
    # the library endpoint (unlike the catalog search the connector uses).
    found = server.find_playlists("mcp-server-spotify] acceptance")
    by_uri = {p["uri"]: p for p in found}
    assert temp_playlist["uri"] in by_uri, "newly created playlist not found by name"
    match = by_uri[temp_playlist["uri"]]
    assert match["owned"] is True
    assert set(match) == {"name", "uri", "owner", "tracks", "public", "owned"}


def test_search_returns_compact_shape(two_track_uris):
    results = server.search_tracks("Soundgarden Black Hole Sun", limit=3)
    assert results, "expected at least one result"
    for r in results:
        assert set(r) == {"name", "artist", "album", "year", "uri"}
        assert r["uri"].startswith("spotify:track:")
