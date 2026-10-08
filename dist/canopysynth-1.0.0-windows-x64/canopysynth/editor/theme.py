"""How the editor looks: colours and sizes in one place. Sizes are in world units (pixels at zoom 1); the view scales them.

The look follows the author's mock-up (plan step 10): a dark background, grey nodes with a black outline and rounded corners, diamond ports,
blue wires. Every node has a title bar across the top of its body. Built-in nodes (keys without a dot) have an uncoloured one: the title in
off-white text on the node's own grey, with a thin off-white line under it that stops short of the node's edges; third-party nodes (keys with a
dot) have a coloured bar, whose colour says whether the node type is realtime safe (the author chose the two colours at step 10 and 11)."""

BACKGROUND = "#262626"
NODE_FILL = "#666666"
NODE_OUTLINE = "#000000"
NODE_OUTLINE_SELECTED = "#7FD0FF"         # the outline of every selected node, and of the rectangle dragged to select
MARQUEE_DASH = (5, 3)                     # the dash pattern of that rectangle (pixels drawn, pixels left out)

TITLE_TEXT_BUILTIN = "#EDE8D8"            # off-white, on the node
TITLE_RULE = "#EDE8D8"                    # the thin line under a built-in node's title
TITLE_BAR_REALTIME_SAFE = "#EFE3B0"       # third-party node types flagged realtime_safe (the cream of the mock-up)
TITLE_BAR_NOT_REALTIME_SAFE = "#D97A5E"   # third-party node types that are not: a muted vermillion (the author's step 10 try-out: darker than the first peach)
TITLE_BAR_TEXT = "#000000"

PORT_FILL = "#B5E61D"
PORT_FILL_REFUSED = "#5E6B2A"             # while a wire is dragged: a port the wire may not be dropped on
PORT_OUTLINE = "#000000"
PORT_OUTLINE_TARGET = "#FFFFFF"           # while a wire is dragged: a port it may be dropped on
PORT_OUTLINE_HOVER = "#7FD0FF"

WIRE = "#0AA0E8"
WIRE_PENDING = "#6CC6F2"

MESSAGE_TEXT = "#E8B04A"
TOOLTIP_TEXT = "#EDE8D8"
TOOLTIP_BACKGROUND = "#1A1A1A"

FONT_FAMILY = "Courier New"
TITLE_FONT_PX = 16                        # bold
LABEL_FONT_PX = 12
CHAR_WIDTH = 0.6                          # width of a character of the (monospaced) font, in ems: layout does not need a Tk font to measure

KNOB_PILL_FILL = "#4A4A4A"                # the holder of an inlet's knob, to the left of the node
KNOB_PILL_OUTLINE = "#000000"
KNOB_DIAL_FILL = "#2B2B2B"
KNOB_DIAL_OUTLINE = "#C8C8C8"
KNOB_TICK = "#FFFFFF"
KNOB_TRANSLUCENT = 0.4                    # how opaque every knob is while a wire is dragged (the colours are blended with the background)

WIDGET_FILL = "#505050"                   # buttons
WIDGET_FILL_PRESSED = "#808080"
WIDGET_OUTLINE = "#1E1E1E"
WIDGET_TEXT = "#EDE8D8"
FIELD_FILL = "#2E2E2E"                    # the box of a text or choice widget
FIELD_OUTLINE = "#1E1E1E"

NODE_MIN_WIDTH = 140
NODE_PADDING = 14                         # either side of the title
BAR_HEIGHT = 28                           # the title bar (coloured on a third-party node, plain on a built-in one)
TITLE_TEXT_X = 10                         # the title's left edge, from the node's
TITLE_RULE_INSET = 12                     # the line under a built-in title stops this far from each edge of the node
ROW_HEIGHT = 30                           # body height per port row
BODY_MIN_ROWS = 2
CORNER_RADIUS = 8
OUTLINE_WIDTH = 2
PORT_RADIUS = 9                           # half the diagonal of a port's diamond

KNOB_RADIUS = 10
KNOB_PILL_WIDTH = 40
KNOB_PILL_HEIGHT = 26
KNOB_GAP = 15                             # from the node's left edge to the right end of the knob's pill (clear of the port's hit radius at zoom 1)
KNOB_SWEEP = 135                          # the dial's tick turns this many degrees either side of straight up, for -1 and +1
TICK_MS = 100                             # how often the editor asks an engine for the playback time of its preview nodes
NOTE_GAP = 4                              # between a node and the text it says about itself (an engine's message, the preview's warning) under it
DOUBLE_CLICK_MS = 500                     # two presses this close in time (the events' own times) and ...
DOUBLE_CLICK_PIXELS = 5                   # ... this close in space (in x and in y) are a double click
KNOB_DRAG_PIXELS = 200                   # screen pixels of vertical drag that move a knob across its whole range (-1 to 1)

WIDGET_ROW = 30                           # body height per widget
WIDGET_HEIGHT = 22
WIDGET_INSET = 10                         # a widget's distance from the node's left and right edges
WIDGET_VALUE_CHARS = 14                   # characters of a text or choice widget's value box that fit before it is shortened
WIDGET_LABEL_GAP = 6
PORT_HIT_RADIUS = 14                      # in screen pixels
WIRE_WIDTH = 4
WIRE_SEGMENTS = 28
WIRE_MIN_HANDLE = 60
WIRE_HIT_PX = 6                           # a right click this close (screen pixels) to a wire is on it

ZOOM_MIN = 0.2
ZOOM_MAX = 4.0
ZOOM_STEP = 1.1                           # per wheel notch
SCROLL_STEP = 60                          # screen pixels per wheel notch for Shift and Alt scrolling
MIN_TEXT_PX = 5                           # below this size text is not drawn
FIT_MARGIN = 40
CULL_MARGIN = 60                          # screen pixels around the canvas inside which nodes and wires are still drawn


def blend(colour, over, opacity):
    """`colour` ("#RRGGBB") shown at `opacity` (0 to 1) over the colour `over`: what a translucent item looks like on a plain background (a Tk
    canvas has no transparency, and a knob only ever sits on the background)."""
    a = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(over[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * opacity + y * (1 - opacity)):02X}" for x, y in zip(a, b))
