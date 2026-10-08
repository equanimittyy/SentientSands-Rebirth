"""Render the tutorial videos and their posters from the captures of capture.py.

Pillow draws each frame, and the ffmpeg of imageio-ffmpeg encodes the frames as H.264, which every browser plays.
A frame shows the screenshot of the current step through a camera that zooms on its target, a cursor, a ring around
the target with the rest of the page dimmed, and a bubble with the note of the step. The videos go into the web app,
which serves them to the Tutorial tab.
"""
import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from motion import FPS, Motion, bubble_position

HERE = Path(__file__).resolve().parent
CAPTURES = HERE / "captures"
WEB = HERE.parents[1] / "server" / "dashboard" / "web"
VIDEOS = WEB / "videos"
TITLE_FONT = WEB / "fonts" / "Lacquer" / "Lacquer-Regular.ttf"
TEXT_FONT = WEB / "fonts" / "WalterTurncoat" / "WalterTurncoat-Regular.ttf"
CRF = 23
# The title card, so the poster names the topic
POSTER_FRAME = 40
# Pillow draws shapes without antialiasing, so smooth shapes are drawn this many times larger and scaled down
SUPERSAMPLE = 3
LANCZOS = Image.Resampling.LANCZOS

PARCHMENT = (244, 234, 216)
SURFACE = (251, 245, 234)
INK = (43, 33, 24)
ACCENT = (181, 118, 42)
NIGHT = (27, 23, 19)
DIM = (20, 14, 8)
DIM_ALPHA = 115
BUBBLE_WIDTH = 760
CURSOR_POINTS = [(2, 2), (2, 34), (10, 27), (16, 40), (22, 37), (16, 25), (26, 25)]


def smooth(size, draw):
    big = Image.new("RGBA", (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), (0, 0, 0, 0))
    draw(ImageDraw.Draw(big), SUPERSAMPLE)
    return big.resize(size, LANCZOS)


def faded(image, opacity):
    if opacity >= 1:
        return image
    result = image.copy()
    result.putalpha(image.getchannel("A").point(lambda alpha: round(alpha * opacity)))
    return result


def with_shadow(image, offset, blur, strength):
    margin = blur * 2 + offset
    canvas = Image.new("RGBA", (image.width + 2 * margin, image.height + 2 * margin), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 255), (margin, margin + offset), image.getchannel("A").point(lambda alpha: round(alpha * strength)))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(image, (margin, margin))
    return canvas, margin


def paste(frame, image, position, opacity=1):
    if opacity > 0:
        layer = faded(image, opacity)
        frame.paste(layer, (round(position[0]), round(position[1])), layer)


def cursor_image(scale):
    size = 1.5 * scale

    def draw(canvas, factor):
        points = [(x * size * factor, y * size * factor) for x, y in CURSOR_POINTS]
        canvas.polygon(points, fill=(255, 255, 255, 255), outline=NIGHT + (255,), width=round(2.5 * size * factor))

    image, margin = with_shadow(smooth((round(28 * size), round(42 * size)), draw), 4, 4, 0.45)
    return image, (margin + 2 * size, margin + 2 * size)


def wrap(text, font, width):
    lines = []
    for word in text.split():
        if lines and font.getlength(f"{lines[-1]} {word}") <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def bubble_image(note):
    font = ImageFont.truetype(str(TEXT_FONT), 40)
    border, padding_x, padding_y, line_height = 4, 32, 22, 52
    lines = wrap(note, font, BUBBLE_WIDTH - 2 * (border + padding_x))
    size = (round(max(font.getlength(line) for line in lines)) + 2 * (border + padding_x), len(lines) * line_height + 2 * (border + padding_y))
    box = smooth(size, lambda canvas, factor: canvas.rounded_rectangle(
        (0, 0, size[0] * factor - 1, size[1] * factor - 1), radius=18 * factor, fill=SURFACE + (255,), outline=INK + (255,), width=border * factor))
    draw = ImageDraw.Draw(box)
    for number, line in enumerate(lines):
        draw.text((border + padding_x, border + padding_y + number * line_height + line_height / 2), line, font=font, fill=INK, anchor="lm")
    return with_shadow(box, 18, 20, 0.35)


@lru_cache(maxsize=64)
def ring(width, height):
    return smooth((width, height), lambda canvas, factor: canvas.rounded_rectangle(
        (0, 0, width * factor - 1, height * factor - 1), radius=12 * factor, outline=ACCENT + (255,), width=5 * factor))


@lru_cache(maxsize=64)
def hole(width, height):
    return smooth((width, height), lambda canvas, factor: canvas.rounded_rectangle(
        (0, 0, width * factor - 1, height * factor - 1), radius=12 * factor, fill=(255, 255, 255, 255))).getchannel("A")


@lru_cache(maxsize=128)
def ripple(radius):
    size = 2 * radius + 8
    return smooth((size, size), lambda canvas, factor: canvas.ellipse(
        (4 * factor, 4 * factor, (size - 4) * factor, (size - 4) * factor), outline=ACCENT + (255,), width=6 * factor))


