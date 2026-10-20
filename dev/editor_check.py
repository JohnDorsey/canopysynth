# SPDX-License-Identifier: GPL-3.0-or-later
"""The real-window check of plan steps 10 to 12 (and the way to try the editor by hand).

    python dev/editor_check.py            opens a window and drives it with synthetic mouse events while you watch: draws a graph, moves a node,
                                          makes a connection, is refused one (and says why), zooms, scrolls, pans, adds a node from the menu, turns
                                          a knob and types a value into another, edits a node's name, presses a button, disconnects an inlet and
                                          deletes a node from the right-click menus; with an Engine made over the graph (miniaudio's null backend:
                                          nothing is heard) presses Play and Pause, watches the time field, types a time, opens the device list and
                                          a WAV file and a missing one; selects two nodes with a rectangle, moves them and deletes them.
                                          Every step asserts what it did to the graph; "editor check passed" at the end means all of them held.
    python dev/editor_check.py --try      the same, then leaves the window open so that you can try the editor yourself (close it to finish)
    python dev/editor_check.py --offscreen --fast
                                          no pauses, and the window is placed far off the screen (this is what the test suite runs)
    python dev/editor_check.py --screenshot FILE.png
                                          also saves a picture of the window (Windows only)
    python dev/editor_check.py --audio system
                                          the Engine uses the machine's own audio system instead of the null one (the graph is silent either way:
                                          dev/editor_try.py is the one to listen with)

Things to try by hand with --try: drag a node by its title or body; drag from a green diamond on the right of a node to one on the left of another
(the diamonds a wire may go to light up white, the ones it may not go dim, and every knob turns translucent); try an inlet that already has a wire (it
says so below the picture); wheel = zoom around the pointer, Shift+wheel = scroll sideways, Alt+wheel = scroll up and down, middle-button drag = pan;
right-click on the background for the list of nodes to add and the loop-protection switch; Home fits the whole graph in the window; Escape drops a wire
you are dragging. Knobs (the round dials in a pill to the left of each inlet): drag one up or down to turn it (hover it for its value), double-click it to
type a value (Enter accepts, Escape drops); an inlet that has a wire shows no knob. Widgets: click a text box to type in it, a choice to pick
from its list, a button to press it. With the Engine of this script: Play and Pause the preview node and watch its Time field (type another time into it),
pick a device in its Device list, press Open... on the file node (the name of the file shows in its File row; a file that cannot be read says why under the
node). Right-click: a node (Delete, and Rename... on a boundary node), a connected inlet or a wire (disconnect it). Drag on the empty background to select
the nodes the rectangle touches, then drag any one of them to move them all (right-click one of them: Delete selected); a click on the background clears
the selection."""
import argparse
import ctypes
import os
import struct
import sys
import time
import tempfile
import tkinter as tk
import wave
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


clock = [1000]


def event(editor, sequence, x, y, **options):
    """Generates a mouse event. Tk gives generated events the time 0, which makes presses at one spot double clicks however far apart: each gets a
    time a second after the last unless it is given one."""
    clock[0] += 1000
    options.setdefault("time", clock[0])
    editor.canvas.event_generate(sequence, x=int(round(x)), y=int(round(y)), **options)
    editor.update()


def double_click(editor, show, x, y):
    clock[0] += 10000
    base = clock[0]                                                  # (event() moves the clock on: the times of the four events come from this one)
    for sequence, offset in (("<ButtonPress-1>", 0), ("<ButtonRelease-1>", 10), ("<ButtonPress-1>", 100), ("<ButtonRelease-1>", 110)):
        event(editor, sequence, x, y, time=base + offset)
    show(0.3)


