"""Excel output palette.

Mirrors the constants at `modOpenItemsList.bas:18-27`. Values here are RGB
hex (no alpha, no BGR swap) — openpyxl wants RGB.
"""

from __future__ import annotations

from typing import Final

CLR_NAVY: Final[str] = "000F47"
CLR_LIGHTBLUE: Final[str] = "CEECFF"
CLR_CHARCOAL: Final[str] = "3D3C37"
CLR_GRAY_MED: Final[str] = "787974"
CLR_GRAY_LT: Final[str] = "B9B6B1"
CLR_CREAM: Final[str] = "F7F3EE"
CLR_WHITE: Final[str] = "FFFFFF"
CLR_CHK_BG: Final[str] = "E8F4FD"
CLR_SUBTOTAL: Final[str] = "E8E5E0"
CLR_RED: Final[str] = "CC0000"

FONT_NAME: Final[str] = "Noto Sans"
