"""Spotify OAuth setup.

Uses spotipy's Authorization Code flow. Credentials come from the environment
(``SPOTIPY_CLIENT_ID`` / ``SPOTIPY_CLIENT_SECRET`` / ``SPOTIPY_REDIRECT_URI``),
which spotipy reads automatically. The refresh token is cached to
``~/.spotify-mcp/token.json`` so the browser auth only happens once.

Scopes are deliberately minimal: playlist read + modify only. No playback,
no library, no profile data — that is the entire trust surface of this server.
"""

from __future__ import annotations

import os
from pathlib import Path

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

SCOPES = "playlist-read-private playlist-modify-private playlist-modify-public"

_CACHE_DIR = Path.home() / ".spotify-mcp"
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

_client: spotipy.Spotify | None = None


def get_client() -> spotipy.Spotify:
    """Return a cached, authenticated Spotify client (creates it on first call)."""
    global _client
    if _client is None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        auth = SpotifyOAuth(
            scope=SCOPES,
            redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", _DEFAULT_REDIRECT_URI),
            cache_handler=CacheFileHandler(cache_path=str(_CACHE_DIR / "token.json")),
            open_browser=True,
        )
        _client = spotipy.Spotify(auth_manager=auth)
    return _client


def current_user_id() -> str:
    """Return the authenticated user's Spotify ID."""
    return get_client().current_user()["id"]
