#!/usr/bin/env python3
"""Create a vertical director-lapian showcase video.

Layout:
- top half: source video playback, with blurred background and original audio.
- bottom half: scrolling image-text Markdown report, preserving frame images,
  timecodes, section headings, node notes, and sound/subtitle notes.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from PIL import Image, ImageDraw, ImageFont, ImageOps


WIDTH = 1080
TOP_HEIGHT = 960
BOTTOM_HEIGHT = 960
DEFAULT_FPS = 30

MARGIN_X = 38
MARGIN_Y = 36
CARD_PAD = 18
THUMB_W = 132
THUMB_H = 235

BG = (14, 16, 22)
CARD_BG = (25, 29, 38)
CARD_BG_2 = (30, 35, 46)
BORDER = (58, 65, 82)
TEXT = (238, 241, 246)
MUTED = (166, 174, 189)
ACCENT = (255, 101, 130)
GOLD = (255, 211, 128)
CYAN = (105, 216, 255)
GREEN = (158, 231, 190)

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((?:<([^>]+)>|([^)]+))\)")
ILLEGAL_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Block:
    kind: str
    payload: Any


@dataclass
class Op:
    kind: str
    payload: Any
    height: int


def find_font() -> str:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttf"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for font in candidates:
        if font.exists():
            return str(font)
    raise FileNotFoundError("No Chinese font found in C:\\Windows\\Fonts.")


def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size=size)


def clean_inline(text: str) -> str:
    text = html.unescape(text)
    text = IMAGE_RE.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = text.replace("`", "")
    text = text.replace("<br>", " ").replace("<br/>", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def resolve_image_path(report_path: Path, markdown_cell: str, project_dir: Path | None) -> Path | None:
    match = IMAGE_RE.search(markdown_cell)
    if not match:
        return None

    raw_href = match.group(2) or match.group(3) or ""
    href = unquote(raw_href.strip())
    candidate = (report_path.parent / href).resolve()
    if candidate.exists():
        return candidate

    if project_dir:
        candidate = (project_dir / href).resolve()
        if candidate.exists():
            return candidate

    frame_name_match = re.search(r"frame_\d+\.(?:jpg|jpeg|png|webp)", href, flags=re.IGNORECASE)
    if frame_name_match:
        search_roots = [report_path.parent.parent, project_dir] if project_dir else [report_path.parent.parent]
        for root in [item for item in search_roots if item]:
            for folder in [root / "01_逐秒抽帧" / "frames", root / "01_逐秒抽帧", root / "01_逐帧抽帧" / "frames"]:
                fallback = folder / frame_name_match.group(0)
                if fallback.exists():
                    return fallback
            try:
                matches = list(root.glob(f"01_*/**/{frame_name_match.group(0)}"))
            except OSError:
                matches = []
            if matches:
                return matches[0]
    return None


def normalize_report_text(text: str) -> str:
    # Some generated reports can glue a heading and a table on one line.
    return re.sub(r"(#{1,6} [^\n|]+)(\| [^\n]+\|)", r"\1\n\2", text)


def read_report_text(report_path: Path) -> str:
    return normalize_report_text(report_path.read_text(encoding="utf-8-sig"))


def parse_report(report_path: Path, project_dir: Path | None) -> list[Block]:
    lines = read_report_text(report_path).splitlines()
    blocks: list[Block] = []
    paragraph: list[str] = []
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            text = clean_inline(" ".join(paragraph))
            if text:
                blocks.append(Block("paragraph", text))
            paragraph = []

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            flush_paragraph()
            blocks.append(Block("space", None))
            i += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match and not line.startswith("|"):
            flush_paragraph()
            blocks.append(Block(f"h{min(len(heading_match.group(1)), 4)}", clean_inline(heading_match.group(2))))
            i += 1
            continue

        if line.startswith("|"):
            flush_paragraph()
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1

            rows = [split_table_row(row) for row in table_lines]
            rows = [row for row in rows if not is_separator_row(row)]
            has_images = any(IMAGE_RE.search(cell) for row in rows for cell in row)
            if has_images:
                frame_rows: list[dict[str, Any]] = []
                for row in rows[1:]:
                    if len(row) < 4:
                        continue
                    timecode = clean_inline(row[0])
                    if not re.fullmatch(r"\d\d:\d\d(?:\.\d+)?", timecode):
                        continue
                    frame_cell = row[1]
                    frame_alt = IMAGE_RE.search(frame_cell)
                    frame_rows.append(
                        {
                            "time": timecode,
                            "frame_label": frame_alt.group(1) if frame_alt else timecode,
                            "image": resolve_image_path(report_path, frame_cell, project_dir),
                            "note": clean_inline(row[2]),
                            "sound": clean_inline(row[3]),
                        }
                    )
                if frame_rows:
                    blocks.append(Block("frame_table", frame_rows))
            else:
                simple_rows: list[list[str]] = []
                for row in rows:
                    cleaned = [clean_inline(cell) for cell in row]
                    if any(cleaned):
                        simple_rows.append(cleaned)
                if simple_rows:
                    blocks.append(Block("table", simple_rows))
            continue

        if line.startswith("- "):
            flush_paragraph()
            blocks.append(Block("bullet", clean_inline(line[2:])))
            i += 1
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return blocks


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = char
    if current:
        lines.append(current)
    return lines


def load_thumb(path: Path | None) -> Image.Image:
    if path and path.exists():
        with Image.open(path) as src:
            return ImageOps.fit(src.convert("RGB"), (THUMB_W, THUMB_H), method=Image.Resampling.LANCZOS)

    image = Image.new("RGB", (THUMB_W, THUMB_H), (42, 46, 56))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, THUMB_W - 1, THUMB_H - 1), outline=(86, 92, 108), width=2)
    draw.line((18, 118, THUMB_W - 18, 118), fill=(86, 92, 108), width=2)
    return image


def build_ops(blocks: list[Block], fonts: dict[str, ImageFont.FreeTypeFont]) -> list[Op]:
    dummy = Image.new("RGB", (WIDTH, 100), BG)
    draw = ImageDraw.Draw(dummy)
    ops: list[Op] = []
    body_width = WIDTH - MARGIN_X * 2

    for block in blocks:
        kind = block.kind
        payload = block.payload

        if kind == "space":
            ops.append(Op("space", None, 14))
            continue

        if kind in {"h1", "h2", "h3", "h4"}:
            font = {"h1": fonts["title"], "h2": fonts["h2"], "h3": fonts["h3"], "h4": fonts["h4"]}[kind]
            line_h = {"h1": 54, "h2": 43, "h3": 38, "h4": 35}[kind]
            lines = wrap_text(draw, payload, font, body_width)
            ops.append(Op(kind, lines, len(lines) * line_h + (26 if kind == "h1" else 20)))
            continue

        if kind == "paragraph":
            lines = wrap_text(draw, payload, fonts["body"], body_width)
            if lines:
                ops.append(Op("paragraph", lines, len(lines) * 35 + 14))
            continue

        if kind == "bullet":
            lines = wrap_text(draw, "· " + payload, fonts["body"], body_width)
            ops.append(Op("bullet", lines, len(lines) * 35 + 10))
            continue

        if kind == "table":
            for index, row in enumerate(payload):
                text = "  |  ".join(cell for cell in row if cell)
                if not text:
                    continue
                font = fonts["small_bold"] if index == 0 else fonts["small"]
                lines = wrap_text(draw, text, font, body_width - 28)
                ops.append(Op("table_row_header" if index == 0 else "table_row", lines, len(lines) * 30 + 18))
            ops.append(Op("space", None, 10))
            continue

        if kind == "frame_table":
            for row in payload:
                text_width = WIDTH - MARGIN_X * 2 - THUMB_W - 34
                note_lines = wrap_text(draw, row["note"], fonts["body"], text_width)
                sound_lines = wrap_text(draw, row["sound"], fonts["small"], text_width)
                text_height = 46 + len(note_lines) * 35 + 10 + len(sound_lines) * 30
                height = max(THUMB_H + CARD_PAD * 2, text_height + CARD_PAD * 2)
                ops.append(Op("frame_row", {**row, "note_lines": note_lines, "sound_lines": sound_lines}, height + 10))
            ops.append(Op("space", None, 16))

    return ops


def render_scroll_image(report_path: Path, out_path: Path, project_dir: Path | None) -> None:
    font_path = find_font()
    fonts = {
        "title": load_font(font_path, 38),
        "h2": load_font(font_path, 31),
        "h3": load_font(font_path, 28),
        "h4": load_font(font_path, 25),
        "body": load_font(font_path, 25),
        "small": load_font(font_path, 22),
        "small_bold": load_font(font_path, 23),
        "time": load_font(font_path, 29),
        "label": load_font(font_path, 20),
    }

    ops = build_ops(parse_report(report_path, project_dir), fonts)
    total_h = MARGIN_Y * 2 + BOTTOM_HEIGHT + sum(op.height for op in ops)

    image = Image.new("RGB", (WIDTH, total_h), BG)
    draw = ImageDraw.Draw(image)
    y = MARGIN_Y

    for op in ops:
        if op.kind == "space":
            y += op.height
            continue

        if op.kind == "h1":
            for line in op.payload:
                draw.text((MARGIN_X, y), line, font=fonts["title"], fill=GOLD)
                y += 54
            draw.line((MARGIN_X, y + 2, WIDTH - MARGIN_X, y + 2), fill=BORDER, width=2)
            y += op.height - len(op.payload) * 54
            continue

        if op.kind in {"h2", "h3", "h4"}:
            font = {"h2": fonts["h2"], "h3": fonts["h3"], "h4": fonts["h4"]}[op.kind]
            color = {"h2": ACCENT, "h3": GREEN, "h4": GOLD}[op.kind]
            line_h = {"h2": 43, "h3": 38, "h4": 35}[op.kind]
            draw.line((MARGIN_X, y - 8, WIDTH - MARGIN_X, y - 8), fill=(42, 48, 62), width=2)
            for line in op.payload:
                draw.text((MARGIN_X, y), line, font=font, fill=color)
                y += line_h
            y += op.height - len(op.payload) * line_h
            continue

        if op.kind in {"paragraph", "bullet"}:
            for line in op.payload:
                draw.text((MARGIN_X, y), line, font=fonts["body"], fill=TEXT)
                y += 35
            y += op.height - len(op.payload) * 35
            continue

        if op.kind in {"table_row_header", "table_row"}:
            rect_h = op.height - 6
            fill = CARD_BG_2 if op.kind == "table_row_header" else CARD_BG
            draw.rounded_rectangle((MARGIN_X, y, WIDTH - MARGIN_X, y + rect_h), radius=8, fill=fill, outline=BORDER, width=1)
            text_y = y + 9
            font = fonts["small_bold"] if op.kind == "table_row_header" else fonts["small"]
            color = GOLD if op.kind == "table_row_header" else TEXT
            for line in op.payload:
                draw.text((MARGIN_X + 14, text_y), line, font=font, fill=color)
                text_y += 30
            y += op.height
            continue

        if op.kind == "frame_row":
            row = op.payload
            rect_bottom = y + op.height - 10
            draw.rounded_rectangle((MARGIN_X, y, WIDTH - MARGIN_X, rect_bottom), radius=10, fill=CARD_BG, outline=BORDER, width=1)

            thumb_x = MARGIN_X + CARD_PAD
            thumb_y = y + CARD_PAD
            image.paste(load_thumb(row["image"]), (thumb_x, thumb_y))
            draw.rectangle((thumb_x, thumb_y, thumb_x + THUMB_W - 1, thumb_y + THUMB_H - 1), outline=(96, 103, 121), width=2)

            text_x = thumb_x + THUMB_W + 22
            text_y = y + CARD_PAD
            badge_w = 116 if "." in row["time"] else 104
            draw.rounded_rectangle((text_x, text_y, text_x + badge_w, text_y + 38), radius=7, fill=(94, 35, 51), outline=(148, 61, 82), width=1)
            draw.text((text_x + 10, text_y + 1), row["time"], font=fonts["time"], fill=(255, 232, 238))
            draw.text((text_x + badge_w + 14, text_y + 9), "对应抽帧 / 逐秒证据", font=fonts["label"], fill=MUTED)
            text_y += 50

            for line in row["note_lines"]:
                draw.text((text_x, text_y), line, font=fonts["body"], fill=TEXT)
                text_y += 35

            if row["sound_lines"]:
                text_y += 8
                draw.text((text_x, text_y), "声音/字幕", font=fonts["label"], fill=CYAN)
                text_y += 27
                for line in row["sound_lines"]:
                    draw.text((text_x, text_y), line, font=fonts["small"], fill=CYAN)
                    text_y += 30

            y += op.height

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, quality=94)


def ffprobe_duration(video_path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return float(proc.stdout.strip())


def make_video(video_path: Path, scroll_image: Path, out_video: Path, fps: int, crf: int, preset: str) -> None:
    duration = ffprobe_duration(video_path)
    out_video.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:v]scale={WIDTH}:{TOP_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{TOP_HEIGHT},gblur=sigma=22,eq=brightness=-0.08:saturation=0.75[topbg];"
        f"[0:v]scale={WIDTH}:{TOP_HEIGHT}:force_original_aspect_ratio=decrease[topfg];"
        f"[topbg][topfg]overlay=(W-w)/2:(H-h)/2[top];"
        f"[1:v]format=rgb24,crop={WIDTH}:{BOTTOM_HEIGHT}:0:"
        f"min((ih-{BOTTOM_HEIGHT})*t/{duration:.6f}\\,ih-{BOTTOM_HEIGHT})[bottom];"
        f"[top][bottom]vstack=inputs=2,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(scroll_image),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-t",
        f"{duration:.6f}",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(out_video),
    ]
    subprocess.run(cmd, check=True)


def sanitize_name(value: str, fallback: str = "拉片展示") -> str:
    value = ILLEGAL_PATH_CHARS.sub("_", value).strip().strip(".")
    value = re.sub(r"\s+", "_", value)
    return value or fallback


def unique_path(path: Path, overwrite: bool) -> Path:
    if overwrite or not path.exists():
        return path
    base_stem = re.sub(r"_v\d{2}$", "", path.stem)
    for index in range(2, 1000):
        candidate = path.with_name(f"{base_stem}_v{index:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"could not create unique output path near: {path}")


def find_child_by_prefix(project_dir: Path, prefix: str) -> Path | None:
    if not project_dir.exists():
        return None
    matches = [p for p in project_dir.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    if not matches:
        return None
    return sorted(matches, key=lambda p: (p.stat().st_mtime, p.name))[-1]


def infer_report(project_dir: Path) -> Path | None:
    report_dir = find_child_by_prefix(project_dir, "03_") or project_dir / "03_MD报告"
    if not report_dir.exists():
        return None
    reports = [
        p
        for p in report_dir.glob("*.md")
        if "专业导演分析" not in p.name and "风格圣经" not in p.name and p.is_file()
    ]
    if not reports:
        reports = [p for p in report_dir.glob("*.md") if p.is_file()]
    return sorted(reports, key=lambda p: (p.stat().st_mtime, p.name))[-1] if reports else None


def infer_video(project_dir: Path) -> Path | None:
    manifest = project_dir / "manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            raw = (data.get("source") or {}).get("source_path")
            if raw:
                candidate = Path(raw)
                if candidate.exists():
                    return candidate
        except (json.JSONDecodeError, OSError):
            pass
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an upper-video/lower-scrolling-report showcase MP4.")
    parser.add_argument("--project-dir", type=Path, help="director-lapian project directory; used to infer report/video/out-dir")
    parser.add_argument("--video", type=Path, help="source video path")
    parser.add_argument("--report", type=Path, help="image-text Markdown lapian report path")
    parser.add_argument("--out-dir", type=Path, help="defaults to <project-dir>/07_视频展示")
    parser.add_argument("--title", help="output file title prefix; defaults to report stem")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--image-only", action="store_true", help="render only the scrolling report PNG")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_dir = args.project_dir.resolve() if args.project_dir else None
    report = args.report.resolve() if args.report else (infer_report(project_dir) if project_dir else None)
    video = args.video.resolve() if args.video else (infer_video(project_dir) if project_dir else None)

    if not report or not report.exists():
        raise SystemExit("missing report: pass --report or --project-dir with a 03_* Markdown report")
    if not args.image_only and (not video or not video.exists()):
        raise SystemExit("missing video: pass --video or use a project manifest with source.source_path")

    out_dir = args.out_dir.resolve() if args.out_dir else None
    if out_dir is None:
        if project_dir:
            out_dir = project_dir / "07_视频展示"
        else:
            out_dir = report.parent.parent / "07_视频展示"

    title = sanitize_name(args.title or re.sub(r"_v\d+$", "", report.stem))
    scroll_image = unique_path(out_dir / f"{title}_图文报告滚动长图_v01.png", args.overwrite)
    render_scroll_image(report, scroll_image, project_dir)

    result = {"scroll_image": str(scroll_image)}
    if not args.image_only:
        out_video = unique_path(out_dir / f"{title}_上视频下图文报告滚动展示_v01.mp4", args.overwrite)
        make_video(video, scroll_image, out_video, args.fps, args.crf, args.preset)
        result["video"] = str(out_video)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
