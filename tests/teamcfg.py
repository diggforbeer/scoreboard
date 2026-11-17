"""Settings objects with a favourite, for tests (epic #470).

The screens read ``favourite_team``, ``followed_teams`` and ``horn_team`` through a
``priority.TeamView`` over their sport's settings; these build one directly, so a test about a
screen can say "NYG is the favourite, WSH is followed" without a ranked list.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from scoreboard.config import FootballConfig, RotationEntry, ScoreboardConfig, Settings, TeamEntry
from scoreboard.priority import TeamView


def _clean(favourite: str | None, follow: Sequence[Any] | str | None) -> tuple[str, list[str]]:
    fav = (favourite or "").strip().upper()
    raw = [follow] if isinstance(follow, str) else list(follow or [])
    out: list[str] = []
    for item in raw:
        team = str(item).strip().upper()
        if team and team != fav and team not in out:
            out.append(team)
    return fav, out


def fcfg(
    favourite_team: str | None = "",
    also_follow: Sequence[Any] | str | None = (),
    horn_team: str | None = None,
    rotation: Sequence[Any] | None = None,
    **settings: Any,
) -> TeamView:
    """Football's settings (``FootballConfig(**settings)``) with a favourite, followed teams, a
    horn team (the favourite unless given) and idle rotation rows (``{"screen", "seconds"}`` dicts
    or ``RotationEntry``; football's default unless given)."""
    fav, follow = _clean(favourite_team, also_follow)
    rows = None
    if rotation:  # an empty list means the default, as it always has
        rows = [
            e if isinstance(e, RotationEntry) else RotationEntry(e["screen"], float(e["seconds"]))
            for e in rotation
        ]
    horn = fav if horn_team is None else horn_team
    return TeamView(FootballConfig(**settings), fav, follow, horn, rows)


def hcfg(
    favourite_team: str | None = "",
    also_follow: Sequence[Any] | str | None = (),
    horn_team: str | None = None,
    **settings: Any,
) -> TeamView:
    """Hockey's settings (``ScoreboardConfig(**settings)``) seen the same way."""
    fav, follow = _clean(favourite_team, also_follow)
    return TeamView(
        ScoreboardConfig(**settings), fav, follow, fav if horn_team is None else horn_team
    )


def teams_for(
    favourite: str | None, follow: Sequence[str] = (), sport: str = "hockey"
) -> list[TeamEntry]:
    """The ranked list that makes ``favourite`` rank 1 of ``sport`` and ``follow`` the next ones."""
    fav, rest = _clean(favourite, follow)
    return [TeamEntry(sport, t) for t in ([fav] if fav else []) + rest]


def with_favourite(
    settings: Settings, favourite: str | None, follow: Sequence[str] = ()
) -> Settings:
    """``settings`` with a hockey favourite and followed teams as a ranked list."""
    settings.teams = teams_for(favourite, follow)
    return settings


def set_favourite(settings: Settings, favourite: str | None) -> None:
    """Make ``favourite`` rank 1 of the hockey teams (``""`` or ``None`` for none), keeping the
    other ranked hockey teams as they are."""
    fav, _ = _clean(favourite, ())
    rest = [
        t
        for t in settings.teams_for("hockey")[1 if settings.teams_for("hockey") else 0 :]
        if t != fav
    ]
    # the old favourite stays followed unless it is being replaced by nobody
    settings.teams = [e for e in settings.teams if e.sport != "hockey"] + teams_for(fav, rest)


def set_follow(settings: Settings, follow: Sequence[str]) -> None:
    """Rank ``follow`` right after the current hockey favourite (the first hockey team)."""
    current = settings.teams_for("hockey")
    fav = current[0] if current else ""
    settings.teams = [e for e in settings.teams if e.sport != "hockey"] + teams_for(fav, follow)


def apply_team_kwargs(settings: Settings, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Pop ``favourite_team`` / ``also_follow`` out of ``kwargs`` (the old way of saying it) into
    the ranked list, and return what is left for the scoreboard settings."""
    rest = dict(kwargs)
    has = "favourite_team" in rest or "also_follow" in rest
    fav = rest.pop("favourite_team", None)
    follow = rest.pop("also_follow", ())
    if has:
        settings.teams = [e for e in settings.teams if e.sport != "hockey"] + teams_for(fav, follow)
    return rest
