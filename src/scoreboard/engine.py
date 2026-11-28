"""The scoreboard without the board: the same app and renderer, no hardware around it.

``ScoreboardApp`` is the engine (fetch data, pick the scene, draw it) plus a shell of things only
the Pi has: the GPIO button, light sensor, audio, the admin and WiFi-setup pages, the mDNS alias.
``Engine`` builds it on the pure-Python software backend with that shell switched off, and
lets a host that owns its own loop -- an Android service, a screenshot script, a test -- pump it:

    engine = Engine(settings)
    engine.start()
    while host_is_running:
        frame = engine.step()          # a ``Frame`` when the panel changed, else None
        host.sleep(engine.frame_interval())
    engine.stop()

Nothing here imports ``rgbmatrix``, ``gpiozero`` or a browser; ``tests/test_engine_boundary.py``
keeps the drawing code from importing the shell.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .app import ScoreboardApp
from .config import Settings
from .display import software
from .display.mirror import Frame


class Engine:
    def __init__(self, settings: Settings, **app_kwargs: Any) -> None:
        # No admin page, no horn: a host has its own UI and audio.
        headless = dataclasses.replace(
            settings,
            status=dataclasses.replace(settings.status, enabled=False),
            audio=dataclasses.replace(settings.audio, enabled=False),
        )
        self.app = ScoreboardApp(headless, backend=software.backend(), **app_kwargs)
        self._shown = 0

    @property
    def width(self) -> int:
        return self.app.settings.panel.width

    @property
    def height(self) -> int:
        return self.app.settings.panel.height

    def start(self) -> None:
        self.app.start()

    def step(self) -> Frame | None:
        """Run one pass of the engine and draw; the frame if the panel was redrawn."""
        self.app.tick()
        self.app.draw()
        return self.latest_frame()

    def latest_frame(self) -> Frame | None:
        """The frame last shown, or None if nothing new has been shown since the last call."""
        matrix = self.app.matrix
        if matrix.frames_shown == self._shown:
            return None
        self._shown = matrix.frames_shown
        return Frame(
            seq=self._shown,
            width=self.width,
            height=self.height,
            pixels=matrix.latest_pixels(),
            brightness=self.app._applied_brightness,
            captured_at=self.app.clock(),
        )

    def frame_interval(self) -> float:
        return self.app.frame_interval()

    def stop(self) -> None:
        self.app.shutdown()
