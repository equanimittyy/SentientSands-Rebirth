"""The timing and the motion of the tutorial videos, without Pillow, so they can be tested anywhere.

A video is a title card, then one shot for each step of its scene. A shot moves the cursor and the camera to its
target, shows its note for a reading time, and then does its action. Motion.state gives everything that one frame
shows, rounded, so equal frames give equal states and render.py draws each state once.
"""
from collections import namedtuple
from functools import lru_cache

FPS = 30
TITLE = 75
FADE = 12
MOVE = 24
CLICK = 16
TYPE_LEAD = 4
END_HOLD = 60
OUTRO = 20
PAD = 8
MARGIN = 56
GAP = 28
SPRING_FRAMES = 90

State = namedtuple("State", "index enter reveal leave camera rect focus cursor pressed cursor_alpha ripple bubble title pop outro")


def clamp(value, low, high):
    return min(high, max(low, value))


def mix(start, end, progress):
    return start + (end - start) * progress


def ramp(t, start, end):
    return clamp((t - start) / (end - start), 0, 1)


def ease(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


@lru_cache(maxsize=None)
def spring_curve(damping):
    x, speed, curve, steps = 0.0, 0.0, [], 20
    dt = 1 / FPS / steps
    for _ in range(SPRING_FRAMES):
        curve.append(x)
        for _ in range(steps):
            speed += (-100 * (x - 1) - damping * speed) * dt
            x += speed * dt
    return curve


def spring(frame, damping):
    # Underdamped, so a pop overshoots a little
    return 0.0 if frame <= 0 else spring_curve(damping)[min(frame, SPRING_FRAMES - 1)]


def read_frames(note):
    # About 4 words a second, so a viewer reads each note before the cursor moves on
    return min(150, 36 + len(note.split()) * 8) if note else 10


def type_frames(text):
    return round(min(60, max(14, len(text or "") * 1.2)))


def act_frames(shot):
    if shot["action"] == "type":
        return TYPE_LEAD + type_frames(shot["text"]) + 8
    return CLICK if shot["action"] in ("click", "choose") else 0


def layout(shots):
    start, spans = TITLE - FADE, []
    for shot in shots:
        read = read_frames(shot["note"]) + (END_HOLD if shot["action"] == "end" else 0)
        length = MOVE + read + act_frames(shot)
        spans.append({"start": start, "read": read, "length": length})
        start += length
    return spans, start


def camera_of(shot, width, height):
    # The zoom shrinks to fit a big target, and the view never leaves the screenshot, so no empty edge shows
    box = shot["frame"] or shot["box"]
    if not box or shot["zoom"] <= 1:
        return (width / 2, height / 2, 1.0)
    zoom = clamp(min(width * 0.8 / box[2], height * 0.6 / box[3]), 1, shot["zoom"])
    half_width, half_height = width / zoom / 2, height / zoom / 2
    return (clamp(box[0] + box[2] / 2, half_width, width - half_width), clamp(box[1] + box[3] / 2, half_height, height - half_height), zoom)


def bubble_position(rect, size, width, height):
    bubble_width, bubble_height = size
    bottom = height - MARGIN - bubble_height
    if rect is None:
        return ((width - bubble_width) / 2, bottom)
    x, y, w, h = rect
    left = clamp(x + w / 2 - bubble_width / 2, MARGIN, width - MARGIN - bubble_width)
    if y + h + GAP + bubble_height <= height - MARGIN:
        return (left, y + h + GAP)
    if y - GAP - bubble_height >= MARGIN:
        return (left, y - GAP - bubble_height)
    return (left, bottom)


class Motion:
    def __init__(self, timeline):
        self.shots = timeline["shots"]
        self.width, self.height = timeline["width"], timeline["height"]
        self.spans, self.end = layout(self.shots)
        self.total = self.end + OUTRO
        self.cameras = [camera_of(shot, self.width, self.height) for shot in self.shots]
        self.points = []
        for shot in self.shots:
            if shot["box"]:
                x, y, w, h = shot["box"]
                self.points.append((x + w / 2, y + h / 2))
            else:
                self.points.append(self.points[-1] if self.points else self.rest)

    @property
    def rest(self):
        return (self.width * 0.6, self.height * 0.8)

    def state(self, frame):
        shots, spans = self.shots, self.spans
        index = next((i for i, span in enumerate(spans) if frame < span["start"] + span["length"]), len(shots) - 1)
        shot, span = shots[index], spans[index]
        t = frame - span["start"]
        acting = t - MOVE - span["read"]
        moved = ease(clamp(t / MOVE, 0, 1))
        leaving = 1 - ramp(t, span["length"] - 8, span["length"])

        start = self.cameras[index - 1] if index else (self.width / 2, self.height / 2, 1.0)
        x, y, zoom = (mix(a, b, moved) for a, b in zip(start, self.cameras[index]))

        def to_screen(point_x, point_y):
            return ((point_x - x) * zoom + self.width / 2, (point_y - y) * zoom + self.height / 2)

        enter = round(1 - t / FADE, 2) if index and 0 <= t < FADE else 0
        reveal, leave = None, 0
        if shot["action"] == "type":
            typed = TYPE_LEAD + type_frames(shot["text"])
            reveal = round(clamp((acting - TYPE_LEAD) / type_frames(shot["text"]), 0, 1), 3) if acting >= TYPE_LEAD else None
            leave = round(ramp(acting, typed, typed + 6), 2)
        elif shot["action"] in ("click", "choose"):
            leave = round(ramp(acting, 4, 4 + FADE), 2)

        rect, focus = None, 0
        if shot["box"]:
            box_x, box_y, box_w, box_h = shot["box"]
            left, top = to_screen(box_x - PAD, box_y - PAD)
            rect = (round(left), round(top), round((box_w + 2 * PAD) * zoom), round((box_h + 2 * PAD) * zoom))
            focus = round(min(ramp(t, MOVE - 8, MOVE), leaving), 2)

        start_point = self.points[index - 1] if index else self.rest
        cursor = to_screen(mix(start_point[0], self.points[index][0], moved), mix(start_point[1], self.points[index][1], moved))
        clicking = shot["action"] in ("click", "choose", "type")
        ripple = round(acting / CLICK, 2) if clicking and 0 <= acting < CLICK else None
        cursor_alpha = round(1 - ramp(t, MOVE, MOVE + 12), 2) if shot["action"] == "end" else 1

        bubble = round(min(spring(t - (MOVE - 6), 14), leaving), 3) if shot["note"] and t >= MOVE - 6 else 0
        title = round(1 - ramp(frame, TITLE - FADE, TITLE), 3)
        return State(
            index=index,
            enter=enter,
            reveal=reveal,
            leave=leave,
            camera=(round(x, 1), round(y, 1), round(zoom, 4)),
            rect=rect,
            focus=focus,
            cursor=(round(cursor[0]), round(cursor[1])),
            pressed=ripple is not None and acting < 6,
            cursor_alpha=cursor_alpha,
            ripple=ripple,
            bubble=bubble,
            title=title,
            pop=round(spring(frame, 12), 3) if title > 0 else 1,
            outro=round(ramp(frame, self.end, self.end + OUTRO), 3),
        )

