#!/usr/bin/env python3
"""Cross-platform Chinese font discovery for director-lapian renderers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


CHINESE_FONT_CANDIDATES = (
    # Windows
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyh.ttf"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/Deng.ttf"),
    # macOS
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path.home() / "Library/Fonts/NotoSansCJKsc-Regular.otf",
    # Linux
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
)


def find_chinese_font(
    explicit_font: Path | None = None,
    candidates: Iterable[Path] | None = None,
) -> str:
    if explicit_font is not None:
        path = explicit_font.expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Explicit Chinese font file not found: {path}")
        return str(path.resolve())

    for path in candidates if candidates is not None else CHINESE_FONT_CANDIDATES:
        expanded = path.expanduser()
        if expanded.is_file():
            return str(expanded.resolve())

    raise FileNotFoundError(
        "No Chinese-capable font found on Windows, macOS, or Linux. "
        "Install Microsoft YaHei, PingFang, or Noto Sans CJK, or pass --font PATH."
    )
