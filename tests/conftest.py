"""Shared pytest fixtures and acceptance-test gating.

Unit tests run everywhere and never touch the network — they monkeypatch
``auth.get_client`` with the in-memory :class:`FakeSpotify` below.

Acceptance tests hit the live Spotify API and are skipped unless you opt in with
``--run-acceptance`` *and* the required credentials are present in the environment.
"""

from __future__ import annotations

import os

import pytest


# --------------------------------------------------------------------------- #
# Acceptance-test gating
# --------------------------------------------------------------------------- #
def pytest_addoption(parser):
    parser.addoption(
        "--run-acceptance",
        action="store_true",
        default=False,
        help="run acceptance tests against the live Spotify API",
    )


_REQUIRED_ACCEPTANCE_ENV = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-acceptance"):
        missing = [v for v in _REQUIRED_ACCEPTANCE_ENV if not os.environ.get(v)]
        if missing:
            skip = pytest.mark.skip(reason=f"acceptance env not set: {', '.join(missing)}")
            for item in items:
                if "acceptance" in item.keywords:
                    item.add_marker(skip)
        return
    skip = pytest.mark.skip(reason="need --run-acceptance to run live Spotify tests")
    for item in items:
        if "acceptance" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- #
# Fake Spotify client for unit tests
# --------------------------------------------------------------------------- #
def _track(uri: str, name: str = "Song", artist: str = "Artist") -> dict:
    """Build a minimal track object shaped like Spotify's API response."""
    return {
        "type": "track",
        "uri": uri,
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": "Album", "release_date": "1995-01-01"},
    }


class FakeSpotify:
    """In-memory stand-in for ``spotipy.Spotify`` that records calls.

    Implements only the methods the server uses, with canned responses and a
    ``calls`` log so tests can assert chunking, positions, and id resolution.
    """

    def __init__(self, *, search_items=None, playlist_pages=None, playlist_list_pages=None):
        self.calls: list[tuple] = []
        self._search_items = (
            search_items
            if search_items is not None
            else [_track("spotify:track:aaa", "Plowed", "Sponge")]
        )
        # playlist_pages: list of (items, has_next) tuples returned by playlist_items.
        self._playlist_pages = playlist_pages or []
        self._page_idx = 0
        # playlist_list_pages: list of (items, has_next) tuples for current_user_playlists.
        self._playlist_list_pages = playlist_list_pages or []
        self._list_idx = 0

    # -- reads --
    def current_user(self):
        self.calls.append(("current_user",))
        return {"id": "test-user"}

    def current_user_playlists(self, limit=50, offset=0):
        self.calls.append(("current_user_playlists", limit, offset))
        if self._list_idx >= len(self._playlist_list_pages):
            return {"items": [], "next": None}
        items, has_next = self._playlist_list_pages[self._list_idx]
        self._list_idx += 1
        return {"items": items, "next": "url" if has_next else None}

    def search(self, q, type="track", limit=10):
        self.calls.append(("search", q, type, limit))
        return {"tracks": {"items": self._search_items[:limit]}}

    def playlist(self, pid, fields=None):
        self.calls.append(("playlist", pid, fields))
        return {"name": "My Playlist"}

    def playlist_items(self, pid, offset=0, limit=100, additional_types=("track",)):
        self.calls.append(("playlist_items", pid, offset, limit))
        if self._page_idx >= len(self._playlist_pages):
            return {"items": [], "next": None}
        items, has_next = self._playlist_pages[self._page_idx]
        self._page_idx += 1
        return {"items": items, "next": "url" if has_next else None}

    # -- writes --
    def current_user_playlist_create(self, name, public=False, collaborative=False, description=""):
        self.calls.append(("current_user_playlist_create", name, public, description))
        return {
            "id": "newpl",
            "uri": "spotify:playlist:newpl",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/newpl"},
        }

    def playlist_add_items(self, pid, uris, position=None):
        self.calls.append(("playlist_add_items", pid, list(uris), position))
        return {"snapshot_id": f"snap-add-{len(self.calls)}"}

    def playlist_remove_all_occurrences_of_items(self, pid, uris):
        self.calls.append(("playlist_remove", pid, list(uris)))
        return {"snapshot_id": f"snap-rm-{len(self.calls)}"}

    def playlist_reorder_items(self, pid, range_start, insert_before, range_length=1):
        self.calls.append(("playlist_reorder", pid, range_start, insert_before, range_length))
        return {"snapshot_id": "snap-reorder"}

    def playlist_replace_items(self, pid, uris):
        self.calls.append(("playlist_replace", pid, list(uris)))
        return {"snapshot_id": "snap-replace"}

    def _put(self, url, payload=None):
        # save_playlist calls the canonical followers endpoint via spotipy's _put.
        self.calls.append(("_put", url, payload))
        return None


@pytest.fixture
def fake_spotify(monkeypatch):
    """Patch ``auth.get_client`` to return a fresh :class:`FakeSpotify`.

    Returns a factory so tests can pass canned search results / playlist pages.
    """
    from mcp_server_spotify import auth

    created: dict = {}

    def _install(**kwargs):
        client = FakeSpotify(**kwargs)
        created["client"] = client
        monkeypatch.setattr(auth, "get_client", lambda: client)
        return client

    return _install
