# Screens

Every distinct thing this project can show, in two groups: the LED panel
(128x32, two chained 64x32 panels) and the two web pages served from the
device. Panel scenes are the `Scene.kind` values in `app.py`; see
`_favourite_scene`/`_select_base_scene`/`select_scene()` there for exactly
when each one is chosen, and `ScoreboardApp.draw_scene()` for the dispatch
to each renderer method below.

## LED panel scenes

| Scene (`kind`) | Renderer method | When it shows |
|---|---|---|
| **Game** | `draw_game` | The default view: live score, final score (held for `final_hold_minutes`), or pregame matchup. Logos on each side if `show_logos`/logos are available, text abbreviations otherwise (`logo_*` vs `text_*` snapshots). The status band below the score shows period/clock, intermission, PP/EN strength, or falls back to shots-on-goal when nothing special is on. |
| **Goal** | `draw_goal` | "GOAL" in big amber type over the current score, for `goal_flash_seconds`. Fires only for the favourite's own goal, in a game they're playing -- never for any other team or game. |
| **Goal detail** | `draw_goal_detail` | Follows the plain Goal flash: scorer's name, season goal total, and assist(s) (or "UNASSISTED"), for `goal_detail_seconds`. Same favourite-only scoping as Goal. |
| **Three stars** | `draw_three_stars` | Once, when the favourite's game (one we watched go live) goes final and `landing` has named its three stars: "3 STARS" over one line per star -- rank, name in that player's team colour, one per-game stat (`2G`/`1A`/`3P`) -- for `three_stars_seconds`, then the normal held final. Same favourite-only scoping as Goal. |
| **Countdown** | `draw_countdown` | The favourite's next game, inside `countdown_hours` of puck drop -- day/date give way to a countdown once close enough. |
| **Preview** | `draw_preview` | The favourite's next game, further out than `countdown_hours` -- day label and start time, no countdown yet. |
| **Standings** | `draw_standings` | The favourite's conference playoff picture: favourite +/- a couple of spots by `conferenceSequence`, one screen, no pagination. Only in `rotation = "favourite"`, alternates with Countdown/Preview on `rotate_seconds`, suppressed until the favourite's season has actually started. |
| **Leaders** | `draw_leaders` | Opt-in `[[rotation]]` screen (`leaders`, #201): the favourite's logo on the left, then a title and one row each for the top goal scorer, top point getter and the two goalies with the most games played (record and save %), from `club-stats/{TEAM}/now`. Ties (including everyone at zero early in the season) are broken at random once per hourly fetch; it is skipped only while the API returns no players at all. |
| **Clock** | `draw_clock` | Plain idle clock. Shown when there's nothing else to display and `show_clock_when_idle` is on, or interleaved between the favourite's games when `show_clock_between_games` is on. |
| **No games** | `draw_message` ("NO GAMES") | Fallback when there's genuinely nothing to show and the idle clock is off. |
| **Connecting** | `draw_message` ("NHL" / "CONNECTING") | Shown at startup before the first successful score fetch. |
| **No data** | `draw_message` ("NO DATA" / "CHECK NETWORK") | Shown when the last successful poll is stale past the 15-minute staleness guard. |
| **AP setup** | `draw_ap_setup` | First-boot WiFi setup: SSID/password as text on the left half, a join QR code on the right half. Shown whenever the board has no network and is broadcasting its own setup AP (`nhl-scoreboard-setup-ap`). Takes priority over every scene above except WiFi join. |
| **WiFi join** | `draw_wifi_join` | "JOINING...", "CONNECTED!", or "COULD NOT CONNECT" while/after a network submitted through the WiFi setup page is being tried. Top priority of every scene -- wins even over AP setup, since a failed join brings the AP scene's own state file back underneath it. |

Two rendering variants apply across most of the above rather than being
separate scenes: **logo layout** vs **text layout** (`show_logos` and
whether logo art is available), and a narrower crop on a single 64x32
panel (`chain_length = 1`) vs the default two-panel 128px width.

Not a scene at all: **night mode** zero-power blanking (`dim_brightness =
0`) skips scene selection and rendering entirely rather than rendering a
scene at brightness 0.

## Web pages

| Page | Served by | Port (default) | Purpose |
|---|---|---|---|
| **Status / config page** | `status_server.py` | `status.port` (8080) | Read-only status snapshot (current scene, game, last poll, last error) plus a form-per-section editor for `scoreboard.toml` -- Scoreboard, Audio, Status page, Night mode, Panel, Wi-Fi, WiFi setup page. Dark dashboard layout, always reachable on the board's normal network. |
| **WiFi setup page** | `setup_server.py` | `wifi_setup.port` (80) | Captive-portal page served only while the board's own first-boot AP is up. Lets a phone pick a nearby network (from a scan cached just before the AP came up) or type one in, submits SSID/password, then the AP tears down and `wifi_join.py` attempts the join -- outcome shown back on the panel (WiFi join scene above), not in the phone's browser, since the AP that request arrived over is what's being torn down. |
