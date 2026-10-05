"""How the editor looks: colours and sizes in one place. Sizes are in world units (pixels at zoom 1); the view scales them.

The look follows the author's mock-up (plan step 10): a dark background, grey nodes with a black outline and rounded corners, diamond ports,
blue wires. Built-in nodes (keys without a dot) show their title in off-white text directly on the background above the node; third-party nodes
(keys with a dot) have a coloured title bar, whose colour says whether the node type is realtime safe. The two bar colours are not decided
(the author said to pick a couple): change them here."""

BACKGROUND = "#262626"
NODE_FILL = "#666666"
NODE_OUTLINE = "#000000"
NODE_OUTLINE_SELECTED = "#7FD0FF"

TITLE_TEXT_BUILTIN = "#EDE8D8"            # off-white, on the background
TITLE_BAR_REALTIME_SAFE = "#EFE3B0"       # third-party node types flagged realtime_safe (the cream of the mock-up)
TITLE_BAR_NOT_REALTIME_SAFE = "#EDB48F"   # third-party node types that are not
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

NODE_MIN_WIDTH = 140
NODE_PADDING = 14                         # either side of the title
BAR_HEIGHT = 28                           # the title bar of a third-party node
ROW_HEIGHT = 30                           # body height per port row
BODY_MIN_ROWS = 2
CORNER_RADIUS = 8
OUTLINE_WIDTH = 2
TITLE_GAP = 6                             # between a built-in node's title text and its body
PORT_RADIUS = 9                           # half the diagonal of a port's diamond
PORT_HIT_RADIUS = 14                      # in screen pixels
WIRE_WIDTH = 4
WIRE_SEGMENTS = 28
WIRE_MIN_HANDLE = 60

ZOOM_MIN = 0.2
ZOOM_MAX = 4.0
ZOOM_STEP = 1.1                           # per wheel notch
SCROLL_STEP = 60                          # screen pixels per wheel notch for Shift and Alt scrolling
MIN_TEXT_PX = 5                           # below this size text is not drawn
FIT_MARGIN = 40
CULL_MARGIN = 60                          # screen pixels around the canvas inside which nodes and wires are still drawn
