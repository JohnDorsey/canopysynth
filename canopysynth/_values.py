"""Checks of the plain values a graph holds: settings, knob positions, canvas positions. Every function returns the value to store or raises
GraphError naming `where` (for example "node 3 (file_read)"). What is stored is always JSON-safe (int, float, str), so that to_dict() can be
written to a file as it is, and always something the engine accepts when it compiles the graph (the checks mirror those of
src/canopy_engine.c: a test compiles graphs made here in a real engine)."""
import math

from .errors import GraphError
from ._descriptor import INTERNAL_RATE_KEY, INTERNAL_RATE_MAX, INTERNAL_RATE_MIN

INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1


def is_absolute_path(path):
    """True for a Windows drive path ("C:/x.wav", "C:\\x.wav") or a network path ("\\\\host\\share", "//host/share"). Version 1 has no relative
    paths (design section 14): "x.wav", "\\x.wav" (rooted on the current drive) and "C:x.wav" (relative to the current folder of drive C) are
    not absolute. src/canopy_fileread.c makes the same distinction when "open" is pressed; a test compares the two on a list of paths."""
    if len(path) >= 3 and path[0].isascii() and path[0].isalpha() and path[1] == ":" and path[2] in "\\/":
        return True
    return len(path) >= 2 and path[0] in "\\/" and path[1] in "\\/"


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)          # (bool is a subclass of int: True is not a number here)


def text(value, where, what):
    """Text that can be handed to C: a str with no NUL character and no lone surrogate."""
    if not isinstance(value, str):
        raise GraphError(f"{where}: {what} must be text, not {value!r}")
    if "\0" in value:
        raise GraphError(f"{where}: {what} must not contain a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise GraphError(f"{where}: {what} is not valid text (a lone surrogate)") from None
    return value


def setting(type_info, key, value, where):
    """The value to store for setting `key` of a node of `type_info`: GraphError for an unknown key or a value of the wrong kind or range."""
    desc = type_info.setting.get(key) if isinstance(key, str) else None
    if desc is None:
        known = ", ".join(repr(s["key"]) for s in type_info.settings) or "none"
        raise GraphError(f"{where} has no setting {key!r} (its settings: {known})")
    kind, what = desc["kind"], f"the setting {key!r}"
    if kind == "int":
        if not is_int(value):
            raise GraphError(f"{where}: {what} must be a whole number, not {value!r}")
        low, high = (INTERNAL_RATE_MIN, INTERNAL_RATE_MAX) if key == INTERNAL_RATE_KEY else (INT64_MIN, INT64_MAX)
        if not low <= value <= high:
            raise GraphError(f"{where}: {what} must be a whole number from {low} to {high}, not {value}")
        return int(value)
    if kind == "float":
        if not is_number(value):
            raise GraphError(f"{where}: {what} must be a number, not {value!r}")
        try:
            number = float(value)
        except OverflowError:
            raise GraphError(f"{where}: {what} must be a finite number") from None
        if not math.isfinite(number):
            raise GraphError(f"{where}: {what} must be a finite number")
        return number
    if kind == "choice":
        if not isinstance(value, str) or value not in desc["choices"]:
            raise GraphError(f"{where}: {what} must be one of {', '.join(repr(c) for c in desc['choices'])}, not {value!r}")
        return value
    value = text(value, where, what)
    if kind == "path" and value and not is_absolute_path(value):
        raise GraphError(f"{where}: {what} must be an absolute path (version 1 has no relative paths), not {value!r}")
    return value


def knob(inlet_key, value, where):
    """A knob position: a finite number from -1 to 1 (design section 6)."""
    if not is_number(value) or not -1 <= value <= 1:         # (a NaN fails the comparison)
        raise GraphError(f"{where}: the knob of inlet {inlet_key!r} must be a number from -1 to 1, not {value!r}")
    return float(value)


def coordinate(name, value, where):
    """A canvas position: a finite number."""
    try:
        finite = is_number(value) and math.isfinite(value)
    except OverflowError:                                    # an int too big for a float
        finite = False
    if not finite:
        raise GraphError(f"{where}: {name} must be a finite number, not {str(value)[:40]}")
    return value if type(value) in (int, float) else float(value)


def node_id(value, what="a node ID"):
    if not is_int(value) or not INT64_MIN <= value <= INT64_MAX:
        raise GraphError(f"{what} must be a whole number that fits in 64 bits, not {value!r}")
    return int(value)
