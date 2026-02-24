"""
TMDB tool — movies, TV shows, ratings, recommendations.

Free API key from https://www.themoviedb.org/settings/api
Rate limits are generous (no hard limit documented, ~40 req/10s).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.themoviedb.org/3"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class TMDBTool:
    """Movies and TV shows: search, trending, recommendations, details from TMDB."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="tmdb",
            description=(
                "TMDB: movies and TV shows data. "
                "Actions: 'search' — find movies/shows by name; "
                "'trending' — what's trending today/this week; "
                "'movie' — detailed movie info by ID; "
                "'tv' — detailed TV show info by ID; "
                "'recommend' — get recommendations based on a movie/show; "
                "'discover' — discover by genre/year/rating. "
                "Use 'search' first to find the ID, then 'movie'/'tv' for details."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'search', 'trending', 'movie', 'tv', 'recommend', 'discover'",
                    required=True,
                    enum=["search", "trending", "movie", "tv", "recommend", "discover"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query for 'search' (e.g. 'Inception', 'Breaking Bad')",
                    required=False,
                ),
                ToolParameter(
                    name="movie_id",
                    type="string",
                    description="TMDB movie ID for 'movie'/'recommend' actions",
                    required=False,
                ),
                ToolParameter(
                    name="tv_id",
                    type="string",
                    description="TMDB TV show ID for 'tv'/'recommend' actions",
                    required=False,
                ),
                ToolParameter(
                    name="media_type",
                    type="string",
                    description="Media type for 'search'/'trending'/'discover': 'movie' or 'tv' (default 'movie')",
                    required=False,
                    enum=["movie", "tv"],
                ),
                ToolParameter(
                    name="genre",
                    type="string",
                    description="Genre for 'discover' (e.g. 'action', 'comedy', 'drama', 'thriller', 'sci-fi', 'horror')",
                    required=False,
                ),
                ToolParameter(
                    name="year",
                    type="string",
                    description="Year for 'discover' (e.g. '2024', '2023')",
                    required=False,
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Language for results: 'ru-RU' (default), 'en-US', 'uk-UA'",
                    required=False,
                ),
            ],
        )

    # Genre name -> TMDB genre ID mapping
    _MOVIE_GENRES = {
        "action": 28, "adventure": 12, "animation": 16, "comedy": 35,
        "crime": 80, "documentary": 99, "drama": 18, "family": 10751,
        "fantasy": 14, "history": 36, "horror": 27, "music": 10402,
        "mystery": 9648, "romance": 10749, "sci-fi": 878, "science fiction": 878,
        "thriller": 53, "war": 10752, "western": 37,
    }
    _TV_GENRES = {
        "action": 10759, "adventure": 10759, "animation": 16, "comedy": 35,
        "crime": 80, "documentary": 99, "drama": 18, "family": 10751,
        "kids": 10762, "mystery": 9648, "news": 10763, "reality": 10764,
        "sci-fi": 10765, "science fiction": 10765, "soap": 10766,
        "talk": 10767, "war": 10768, "western": 37,
    }

    async def _api_get(self, endpoint: str, params: dict | None = None) -> Any:
        if not params:
            params = {}
        params["api_key"] = self._api_key
        url = f"{BASE_URL}{endpoint}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=_TIMEOUT) as resp:
                if resp.status == 401:
                    raise ValueError("Invalid TMDB API key")
                if resp.status != 200:
                    raise ValueError(f"TMDB HTTP {resp.status}")
                return await resp.json()

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._api_key:
            return ToolResult(
                success=False,
                error="TMDB API key not configured. Get free key at https://www.themoviedb.org/settings/api and set TMDB_API_KEY in .env",
            )

        action = kwargs.get("action", "trending").strip().lower()
        try:
            if action == "search":
                return await self._search(kwargs)
            elif action == "trending":
                return await self._trending(kwargs)
            elif action == "movie":
                return await self._movie(kwargs)
            elif action == "tv":
                return await self._tv_show(kwargs)
            elif action == "recommend":
                return await self._recommend(kwargs)
            elif action == "discover":
                return await self._discover(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("TMDB error: %s", e)
            return ToolResult(success=False, error=f"TMDB error: {e}")

    async def _search(self, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Query required for search")

        media = kwargs.get("media_type", "movie").strip().lower()
        lang = kwargs.get("language", "ru-RU")
        endpoint = f"/search/{media}"

        data = await self._api_get(endpoint, {"query": query, "language": lang})
        results = data.get("results", [])

        if not results:
            return ToolResult(success=True, data=f"Nothing found for '{query}'")

        lines = [f"**{media.title()} search '{query}':**\n"]
        for r in results[:10]:
            title = r.get("title") or r.get("name", "?")
            year = (r.get("release_date") or r.get("first_air_date") or "?")[:4]
            rating = r.get("vote_average", 0)
            item_id = r.get("id", "?")
            overview = (r.get("overview") or "")[:100]

            star = "⭐" if rating >= 7 else "🎬"
            lines.append(
                f"{star} **{title}** ({year}) — {rating:.1f}/10 [ID: {item_id}]\n"
                f"   {overview}{'...' if overview else ''}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _trending(self, kwargs: dict) -> ToolResult:
        media = kwargs.get("media_type", "movie").strip().lower()
        lang = kwargs.get("language", "ru-RU")

        data = await self._api_get(f"/trending/{media}/week", {"language": lang})
        results = data.get("results", [])

        if not results:
            return ToolResult(success=True, data="No trending content")

        lines = [f"**Trending {media}s this week:**\n"]
        for i, r in enumerate(results[:15], 1):
            title = r.get("title") or r.get("name", "?")
            year = (r.get("release_date") or r.get("first_air_date") or "?")[:4]
            rating = r.get("vote_average", 0)
            item_id = r.get("id", "?")

            star = "⭐" if rating >= 7 else "🎬"
            lines.append(f"{i}. {star} **{title}** ({year}) — {rating:.1f}/10 [ID: {item_id}]")

        return ToolResult(success=True, data="\n".join(lines))

    async def _movie(self, kwargs: dict) -> ToolResult:
        movie_id = kwargs.get("movie_id", "").strip()
        if not movie_id:
            return ToolResult(success=False, error="movie_id required. Use 'search' first to find the ID.")

        lang = kwargs.get("language", "ru-RU")
        data = await self._api_get(
            f"/movie/{movie_id}",
            {"language": lang, "append_to_response": "credits"},
        )

        if not data or not data.get("title"):
            return ToolResult(success=False, error=f"Movie {movie_id} not found")

        title = data.get("title", "?")
        original = data.get("original_title", "")
        year = (data.get("release_date") or "?")[:4]
        rating = data.get("vote_average", 0)
        votes = data.get("vote_count", 0)
        runtime = data.get("runtime", 0)
        genres = ", ".join(g["name"] for g in data.get("genres", []))
        overview = data.get("overview", "")
        budget = data.get("budget", 0)
        revenue = data.get("revenue", 0)
        status = data.get("status", "?")
        tagline = data.get("tagline", "")

        # Cast
        credits = data.get("credits", {})
        cast = credits.get("cast", [])[:5]
        cast_str = ", ".join(f"{c['name']} ({c.get('character', '?')})" for c in cast)

        # Director
        crew = credits.get("crew", [])
        directors = [c["name"] for c in crew if c.get("job") == "Director"]

        result = f"**{title}**"
        if original and original != title:
            result += f" ({original})"
        result += f" — {year}\n"
        if tagline:
            result += f"_{tagline}_\n"
        result += (
            f"\n⭐ {rating:.1f}/10 ({votes:,} votes)\n"
            f"Runtime: {runtime} min | Genres: {genres}\n"
            f"Status: {status}\n"
        )
        if directors:
            result += f"Director: {', '.join(directors)}\n"
        if cast_str:
            result += f"Cast: {cast_str}\n"
        if budget:
            result += f"Budget: ${budget:,}\n"
        if revenue:
            result += f"Revenue: ${revenue:,}\n"
        if overview:
            result += f"\n{overview}"

        return ToolResult(success=True, data=result)

    async def _tv_show(self, kwargs: dict) -> ToolResult:
        tv_id = kwargs.get("tv_id", "").strip()
        if not tv_id:
            return ToolResult(success=False, error="tv_id required. Use 'search' first to find the ID.")

        lang = kwargs.get("language", "ru-RU")
        data = await self._api_get(
            f"/tv/{tv_id}",
            {"language": lang, "append_to_response": "credits"},
        )

        if not data or not data.get("name"):
            return ToolResult(success=False, error=f"TV show {tv_id} not found")

        name = data.get("name", "?")
        original = data.get("original_name", "")
        first_year = (data.get("first_air_date") or "?")[:4]
        last_year = (data.get("last_air_date") or "?")[:4]
        rating = data.get("vote_average", 0)
        votes = data.get("vote_count", 0)
        seasons = data.get("number_of_seasons", 0)
        episodes = data.get("number_of_episodes", 0)
        genres = ", ".join(g["name"] for g in data.get("genres", []))
        overview = data.get("overview", "")
        status = data.get("status", "?")
        tagline = data.get("tagline", "")

        credits = data.get("credits", {})
        cast = credits.get("cast", [])[:5]
        cast_str = ", ".join(f"{c['name']} ({c.get('character', '?')})" for c in cast)

        result = f"**{name}**"
        if original and original != name:
            result += f" ({original})"
        result += f" — {first_year}–{last_year}\n"
        if tagline:
            result += f"_{tagline}_\n"
        result += (
            f"\n⭐ {rating:.1f}/10 ({votes:,} votes)\n"
            f"Seasons: {seasons} | Episodes: {episodes}\n"
            f"Genres: {genres} | Status: {status}\n"
        )
        if cast_str:
            result += f"Cast: {cast_str}\n"
        if overview:
            result += f"\n{overview}"

        return ToolResult(success=True, data=result)

    async def _recommend(self, kwargs: dict) -> ToolResult:
        movie_id = kwargs.get("movie_id", "").strip()
        tv_id = kwargs.get("tv_id", "").strip()
        lang = kwargs.get("language", "ru-RU")

        if movie_id:
            media_type = "movie"
            item_id = movie_id
        elif tv_id:
            media_type = "tv"
            item_id = tv_id
        else:
            return ToolResult(success=False, error="movie_id or tv_id required for recommendations")

        data = await self._api_get(
            f"/{media_type}/{item_id}/recommendations",
            {"language": lang},
        )
        results = data.get("results", [])

        if not results:
            return ToolResult(success=True, data="No recommendations found")

        lines = [f"**Recommendations (based on {media_type} {item_id}):**\n"]
        for i, r in enumerate(results[:15], 1):
            title = r.get("title") or r.get("name", "?")
            year = (r.get("release_date") or r.get("first_air_date") or "?")[:4]
            rating = r.get("vote_average", 0)
            item_rid = r.get("id", "?")
            overview = (r.get("overview") or "")[:80]

            star = "⭐" if rating >= 7 else "🎬"
            lines.append(
                f"{i}. {star} **{title}** ({year}) — {rating:.1f}/10 [ID: {item_rid}]\n"
                f"   {overview}{'...' if overview else ''}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _discover(self, kwargs: dict) -> ToolResult:
        media = kwargs.get("media_type", "movie").strip().lower()
        lang = kwargs.get("language", "ru-RU")
        year = kwargs.get("year", "").strip()
        genre_name = kwargs.get("genre", "").strip().lower()

        params: dict[str, str] = {
            "language": lang,
            "sort_by": "vote_average.desc",
            "vote_count.gte": "100",
        }

        if year:
            if media == "movie":
                params["primary_release_year"] = year
            else:
                params["first_air_date_year"] = year

        if genre_name:
            genres = self._MOVIE_GENRES if media == "movie" else self._TV_GENRES
            genre_id = genres.get(genre_name)
            if genre_id:
                params["with_genres"] = str(genre_id)

        data = await self._api_get(f"/discover/{media}", params)
        results = data.get("results", [])

        if not results:
            return ToolResult(success=True, data="Nothing found with these filters")

        desc_parts = []
        if genre_name:
            desc_parts.append(genre_name)
        if year:
            desc_parts.append(year)
        desc = f" ({', '.join(desc_parts)})" if desc_parts else ""

        lines = [f"**Discover {media}s{desc} — top rated:**\n"]
        for i, r in enumerate(results[:15], 1):
            title = r.get("title") or r.get("name", "?")
            yr = (r.get("release_date") or r.get("first_air_date") or "?")[:4]
            rating = r.get("vote_average", 0)
            item_id = r.get("id", "?")

            star = "⭐" if rating >= 7 else "🎬"
            lines.append(f"{i}. {star} **{title}** ({yr}) — {rating:.1f}/10 [ID: {item_id}]")

        return ToolResult(success=True, data="\n".join(lines))
