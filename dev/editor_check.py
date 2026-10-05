"""The real-window check of plan step 10 (and the way to try the editor by hand).

    python dev/editor_check.py            opens a window and drives it with synthetic mouse events while you watch: draws a graph, moves a node,
                                          makes a connection, is refused one (and says why), zooms, scrolls, pans, adds a node from the menu.
                                          Every step asserts what it did to the graph; "editor check passed" at the end means all of them held.
    python dev/editor_check.py --try      the same, then leaves the window open so that you can try the editor yourself (close it to finish)
    python dev/editor_check.py --offscreen --fast
                                          no pauses, and the window is placed far off the screen (this is what the test suite runs)
    python dev/editor_check.py --screenshot FILE.png
                                          also saves a picture of the window (Windows only)

Things to try by hand with --try: drag a node by its title or body; drag from a green diamond on the right of a node to one on the left of another
(the diamonds a wire may go to light up white, the ones it may not go dim); try an inlet that already has a wire (it says so below the picture); wheel =
zoom around the pointer, Shift+wheel = scroll sideways, Alt+wheel = scroll up and down, middle-button drag = pan; right-click on the background for the
list of nodes to add; Home fits the whole graph in the window; Escape drops a wire you are dragging."""
import argparse
import ctypes
import os
import struct
import sys
import time
import tkinter as tk
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "python"))

import canopysynth                                    # noqa: E402
import engine_dll as e                                # noqa: E402
from canopysynth import _descriptor as d              # noqa: E402
from canopysynth.editor import Editor, geometry as geo, theme   # noqa: E402

checks = 0


def check(condition, text):
    global checks
    if not condition:
        raise SystemExit(f"editor check FAILED: {text}")
    checks += 1
    print(f"  ok  {text}")


class Show:
    """Pauses so that a person can watch (not when --fast)."""

    def __init__(self, root, fast):
        self.root, self.fast = root, fast

    def __call__(self, seconds=0.5):
        self.root.update()
        if not self.fast:
            end = time.time() + seconds
            while time.time() < end:
                self.root.update()
                time.sleep(0.01)


def event(editor, sequence, x, y, **options):
    editor.canvas.event_generate(sequence, x=int(round(x)), y=int(round(y)), **options)
    editor.update()


def drag(editor, show, start, end, button=1, steps=8):
    state = {1: 0x100, 2: 0x200}[button]
    event(editor, f"<ButtonPress-{button}>", *start)
    for i in range(1, steps + 1):
        event(editor, f"<B{button}-Motion>", start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps, state=state)
        show(0.03)
    show(0.2)
    event(editor, f"<ButtonRelease-{button}>", *end)
    show(0.3)


def port(editor, node, kind, key):
    box = editor.box(node)
    p = box.port(kind, key)
    return editor.view.to_screen(p.x, p.y)


def make_graph():
    """Third-party node types like the one in the author's mock-up (a 'Multiply' with three inlets and two outlets), and a graph of them."""
    multiply = e.PyNodeType("vendor.multiply", inlets=[("a", 0.0), ("b", 0.5), ("c", 0.5)], outlets=["out", "aux"], flags=d.FLAG_REALTIME_SAFE,
                            at=lambda ctx, outlet, t: 0.0)
    multiply.type.name = b"Multiply"
    echo = e.PyNodeType("vendor.echo", inlets=[("in", 0.0)], outlets=["out"], at=lambda ctx, outlet, t: 0.0)
    echo.type.name = b"Slow echo"
    rig = e.Rig(multiply, echo)
    graph = canopysynth.Graph(types=canopysynth.NodeTypes.from_registry(rig.registry, e.lib))
    nodes = {
        "file": graph.add("file_read", x=0, y=40, path="C:/audio/song.wav"),
        "mult": graph.add("vendor.multiply", x=260, y=20),
        "echo": graph.add("vendor.echo", x=260, y=200),
        "left": graph.add("boundary_outlet", x=540, y=40, name="song_left"),
        "level": graph.add("boundary_inlet", x=0, y=230, name="intensity"),
        "play": graph.add("realtime_preview", x=540, y=180),
    }
    graph.connect(nodes["file"].outlet("left"), nodes["mult"].inlet("a"))
    graph.connect(nodes["mult"].outlet("out"), nodes["left"].inlet("in"))
    return rig, graph, nodes


def screenshot(window, path):
    """A PNG of the window (Windows: PrintWindow, no extra library)."""
    from ctypes import wintypes
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

    class Header(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG), ("planes", wintypes.WORD), ("bits", wintypes.WORD),
                    ("compression", wintypes.DWORD), ("image", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG), ("used", wintypes.DWORD),
                    ("important", wintypes.DWORD)]

    window.update()
    hwnd = int(window.wm_frame(), 16)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(memory, bitmap)
    user32.PrintWindow(hwnd, memory, 2)
    header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    raw = buffer.raw
    rows = []
    for y in range(height):
        line = raw[y * width * 4:(y + 1) * width * 4]
        rows.append(b"\x00" + b"".join(bytes((line[x * 4 + 2], line[x * 4 + 1], line[x * 4])) for x in range(width)))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
                     + chunk(b"IEND", b""))
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(hwnd, hdc)
    print(f"  picture of the window saved to {path}")