def type_in_box(editor, show, text):
    """Types text into the box the editor has open and presses Enter in it."""
    entry = editor._entry[0]
    entry.delete(0, "end")
    entry.insert(0, text)
    show(0.5)
    entry.focus_force()
    entry.event_generate("<Return>")
    show(0.3)


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
    engine = canopysynth.Engine(graph, registry=rig.registry)
    engine.set_audio_backend(options.audio)
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
    check(editor.canvas.find_withtag("bar:" + str(nodes["file"].id)) == () and len(editor.canvas.find_withtag("rule:" + str(nodes["file"].id))) == 1,
          "a built-in node has no coloured bar, but a thin line under its title")
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
    print("deleting a node from its menu")
    added = graph.nodes()[-1]
    box = editor.box(added)
    event(editor, "<ButtonPress-3>", *editor.view.to_screen(box.x + 10, box.y + 8))
    labels = [popups[-1].entrycget(i, "label") for i in range(popups[-1].index("end") + 1)]
    check(len(popups) == 2 and labels == ["Delete"], "a right click on a node opens its menu (Delete)")
    popups[-1].invoke(0)
    show(0.8)
    check(added.graph is None and len(graph.nodes()) == 6, "choosing Delete removed the node again")
    print("knobs")
    editor.view = geo.View(1.0, 60.0, 50.0)
    editor.redraw()
    show(0.8)
    mult = nodes["mult"]
    knob = editor.box(mult).knob("b")
    centre = editor.view.to_screen(knob.cx, knob.cy)
    drag(editor, show, centre, (centre[0], centre[1] - 50))
    check(mult.knobs["b"] == 1.0, "dragging the middle knob of the Multiply up by 50 pixels turned it from 0.5 to 1.0")
    check(graph.connection_into(mult.inlet("a")) is not None and editor.canvas.find_withtag(f"knob:{mult.id}:a") == ()
          and editor.canvas.find_withtag(f"knob:{mult.id}:b") != (), "an inlet that has a wire shows no knob (its neighbour does)")
    double_click(editor, show, *centre)
    check(editor._entry is not None and editor._entry[0].get() == "1", "double-clicking the knob opened a box holding its value")
    type_in_box(editor, show, "-0.25")
    check(mult.knobs["b"] == -0.25 and editor._entry is None, "typing -0.25 and pressing Enter set the knob")
    print("widgets")
    name = editor.box(nodes["left"]).widgets[0]
    spot = editor.view.to_screen(name.field_x + 10, name.y + name.h / 2)
    event(editor, "<ButtonPress-1>", *spot)
    event(editor, "<ButtonRelease-1>", *spot)
    check(editor._entry is not None and editor._entry[0].get() == "song_left", "clicking the Name box of the boundary outlet opened a box holding the name")
    type_in_box(editor, show, "right_channel")
    check(nodes["left"].settings["name"] == "right_channel" and graph.boundary_nodes()[1].name == "right_channel", "the typed name was set")
    calls = []
    editor.add_action_listener(lambda node, action: calls.append((node.id, action)))
    play = editor.box(nodes["play"]).widgets[0]
    spot = editor.view.to_screen(play.x + play.w / 2, play.y + play.h / 2)
    event(editor, "<ButtonPress-1>", *spot)
    show(0.3)
    event(editor, "<ButtonRelease-1>", *spot)
    check(calls == [(nodes["play"].id, "play")], "pressing the Play button of the preview node told the action listeners 'play'")
    device = editor.box(nodes["play"]).widgets[2]
    spot = editor.view.to_screen(device.field_x + 10, device.y + device.h / 2)
    event(editor, "<ButtonPress-1>", *spot)
    event(editor, "<ButtonRelease-1>", *spot)
    check([popups[-1].entrycget(i, "label") for i in range(popups[-1].index("end") + 1)][0] == "(system default)", "clicking the Device choice opened its list of choices")
    print("disconnecting from the inlet's menu")
    inlet = port(editor, nodes["echo"], "inlet", "in")
    event(editor, "<ButtonPress-3>", *inlet)
    check([popups[-1].entrycget(i, "label") for i in range(popups[-1].index("end") + 1)] == ["Disconnect"], "a right click on a connected inlet opens a menu: Disconnect")
    popups[-1].invoke(0)
    show(0.8)
    check(graph.connection_into(nodes["echo"].inlet("in")) is None, "choosing Disconnect removed the connection")
    print("the engine: playing, the time field, the devices, opening a file")
    editor.view = geo.View(1.0, 60.0, 50.0)
    editor.redraw()
    show(0.5)
    play, file_node = nodes["play"], nodes["file"]
    check(graph.engines() == [engine], "the engine made over the graph is the editor's to keep up to date")

    def centre(node, label, value_box=False):
        w = {w.label: w for w in editor.box(node).widgets}[label]
        return editor.view.to_screen(w.field_x + 10 if value_box else w.x + w.w / 2, w.y + w.h / 2)

    def time_field():
        return editor.canvas.itemcget(f"widgetvalue:{play.id}:3", "text")

    def press_at(spot):
        event(editor, "<ButtonPress-1>", *spot)
        show(0.2)
        event(editor, "<ButtonRelease-1>", *spot)

    def wait_for(condition, seconds=3.0):
        end = time.time() + seconds
        while time.time() < end and not condition():
            root.update()
            time.sleep(0.01)
        return condition()
    engine.action(play.id, "pause")                                  # (the step before pressed Play: start again from a paused node at zero)
    engine.preview_set_time(play.id, 0)
    check(wait_for(lambda: time_field() == "00:00:00.000") and engine.preview_state(play.id) == (False, 0), "a paused preview node at zero shows 00:00:00.000")
    press_at(centre(play, "Play"))
    check(engine.preview_state(play.id)[0] is True, "pressing Play started the preview node")
    check(wait_for(lambda: time_field() != "00:00:00.000"), f"the time field follows the playback ({time_field()})")
    press_at(centre(play, "Pause"))
    check(engine.preview_state(play.id)[0] is False, "pressing Pause stopped it")
    press_at(centre(play, "Time", True))
    type_in_box(editor, show, "00:01:02.500")
    check(engine.preview_state(play.id) == (False, 62_500_000_000) and time_field() == "00:01:02.500", "a typed time 00:01:02.500 moved the playback there")
    press_at(centre(play, "Device", True))
    entries = [popups[-1].entrycget(i, "label") for i in range(popups[-1].index("end") + 1)]
    check(entries[0] == "(system default)" and len(entries) >= 1, f"the Device choice lists the system default and the machine's devices ({len(entries) - 1} found)")
    folder = tempfile.mkdtemp()
    wav = os.path.join(folder, "tone.wav")
    with wave.open(wav, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x10\x00" * 8000)
    editor.file_chooser = lambda node: wav
    press_at(centre(file_node, "Open..."))
    check(file_node.settings["path"] == os.path.abspath(wav) and engine.node_message(file_node.id) == "", "Open... stored the file's absolute path and the engine loaded it")
    check(editor.canvas.itemcget(f"widgetvalue:{file_node.id}:1", "text") == "tone.wav", "the node shows the file's name")
    editor.file_chooser = lambda node: os.path.join(folder, "missing.wav")
    press_at(centre(file_node, "Open..."))
    check("file not found" in editor.canvas.itemcget(f"note:{file_node.id}", "text"), "a file that is not there is said under the node: file not found")
    os.remove(wav)
    os.rmdir(folder)
    print("selecting with a rectangle and moving the selection")
    drag(editor, show, (20, 20), (480, 230), steps=6)
    check(editor.selection == {nodes["file"].id, nodes["mult"].id}, "a rectangle dragged on the background selected the two nodes it touches")
    before = {key: (nodes[key].x, nodes[key].y) for key in ("file", "mult", "echo")}
    grab_box = editor.box(nodes["file"])
    grab = editor.view.to_screen(grab_box.x + 40, grab_box.y + 8)
    drag(editor, show, grab, (grab[0] + 30, grab[1] + 20))
    after = {key: (nodes[key].x, nodes[key].y) for key in ("file", "mult", "echo")}
    check(all(after[key] == (before[key][0] + 30, before[key][1] + 20) for key in ("file", "mult")) and after["echo"] == before["echo"],
          "dragging one selected node moved both by the same amount and left the others")
    event(editor, "<ButtonPress-1>", 840, 460)
    event(editor, "<ButtonRelease-1>", 840, 460)
    check(editor.selection == frozenset(), "a click on the background cleared the selection")
    print("deleting the selection from its menu")
    drag(editor, show, (20, 20), (480, 230), steps=6)
    grab_box = editor.box(nodes["file"])
    event(editor, "<ButtonPress-3>", *editor.view.to_screen(grab_box.x + 40, grab_box.y + 8))
    entries = [popups[-1].entrycget(i, "label") for i in range(popups[-1].index("end") + 1)]
    check(editor.selection == {nodes["file"].id, nodes["mult"].id} and entries == ["Delete selected"], "a right click on one of two selected nodes offers: Delete selected")
    popups[-1].invoke(0)
    show(0.8)
    check(nodes["file"].graph is None and nodes["mult"].graph is None and len(graph.nodes()) == 4, "choosing it deleted both nodes at once")
    check([b.name for b in engine.boundary_nodes()] == ["intensity", "right_channel"], "and the engine compiled the graph without them")
    check(not problems, "no error was raised inside any Tk callback")
    if options.screenshot:
        screenshot(root, options.screenshot)
    if options.use_it:
        editor._popup = type(editor)._popup.__get__(editor)          # real menus again
        print("\nThe window is open for you to try (see the top of this file for things to try). Close it to finish.")
        root.mainloop()
    root.destroy()
    engine.close()
    rig.close()
    print(f"editor check passed ({checks} checks)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="the real-window check of the editor")
    parser.add_argument("--try", dest="use_it", action="store_true", help="leave the window open afterwards")
    parser.add_argument("--fast", action="store_true", help="no pauses")
    parser.add_argument("--offscreen", action="store_true", help="place the window far off the screen")
    parser.add_argument("--screenshot", metavar="FILE", help="save a PNG of the window")
    parser.add_argument("--audio", choices=("null", "system"), default="null", help="the audio system of the Engine (default: null, nothing is heard)")
    run(parser.parse_args())
