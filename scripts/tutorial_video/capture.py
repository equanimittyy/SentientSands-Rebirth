"""Capture the screenshots of the tutorial videos from the real web app.

Each scene runs against its own copy of the server, filled by scripts/mock_test.py, so a scene that creates or saves
something changes neither the next scene nor your own campaigns and keys. A step saves the page before its action,
with the box of its target, so the video can move a cursor to the box and show the note. The LLM calls of the page
get fixed replies, so no scene needs a key or a model.

The server accepts only the host 127.0.0.1:5000, so the capture needs port 5000 free.
"""
import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from scenes import SCENES

REPO = Path(__file__).resolve().parents[2]
CAPTURES = Path(__file__).resolve().parent / "captures"
BASE = "http://127.0.0.1:5000"
SERVER_PARTS = ["main.py", "core", "chat", "store", "dashboard", "data/templates", "data/prompts", "data/defaults"]
CAMPAIGN = "Playthrough"
# 1920x1080 frames of the CSS layout of a 1280x720 window, so the text is sharp and the page is not tiny
VIEWPORT = {"width": 1280, "height": 720}
SCALE = 1.5
SETTLE_MS = 700
MODELS = {
    "openrouter": ["google/gemini-3-flash-preview", "deepseek/deepseek-v3.2", "moonshotai/kimi-k2.5", "z-ai/glm-4.7"],
    "llamacpp": ["gemma-3-4b-it-Q4_K_M.gguf"],
}


def port_in_use():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", 5000)) == 0


def post(path, body):
    request = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=10).close()


def wait_for_server(server):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if server.poll() is not None:
            sys.exit("The server stopped at start. Install the server packages: python -m pip install -r server/requirements.txt")
        try:
            urllib.request.urlopen(BASE + "/context", timeout=2).close()
            return
        except OSError:
            time.sleep(0.3)
    sys.exit("The server did not start in 30 s.")


@contextmanager
def scratch_server():
    with tempfile.TemporaryDirectory(prefix="ssr-capture-", ignore_cleanup_errors=True) as root:
        root = Path(root)
        for part in SERVER_PARTS:
            source, target = REPO / "server" / part, root / "server" / part
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        (root / "scripts").mkdir()
        shutil.copy2(REPO / "scripts" / "mock_test.py", root / "scripts")
        subprocess.run([sys.executable, str(root / "scripts" / "mock_test.py"), CAMPAIGN], cwd=root, check=True, stdout=subprocess.DEVNULL)
        server = subprocess.Popen([sys.executable, str(root / "server" / "main.py")], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_for_server(server)
            post("/api/campaigns/switch", {"name": CAMPAIGN})
            yield
        finally:
            server.terminate()
            server.wait()


def stub_llm(page):
    def test(route):
        # A real call takes a moment, and the page shows the time that it took
        time.sleep(1.4)
        route.fulfill(json={"status": "ok", "response": "Success"})

    def models(route):
        route.fulfill(json={"status": "ok", "models": MODELS.get(route.request.post_data_json.get("name"), MODELS["openrouter"])})

    page.route("**/api/llm/test", test)
    page.route("**/api/llm/models", models)


def settle(page, ms=SETTLE_MS):
    page.wait_for_function("() => !document.querySelector('dialog#progress[open]')")
    page.wait_for_timeout(ms)


def option_value(target, text):
    value = target.evaluate("(select, text) => [...select.options].find((option) => option.text.includes(text))?.value", text)
    if value is None:
        raise LookupError(f"No option holds {text!r}.")
    return value


def act(step, target):
    if step.action == "click":
        target.click()
    elif step.action == "fill":
        target.fill(step.value)
    elif step.action == "append":
        target.evaluate("(field) => { field.focus(); field.setSelectionRange(field.value.length, field.value.length); }")
        target.press_sequentially(step.value)
    elif step.action == "choose":
        target.select_option(value=option_value(target, step.value))


def capture(browser, scene, theme):
    out = CAPTURES / scene.id
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE, color_scheme=theme)
    page = context.new_page()
    stub_llm(page)
    page.goto(BASE + "/")
    shots = []
    try:
        for number, step in enumerate(scene.steps, 1):
            if step.action == "goto":
                page.evaluate("(hash) => { location.hash = hash; window.scrollTo(0, 0); }", step.value)
                settle(page)
                continue
            try:
                target = step.target(page)
                target.wait_for(state="visible")
                target.evaluate("(element) => element.scrollIntoView({ block: 'center', behavior: 'instant' })")
                page.wait_for_timeout(300)
                box = target.bounding_box()
                # The camera frames the whole field, so the label of an input stays in view
                frame = target.evaluate("(element) => { const r = (element.closest('label') ?? element).getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                image = f"{len(shots):02}.png"
                page.screenshot(path=out / image)
                shot = {
                    "image": image,
                    "after": image,
                    "action": "type" if step.action in ("fill", "append") else step.action,
                    "box": [round(value * SCALE) for value in (box["x"], box["y"], box["width"], box["height"])],
                    "frame": [round(value * SCALE) for value in frame],
                    "note": step.note,
                    "zoom": step.zoom,
                    "text": step.value,
                }
                shots.append(shot)
                act(step, target)
                settle(page)
                # Before the next step scrolls, so the video shows the result of the action in place
                if step.action != "look":
                    shot["after"] = f"{len(shots) - 1:02}-after.png"
                    page.screenshot(path=out / shot["after"])
            except Exception as error:
                page.screenshot(path=out / "failed.png")
                raise RuntimeError(f"Step {number} ({step.action}, note {step.note!r}) failed. The page is in {out / 'failed.png'}.") from error
        image = f"{len(shots):02}.png"
        page.screenshot(path=out / image)
        shots.append({"image": image, "after": image, "action": "end", "box": None, "frame": None, "note": scene.outro, "zoom": 1, "text": None})
    finally:
        context.close()
    timeline = {"id": scene.id, "title": scene.title, "width": round(VIEWPORT["width"] * SCALE), "height": round(VIEWPORT["height"] * SCALE), "shots": shots}
    (out / "timeline.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenes", nargs="*", help=f"the scenes to capture (default: all): {', '.join(scene.id for scene in SCENES)}")
    parser.add_argument("--theme", choices=["light", "dark"], default="light", help="the theme of the web app (default: light)")
    args = parser.parse_args()
    known = {scene.id: scene for scene in SCENES}
    unknown = [name for name in args.scenes if name not in known]
    if unknown:
        sys.exit(f"Unknown scenes: {', '.join(unknown)}")
    # The server kills each process that listens on port 5000, such as a forwarded port of a dev container
    if port_in_use():
        sys.exit("Port 5000 is in use. Close Kenshi, stop the SSR server, and stop any forwarded port 5000, then run again.")
    failed = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for scene in [known[name] for name in args.scenes] or SCENES:
            print(f"Capturing {scene.id}...")
            with scratch_server():
                try:
                    capture(browser, scene, args.theme)
                except Exception as error:
                    failed.append(scene.id)
                    print(f"  {error}\n  Cause: {error.__cause__}")
        browser.close()
    if failed:
        sys.exit(f"Failed: {', '.join(failed)}")
    print(f"Saved the captures in {CAPTURES}.")


if __name__ == "__main__":
    main()