class TitleCard:
    def __init__(self, title, size):
        banner = Image.open(WEB / "images" / "banner.jpg").convert("RGB").resize(size, LANCZOS)
        self.size = size
        self.background = Image.blend(Image.new("RGB", size, NIGHT), banner, 0.35)
        logo = Image.open(WEB / "images" / "logo.png").convert("RGBA")
        logo = logo.resize((520, round(520 * logo.height / logo.width)), LANCZOS)
        title_font, text_font = ImageFont.truetype(str(TITLE_FONT), 104), ImageFont.truetype(str(TEXT_FONT), 40)
        subtitle = "Sentient Sands Rebirth tutorial"
        width = round(max(logo.width, title_font.getlength(title), text_font.getlength(subtitle))) + 20
        self.content = Image.new("RGBA", (width, logo.height + 230), (0, 0, 0, 0))
        self.content.alpha_composite(logo, ((width - logo.width) // 2, 0))
        draw = ImageDraw.Draw(self.content)
        draw.text((width / 2, logo.height + 24), title, font=title_font, fill=PARCHMENT, anchor="ma")
        draw.text((width / 2, logo.height + 170), subtitle, font=text_font, fill=ACCENT, anchor="ma")
        self.at = lru_cache(maxsize=None)(self._at)

    def _at(self, pop):
        frame = self.background.copy()
        scale = 0.85 + 0.15 * pop
        layer = self.content.resize((round(self.content.width * scale), round(self.content.height * scale)), LANCZOS)
        paste(frame, layer, ((self.size[0] - layer.width) / 2, (self.size[1] - layer.height) / 2), min(pop, 1))
        return frame


class Video:
    def __init__(self, name):
        folder = CAPTURES / name
        timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
        self.motion = Motion(timeline)
        self.size = (timeline["width"], timeline["height"])
        self.images = [Image.open(folder / shot["image"]).convert("RGB").resize(self.size, LANCZOS) for shot in self.motion.shots]
        self.bubbles = {index: bubble_image(shot["note"]) for index, shot in enumerate(self.motion.shots) if shot["note"]}
        self.cursors = {False: cursor_image(1), True: cursor_image(0.85)}
        self.title = TitleCard(timeline["title"], self.size)
        self.night = Image.new("RGB", self.size, NIGHT)

    def page(self, state):
        page = self.images[state.index]
        if state.fade:
            page = Image.blend(page, self.images[state.index - 1], state.fade)
        if state.reveal:
            x, y, w, h = self.motion.shots[state.index]["box"]
            typed = round(w * state.reveal)
            if typed > 0:
                page = page.copy()
                page.paste(self.images[state.index + 1].crop((x, y, x + typed, y + h)), (x, y))
        x, y, zoom = state.camera
        width, height = self.size
        return page.resize(self.size, Image.Resampling.BICUBIC, box=(x - width / 2 / zoom, y - height / 2 / zoom, x + width / 2 / zoom, y + height / 2 / zoom))

    def draw(self, state):
        frame = self.page(state)
        width, height = self.size
        if state.rect and state.focus > 0:
            x, y, w, h = state.rect
            dim = round(DIM_ALPHA * state.focus)
            mask = Image.new("L", self.size, dim)
            mask.paste(hole(w, h).point(lambda value: dim * (255 - value) // 255), (x, y))
            frame.paste(DIM, (0, 0, width, height), mask)
            paste(frame, ring(w, h), (x, y), state.focus)
        if state.ripple is not None:
            radius = round(10 + 60 * state.ripple)
            paste(frame, ripple(radius), (state.cursor[0] - radius - 4, state.cursor[1] - radius - 4), 1 - state.ripple)
        cursor, tip = self.cursors[state.pressed]
        paste(frame, cursor, (state.cursor[0] - tip[0], state.cursor[1] - tip[1]), state.cursor_alpha)
        if state.bubble > 0:
            image, margin = self.bubbles[state.index]
            full = (image.width - 2 * margin, image.height - 2 * margin)
            left, top = bubble_position(state.rect, full, width, height)
            scale = 0.9 + 0.1 * state.bubble
            scaled = image.resize((round(image.width * scale), round(image.height * scale)), LANCZOS)
            paste(frame, scaled, (left + full[0] / 2 - scaled.width / 2, top + full[1] / 2 - scaled.height / 2), min(state.bubble, 1))
        if state.title > 0:
            frame = Image.blend(frame, self.title.at(state.pop), state.title)
        if state.outro > 0:
            frame = Image.blend(frame, self.night, state.outro)
        return frame

    def render(self, video, poster):
        writer = imageio_ffmpeg.write_frames(
            str(video), self.size, fps=FPS, codec="libx264", quality=None, macro_block_size=8,
            output_params=["-crf", str(CRF), "-preset", "slow", "-movflags", "+faststart"])
        writer.send(None)
        last_state, image, data = None, None, None
        for frame in range(self.motion.total):
            state = self.motion.state(frame)
            # A held frame repeats its state, so it is drawn once
            if state != last_state:
                last_state, image = state, self.draw(state)
                data = image.tobytes()
            writer.send(data)
            if frame == POSTER_FRAME:
                image.save(poster, quality=85)
        writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenes", nargs="*", help="the scenes to render (default: every captured scene)")
    names = parser.parse_args().scenes or sorted(path.parent.name for path in CAPTURES.glob("*/timeline.json"))
    missing = [name for name in names if not (CAPTURES / name / "timeline.json").exists()]
    if missing or not names:
        sys.exit(f"No capture of {', '.join(missing) or 'any scene'}. Run capture.py first.")
    VIDEOS.mkdir(exist_ok=True)
    for name in names:
        print(f"Rendering {name}...")
        video, poster = VIDEOS / f"{name}.mp4", VIDEOS / f"{name}.jpg"
        Video(name).render(video, poster)
        print(f"  {video.stat().st_size / 1e6:.1f} MB video, {poster.stat().st_size / 1e3:.0f} KB poster")


if __name__ == "__main__":
    main()
