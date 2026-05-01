from __future__ import annotations

from textual.app import App

from openitems.config import Config
from openitems.db.schema import init_schema
from openitems.tui.screens.engagement_switcher import EngagementSwitcher
from openitems.tui.screens.main import MainScreen


class OpenItemsApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "openitems"

    def on_mount(self) -> None:
        init_schema()
        screen = MainScreen()
        self.push_screen(screen)

        cfg = Config.load()
        if cfg.active_engagement:
            screen.set_engagement(cfg.active_engagement)
        else:
            self.push_screen(EngagementSwitcher(), self._handle_initial_engagement)

    def _handle_initial_engagement(self, slug: str | None) -> None:
        if not slug:
            return
        # MainScreen is now the visible screen
        screen = self.screen_stack[-1]
        if isinstance(screen, MainScreen):
            screen.set_engagement(slug)
