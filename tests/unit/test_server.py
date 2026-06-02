"""Unit tests for the server tools, exercised against the FakeSpotify client.

These assert the behavior that's easy to get wrong: 100-item chunking, the
insertion-position math across chunks, URI normalization of inputs, and
absolute-index handling in get_playlist when non-track items are interleaved.
"""

from __future__ import annotations

import pytest

from mcp_server_spotify import server


def _wrap_y(uri, name, artist, year):
    """A playlist-item wrapper carrying an album release year (for sort tests)."""
    return {
        "track": {
            "type": "track",
            "uri": uri,
            "name": name,
            "artists": [{"name": artist}],
            "album": {"name": "Al", "release_date": f"{year}-06-01"},
        }
    }


def _wrap(uri, name="N", artist="A"):
    """A playlist-item wrapper as returned by playlist_items."""
    return {
        "track": {
            "type": "track",
            "uri": uri,
            "name": name,
            "artists": [{"name": artist}],
            "album": {},
        }
    }


def _pl(name, owner="test-user", pid=None, total=0, public=False):
    """A playlist object as returned by current_user_playlists."""
    pid = pid or name
    return {
        "name": name,
        "uri": f"spotify:playlist:{pid}",
        "id": pid,
        "owner": {"id": owner},
        "tracks": {"total": total},
        "public": public,
    }


def test_find_playlists_filters_by_name_case_insensitive(fake_spotify):
    fake_spotify(
        playlist_list_pages=[
            (
                [
                    _pl("Blitz from the 90s", total=60),
                    _pl("Chill Vibes", total=12),
                    _pl("90s Hip Hop", total=30),
                ],
                False,
            )
        ]
    )
    out = server.find_playlists("blitz")
    assert [p["name"] for p in out] == ["Blitz from the 90s"]
    assert out[0]["uri"] == "spotify:playlist:Blitz from the 90s"
    assert out[0]["tracks"] == 60


def test_find_playlists_empty_returns_all(fake_spotify):
    fake_spotify(playlist_list_pages=[([_pl("A"), _pl("B")], False)])
    out = server.find_playlists()
    assert {p["name"] for p in out} == {"A", "B"}


def test_find_playlists_paginates(fake_spotify):
    client = fake_spotify(
        playlist_list_pages=[
            ([_pl("One")], True),
            ([_pl("Two")], False),
        ]
    )
    out = server.find_playlists()
    assert [p["name"] for p in out] == ["One", "Two"]
    list_calls = [c for c in client.calls if c[0] == "current_user_playlists"]
    assert [c[2] for c in list_calls] == [0, 1]  # offset advances by page size


def test_find_playlists_sets_owned_flag(fake_spotify):
    fake_spotify(
        playlist_list_pages=[
            ([_pl("Mine", owner="test-user"), _pl("Theirs", owner="someone-else")], False)
        ]
    )
    out = {p["name"]: p for p in server.find_playlists()}
    assert out["Mine"]["owned"] is True
    assert out["Theirs"]["owned"] is False


def test_shuffle_playlist_replaces_with_permutation(fake_spotify):
    items = [
        _wrap("spotify:track:a", "S1", "Sponge"),
        _wrap("spotify:track:b", "S2", "Sponge"),
        _wrap("spotify:track:c", "P1", "Pearl Jam"),
        _wrap("spotify:track:d", "N1", "Nirvana"),
    ]
    client = fake_spotify(playlist_pages=[(items, False)])
    out = server.shuffle_playlist("spotify:playlist:p")
    assert out == {"playlist_id": "p", "tracks": 4, "method": "artist_spread"}
    replace = next(c for c in client.calls if c[0] == "playlist_replace")
    assert replace[1] == "p"
    # same set of URIs, just reordered
    assert sorted(replace[2]) == [
        "spotify:track:a",
        "spotify:track:b",
        "spotify:track:c",
        "spotify:track:d",
    ]


def test_shuffle_playlist_empty_is_noop(fake_spotify):
    client = fake_spotify(playlist_pages=[([], False)])
    out = server.shuffle_playlist("p")
    assert out == {"playlist_id": "p", "tracks": 0, "method": "artist_spread"}
    assert not any(c[0] == "playlist_replace" for c in client.calls)