def run(options):
    rig, graph, nodes = make_graph()
    root = tk.Tk()
    root.title("canopysynth editor check")
    root.geometry("860x520" + ("+6000+6000" if options.offscreen else "+80+60"))
    problems = []
    root.report_callback_exception = lambda *details: problems.append(details)
    editor = Editor(root, graph, width=860, height=470)
    editor.pack(fill="both", expand=True)
    show = Show(root, options.fast)
    show(0.8)
    editor.view = geo.View(1.0, 60.0, 50.0)
    editor.redraw()
    editor.canvas.focus_force()
    show(0.8)
    print("drawing")
    check(len(editor.canvas.find_withtag("body")) == 6 and len(editor.canvas.find_withtag("wire")) == 2, "six nodes and two wires are drawn")
    check(editor.canvas.itemcget("bar:" + str(nodes["mult"].id), "fill") == theme.TITLE_BAR_REALTIME_SAFE
          and editor.canvas.itemcget("bar:" + str(nodes["echo"].id), "fill") == theme.TITLE_BAR_NOT_REALTIME_SAFE,
          "the two third-party nodes have title bars of different colours (realtime safe or not)")
    check(editor.canvas.find_withtag("bar:" + str(nodes["file"].id)) == (), "a built-in node has no title bar")
    print("moving a node")
    box = editor.box(nodes["level"])
    start = editor.view.to_screen(box.x + 40, box.y + 30)
    drag(editor, show, start, (start[0] + 60, start[1] + 50))
    check((nodes["level"].x, nodes["level"].y) == (60, 280), "dragging the boundary inlet moved it by exactly the drag")
    print("connecting")
    drag(editor, show, port(editor, nodes["level"], "outlet", "out"), port(editor, nodes["echo"], "inlet", "in"))
    check(graph.connection_into(nodes["echo"].inlet("in")) is not None, "a wire from the boundary inlet to the echo's inlet was made")
    drag(editor, show, port(editor, nodes["echo"], "outlet", "out"), port(editor, nodes["play"], "inlet", "center"))
    check(graph.connection_into(nodes["play"].inlet("center")) is not None, "and from the echo to the preview's centre inlet")
    print("being refused")
    before = graph.to_dict()
    drag(editor, show, port(editor, nodes["level"], "outlet", "out"), port(editor, nodes["mult"].inlet("a").node, "inlet", "a"))
    check(graph.to_dict() == before and "already connected" in editor.message, f"a wire to an inlet that is taken is refused: \"{editor.message[:60]}...\"")
    show(1.0)
    drag(editor, show, port(editor, nodes["mult"], "outlet", "aux"), port(editor, nodes["mult"], "inlet", "b"))
    check(graph.to_dict() == before and "loop" in editor.message, f"a wire from a node into itself is refused: \"{editor.message[:60]}...\"")
    show(1.0)
    print("zooming and scrolling")
    scale = editor.view.scale
    event(editor, "<MouseWheel>", 430, 250, delta=120)
    event(editor, "<MouseWheel>", 430, 250, delta=120)
    show(0.5)
    check(abs(editor.view.scale - scale * 1.1 ** 2) < 1e-9, "two wheel notches zoomed in by 10% each")
    ox, oy = editor.view.ox, editor.view.oy
    event(editor, "<MouseWheel>", 430, 250, delta=120, state=0x1)
    check(editor.view.ox == ox + theme.SCROLL_STEP, "Shift+wheel scrolled sideways")
    event(editor, "<MouseWheel>", 430, 250, delta=-120, state=0x20000)
    check(editor.view.oy == oy - theme.SCROLL_STEP, "Alt+wheel scrolled up and down")
    ox, oy = editor.view.ox, editor.view.oy
    drag(editor, show, (400, 300), (340, 330), button=2)
    check((editor.view.ox, editor.view.oy) == (ox - 60, oy + 30), "a middle-button drag panned the picture")
    editor.fit()
    show(0.8)
    check(all(0 <= editor.view.to_screen(box.x, box.y)[0] <= editor.canvas.winfo_width() for box in editor.layout()), "fit shows the whole graph")
    print("adding a node from the menu")
    popups = []
    editor._popup = lambda menu, x, y: popups.append(menu)          # (a real pop-up menu would wait for a click; the menu is inspected instead)
    event(editor, "<ButtonPress-3>", 30, 30)
    check(len(popups) == 1, "a right click on the background opens the add-node menu")
    menu = popups[0]
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    check(labels[:4] == ["Boundary inlet", "Boundary outlet", "File read", "Realtime preview"] and "Multiply" in labels and "Test filter (hidden)" not in labels,
          "it lists the built-in nodes first, then the third-party ones, and not the hidden test node")
    menu.invoke(labels.index("Multiply") + 1)                    # (entry numbers count the separator between the built-in and the third-party types)
    show(0.8)
    check(graph.nodes()[-1].type == "vendor.multiply" and editor.selected == graph.nodes()[-1].id, "choosing Multiply added one at the clicked place, selected")
    check(not problems, "no error was raised inside any Tk callback")
    if options.screenshot:
        screenshot(root, options.screenshot)
    if options.use_it:
        editor._popup = type(editor)._popup.__get__(editor)          # real menus again
        print("\nThe window is open for you to try (see the top of this file for things to try). Close it to finish.")
        root.mainloop()
    root.destroy()
    rig.close()
    print(f"editor check passed ({checks} checks)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="the real-window check of the editor")
    parser.add_argument("--try", dest="use_it", action="store_true", help="leave the window open afterwards")
    parser.add_argument("--fast", action="store_true", help="no pauses")
    parser.add_argument("--offscreen", action="store_true", help="place the window far off the screen")
    parser.add_argument("--screenshot", metavar="FILE", help="save a PNG of the window")
    run(parser.parse_args())