def test_dedupe_playlist_removes_exact_duplicates(fake_spotify):
    items = [
        _wrap("spotify:track:a"),
        _wrap("spotify:track:b"),
        _wrap("spotify:track:a"),
        _wrap("spotify:track:c"),
        _wrap("spotify:track:b"),
        _wrap("spotify:track:a"),
    ]
    client = fake_spotify(playlist_pages=[(items, False)])
    out = server.dedupe_playlist("spotify:playlist:p")
    assert out == {"playlist_id": "p", "removed": 3}
    # Rebuilt via replace with the first-occurrence-deduped list, order preserved.
    replace = next(c for c in client.calls if c[0] == "playlist_replace")
    assert replace[2] == ["spotify:track:a", "spotify:track:b", "spotify:track:c"]


def test_dedupe_playlist_no_duplicates_is_noop(fake_spotify):
    client = fake_spotify(
        playlist_pages=[([_wrap("spotify:track:a"), _wrap("spotify:track:b")], False)]
    )
    out = server.dedupe_playlist("p")
    assert out == {"playlist_id": "p", "removed": 0}
    assert not any(c[0] == "playlist_replace" for c in client.calls)


def test_add_tracks_skip_existing_filters_present_and_input_dups(fake_spotify):
    client = fake_spotify(
        playlist_pages=[([_wrap("spotify:track:a"), _wrap("spotify:track:b")], False)]
    )
    out = server.add_tracks(
        "spotify:playlist:p",
        [
            "spotify:track:a",
            "spotify:track:c",
            "spotify:track:b",
            "spotify:track:c",
            "spotify:track:d",
        ],
        skip_existing=True,
    )
    assert out["added"] == 2
    assert out["skipped"] == 3  # a,b already present; the second c is an input dup
    add_call = next(c for c in client.calls if c[0] == "playlist_add_items")
    assert add_call[2] == ["spotify:track:c", "spotify:track:d"]


def test_shuffle_playlist_random_is_permutation(fake_spotify):
    items = [_wrap(f"spotify:track:{x}") for x in "abcd"]
    client = fake_spotify(playlist_pages=[(items, False)])
    out = server.shuffle_playlist("p", method="random")
    assert out["method"] == "random"
    replace = next(c for c in client.calls if c[0] == "playlist_replace")
    assert sorted(replace[2]) == [f"spotify:track:{x}" for x in "abcd"]


def test_shuffle_playlist_unknown_method_raises(fake_spotify):
    fake_spotify(playlist_pages=[([_wrap("spotify:track:a")], False)])
    with pytest.raises(ValueError):
        server.shuffle_playlist("p", method="bogus")


def test_sort_playlist_by_year_ascending(fake_spotify):
    items = [
        _wrap_y("spotify:track:c", "C", "Z", 1999),
        _wrap_y("spotify:track:a", "A", "X", 1992),
        _wrap_y("spotify:track:b", "B", "Y", 1995),
    ]
    client = fake_spotify(playlist_pages=[(items, False)])
    out = server.sort_playlist("p", by="year", order="asc")
    assert out["by"] == "year" and out["order"] == "asc"
    replace = next(c for c in client.calls if c[0] == "playlist_replace")
    assert replace[2] == ["spotify:track:a", "spotify:track:b", "spotify:track:c"]


def test_sort_playlist_descending_reverses(fake_spotify):
    items = [
        _wrap_y("spotify:track:a", "A", "X", 1992),
        _wrap_y("spotify:track:b", "B", "Y", 1999),
    ]
    client = fake_spotify(playlist_pages=[(items, False)])
    server.sort_playlist("p", by="year", order="desc")
    replace = next(c for c in client.calls if c[0] == "playlist_replace")
    assert replace[2] == ["spotify:track:b", "spotify:track:a"]


def test_sort_playlist_by_artist(fake_spotify):
    items = [
        _wrap_y("spotify:track:a", "A", "Beck", 1994),
        _wrap_y("spotify:track:b", "B", "Adele", 1994),
    ]
    client = fake_spotify(playlist_pages=[(items, False)])
    server.sort_playlist("p", by="artist", order="asc")
    replace = next(c for c in client.calls if c[0] == "playlist_replace")
    assert replace[2] == ["spotify:track:b", "spotify:track:a"]  # Adele < Beck


def test_sort_playlist_unknown_key_raises(fake_spotify):
    fake_spotify()
    with pytest.raises(ValueError):
        server.sort_playlist("p", by="bogus")


def test_save_playlist_follows_and_resolves_id(fake_spotify):
    client = fake_spotify()
    out = server.save_playlist("https://open.spotify.com/playlist/xyz?si=abc")
    assert out == {"playlist_id": "xyz", "saved": True}
    assert ("_put", "playlists/xyz/followers", {"public": False}) in client.calls


def test_search_tracks_returns_compact_and_clamps_limit(fake_spotify):
    client = fake_spotify(
        search_items=[
            {
                "type": "track",
                "uri": "spotify:track:a",
                "name": "Plowed",
                "artists": [{"name": "Sponge"}],
                "album": {"name": "X", "release_date": "1994"},
            },
        ]
    )
    out = server.search_tracks("sponge plowed", limit=999)
    assert out == [
        {
            "name": "Plowed",
            "artist": "Sponge",
            "album": "X",
            "year": "1994",
            "uri": "spotify:track:a",
        }
    ]
    # limit is clamped to Spotify's max of 50
    assert client.calls[0] == ("search", "sponge plowed", "track", 50)


def test_create_playlist_returns_ids(fake_spotify):
    client = fake_spotify()
    out = server.create_playlist("Blitz from the 90s", "grunge", public=True)
    assert out == {
        "playlist_id": "newpl",
        "uri": "spotify:playlist:newpl",
        "url": "https://open.spotify.com/playlist/newpl",
    }
    assert ("current_user_playlist_create", "Blitz from the 90s", True, "grunge") in client.calls


def test_add_tracks_chunks_and_advances_position(fake_spotify):
    client = fake_spotify()
    uris = [f"spotify:track:{i}" for i in range(250)]
    out = server.add_tracks("spotify:playlist:p", uris, position=5)
    assert out["added"] == 250

    add_calls = [c for c in client.calls if c[0] == "playlist_add_items"]
    sizes = [len(c[2]) for c in add_calls]
    positions = [c[3] for c in add_calls]
    assert sizes == [100, 100, 50]
    assert positions == [5, 105, 205]  # position advances by chunk size
    # playlist id resolved from the URI
    assert all(c[1] == "p" for c in add_calls)


def test_add_tracks_position_none_stays_none(fake_spotify):
    client = fake_spotify()
    server.add_tracks("p", [f"spotify:track:{i}" for i in range(150)])
    positions = [c[3] for c in client.calls if c[0] == "playlist_add_items"]
    assert positions == [None, None]


def test_add_tracks_normalizes_mixed_input_forms(fake_spotify):
    client = fake_spotify()
    server.add_tracks(
        "p",
        [
            "spotify:track:a",
            "https://open.spotify.com/track/b?si=zzz",
            "c",
        ],
    )
    add_call = next(c for c in client.calls if c[0] == "playlist_add_items")
    assert add_call[2] == ["spotify:track:a", "spotify:track:b", "spotify:track:c"]


def test_remove_tracks_chunks(fake_spotify):
    client = fake_spotify()
    out = server.remove_tracks("p", [f"spotify:track:{i}" for i in range(120)])
    assert out["removed"] == 120
    rm_calls = [c for c in client.calls if c[0] == "playlist_remove"]
    assert [len(c[2]) for c in rm_calls] == [100, 20]


def test_reorder_tracks_passes_through(fake_spotify):
    client = fake_spotify()
    out = server.reorder_tracks("spotify:playlist:p", range_start=7, insert_before=0)
    assert out == {"snapshot_id": "snap-reorder"}
    assert ("playlist_reorder", "p", 7, 0, 1) in client.calls


def test_get_playlist_paginates_and_uses_absolute_index(fake_spotify):
    # Page 1: track, episode (skipped), track ; Page 2: track
    episode = {"track": {"type": "episode", "uri": "spotify:episode:e"}}
    page1 = ([_wrap("spotify:track:a"), episode, _wrap("spotify:track:b")], True)
    page2 = ([_wrap("spotify:track:c")], False)
    fake_spotify(playlist_pages=[page1, page2])

    out = server.get_playlist("spotify:playlist:p")
    assert out["name"] == "My Playlist"
    assert out["total"] == 3
    # Episode at absolute index 1 is skipped from output, but downstream indices
    # remain the TRUE playlist positions so reorder_tracks stays correct.
    assert [(t["uri"], t["position"]) for t in out["tracks"]] == [
        ("spotify:track:a", 0),
        ("spotify:track:b", 2),
        ("spotify:track:c", 3),
    ]
