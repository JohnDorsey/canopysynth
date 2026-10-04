"""Tests: the realtime preview node through ctypes, as the editor of plan step 12 and a host will call it: the list of audio devices, Play and
Pause as actions, the playback time, the warning, the node's message, all on miniaudio's null backend (no sound hardware needed). The C tests
(tests/c/test_preview.c) check the mixing and the timing against exact references; here the calls cross the DLL's boundary, and a node written
in Python is run by the audio thread itself, which shows that the callback asks for consecutive frames and that Python can be in the audio path
(the warning says it should not be)."""
import ctypes
import threading
import time

import engine_dll as e
from engine_dll import PyNodeType, Rig

PREVIEW = 50
WARNING = "not realtime safe, so the sound may break up: "


def ns(frame):
    """The time of a frame of 48000 Hz in nanoseconds, rounded half up (big integers: exact)."""
    return (frame * 1_000_000_000 + 24_000) // 48_000


def read_text(function, *args):
    """Calls function(*args, buffer, capacity, length) the way a caller must: once for the length, once for the text."""
    length = e.i32()
    assert function(*args, None, 0, ctypes.byref(length)) == e.OK
    buffer = ctypes.create_string_buffer(length.value + 1)
    assert function(*args, buffer, length.value + 1, ctypes.byref(length)) == e.OK
    return buffer.value.decode()


def message(rig, node=PREVIEW):
    return read_text(e.engine_node_message, rig.engine, node)


def devices(rig):
    return read_text(e.engine_audio_devices, rig.engine)


def warning(rig, node=PREVIEW):
    return read_text(e.preview_warning, rig.engine, node)


def state(rig, node=PREVIEW):
    """(status, playing, time in ns)."""
    playing, t = e.i32(), e.i64()
    status = e.preview_state(rig.engine, node, ctypes.byref(playing), ctypes.byref(t))
    return status, playing.value, t.value


def wait_for(condition, what, seconds=5.0):
    """Waits for something the audio thread does (only a failing run reaches the limit)."""
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.002)


def settle(rig, quiet=0.1):
    """Waits until the playback time has not changed for `quiet` seconds (a callback that was running when Pause was pressed may still add its
    chunk) and returns it."""
    deadline = time.monotonic() + 5.0
    last, since = state(rig)[2], time.monotonic()
    while time.monotonic() - since < quiet:
        assert time.monotonic() < deadline, "the time never stood still"
        time.sleep(0.005)
        now = state(rig)[2]
        if now != last:
            last, since = now, time.monotonic()
    return last


def preview_rig(*types, device=None):
    """A rig on the null backend with a preview node (50) whose left inlet is fed by a boundary inlet 'level' (node 1)."""
    rig = Rig(*types)
    assert e.engine_set_audio_backend(rig.engine, e.AUDIO_NULL) == e.OK
    rig.node(1, "boundary_inlet")
    rig.node(PREVIEW, "realtime_preview")
    assert e.graph_set_string(rig.graph, 1, b"name", b"level") == e.OK
    if device is not None:
        assert e.graph_set_string(rig.graph, PREVIEW, b"device", device) == e.OK
    rig.connect(1, "out", PREVIEW, "left")
    rig.install()
    return rig


def test_py_the_audio_backend_and_the_list_of_devices_are_asked_through_the_dll_with_the_two_call_protocol():
    rig = Rig()
    live = e.alloc_live()
    assert e.engine_set_audio_backend(rig.engine, e.AUDIO_NULL) == e.OK
    assert devices(rig) == "NULL Playback Device"
    length, cut = e.i32(), ctypes.create_string_buffer(5)
    assert e.engine_audio_devices(rig.engine, cut, 5, ctypes.byref(length)) == e.OK
    assert cut.value == b"NULL" and length.value == len("NULL Playback Device")                  # cut to the capacity, with the full length
    assert e.engine_set_audio_backend(rig.engine, 7) == e.ERR_ARGUMENT
    assert e.engine_set_audio_backend(rig.engine, -1) == e.ERR_ARGUMENT
    assert e.engine_set_audio_backend(None, e.AUDIO_NULL) == e.ERR_ARGUMENT
    assert e.engine_audio_devices(None, cut, 5, ctypes.byref(length)) == e.ERR_ARGUMENT
    assert e.engine_audio_devices(rig.engine, cut, -1, ctypes.byref(length)) == e.ERR_ARGUMENT
    assert e.engine_audio_devices(rig.engine, None, 4, ctypes.byref(length)) == e.ERR_ARGUMENT
    assert e.engine_set_audio_backend(rig.engine, e.AUDIO_SYSTEM) == e.OK
    system = devices(rig)                                                                       # the real system: whatever the machine has, one name per line
    assert "\r" not in system and "NULL Playback Device" not in system                         # (the null backend's device is not one of the machine's)
    assert e.alloc_live() == live
    rig.close()


def test_py_play_and_pause_are_actions_and_the_time_moves_only_while_playing_and_can_be_typed():
    live = e.alloc_live()
    rig = preview_rig()
    assert state(rig) == (e.OK, 0, 0)
    assert e.engine_action(rig.engine, PREVIEW, b"play") == e.OK
    assert state(rig)[1] == 1
    wait_for(lambda: state(rig)[2] >= 100_000_000, "100 ms of audio")
    assert message(rig) == ""
    assert e.engine_action(rig.engine, PREVIEW, b"pause") == e.OK
    assert state(rig)[1] == 0
    stopped_at = settle(rig)
    time.sleep(0.15)                                                                            # the device goes on, with silence; the time does not
    assert state(rig)[2] == stopped_at
    assert e.engine_action(rig.engine, PREVIEW, b"play") == e.OK
    wait_for(lambda: state(rig)[2] >= stopped_at + 60_000_000, "play to go on from where it was paused")
    assert state(rig)[2] < stopped_at + 4_000_000_000
    assert e.preview_set_time(rig.engine, PREVIEW, 7_000_000_000) == e.OK                       # typed while playing
    wait_for(lambda: state(rig)[2] >= 7_020_000_000, "the time to go on from the typed time")
    assert state(rig)[2] < 11_000_000_000
    assert e.engine_action(rig.engine, PREVIEW, b"pause") == e.OK
    settle(rig)
    assert e.preview_set_time(rig.engine, PREVIEW, 3_723_004_000_000) == e.OK                   # 01:02:03.004, typed while paused
    assert state(rig) == (e.OK, 0, 3_723_004_000_000)
    assert e.preview_set_time(rig.engine, PREVIEW, -1_500_000_000) == e.OK                      # negative times are legal
    assert state(rig) == (e.OK, 0, -1_500_000_000)
    rig.close()                                                                                 # the engine closes the device
    assert e.alloc_live() == live


def test_py_a_node_written_in_python_is_run_by_the_audio_thread_and_is_asked_for_consecutive_frames():
    live = e.alloc_live()
    asked = []                                                                                  # (t0, t1, n, thread) of every span the preview asks for

    def span(ctx, outlet, t0, t1, n, out):
        asked.append((t0, t1, n, threading.get_ident()))
        for i in range(n):
            out[i] = 0.25
        return e.OK

    rig = Rig(PyNodeType("py.source", span=span))
    assert e.engine_set_audio_backend(rig.engine, e.AUDIO_NULL) == e.OK
    rig.node(1, "py.source")
    rig.node(PREVIEW, "realtime_preview")
    rig.connect(1, "out", PREVIEW, "left")
    rig.install()
    assert warning(rig) == WARNING + "py.source (node 1)"                                       # a Python node is not realtime safe: the preview says so
    assert e.engine_action(rig.engine, PREVIEW, b"play") == e.OK
    wait_for(lambda: len(asked) >= 8, "eight callbacks")
    assert e.engine_action(rig.engine, PREVIEW, b"pause") == e.OK
    settle(rig)
    rig.close()                                                                                 # (stops a device whose thread may be inside the Python node)
    frame = 0
    for t0, t1, n, thread in asked:
        assert 0 < n <= e.MAX_N
        assert (t0, t1) == (ns(frame), ns(frame + n)), (frame, n, t0, t1)                        # each span starts where the one before ended
        assert thread != threading.get_ident()                                                  # the audio thread ran the node, not this one
        frame += n
    assert e.alloc_live() == live


def test_py_a_device_that_does_not_exist_falls_back_to_the_default_and_the_node_says_so():
    rig = preview_rig(device=b"No such device")
    assert e.engine_action(rig.engine, PREVIEW, b"play") == e.OK
    assert state(rig)[1] == 1
    assert "No such device" in message(rig) and "system default" in message(rig)
    wait_for(lambda: state(rig)[2] >= 40_000_000, "the node to play on the default device")
    assert "No such device" not in devices(rig)
    rig.close()


def test_py_the_warning_lists_the_nodes_that_feed_the_preview_and_are_not_realtime_safe_and_follows_edits():
    rig = Rig(PyNodeType("py.slow", inlets=[("in", 0.0)], at=lambda ctx, outlet, t: 0.0),
              PyNodeType("py.unrelated", at=lambda ctx, outlet, t: 0.0))
    rig.node(1, "boundary_inlet")
    rig.node(2, "py.slow")
    rig.node(3, "py.unrelated")                                                                 # connected to nothing
    rig.node(PREVIEW, "realtime_preview")
    assert e.graph_set_string(rig.graph, 1, b"name", b"x") == e.OK
    rig.connect(1, "out", 2, "in")
    rig.install()
    assert warning(rig) == ""                                                                   # nothing slow feeds the preview yet
    rig.connect(2, "out", PREVIEW, "center")
    rig.update()                                                                                # an edit: the next call to the warning sees it
    assert warning(rig) == WARNING + "py.slow (node 2)"
    length, cut = e.i32(), ctypes.create_string_buffer(8)
    assert e.preview_warning(rig.engine, PREVIEW, cut, 8, ctypes.byref(length)) == e.OK
    assert cut.value == (WARNING)[:7].encode() and length.value == len(WARNING + "py.slow (node 2)")
    rig.close()


def test_py_the_exported_preview_calls_give_the_documented_statuses_for_other_nodes_and_bad_arguments():
    rig = preview_rig()
    playing, t, length, text = e.i32(), e.i64(), e.i32(), ctypes.create_string_buffer(16)
    for node, status in ((999, e.ERR_NODE), (1, e.ERR_ARGUMENT)):                               # no such node; a node that is not a preview node
        assert e.preview_state(rig.engine, node, ctypes.byref(playing), ctypes.byref(t)) == status
        assert e.preview_set_time(rig.engine, node, 0) == status
        assert e.preview_warning(rig.engine, node, text, 16, ctypes.byref(length)) == status
    assert e.preview_state(None, PREVIEW, ctypes.byref(playing), ctypes.byref(t)) == e.ERR_ARGUMENT
    assert e.preview_set_time(None, PREVIEW, 0) == e.ERR_ARGUMENT
    assert e.preview_warning(None, PREVIEW, text, 16, ctypes.byref(length)) == e.ERR_ARGUMENT
    assert e.preview_state(rig.engine, PREVIEW, None, None) == e.OK                             # both outputs are optional
    assert e.preview_warning(rig.engine, PREVIEW, None, 4, ctypes.byref(length)) == e.ERR_ARGUMENT
    assert e.preview_warning(rig.engine, PREVIEW, text, -1, ctypes.byref(length)) == e.ERR_ARGUMENT
    assert e.engine_action(rig.engine, 999, b"play") == e.ERR_NODE
    assert e.engine_action(rig.engine, 1, b"play") == e.OK                                      # a node without such a button ignores it
    rig.close()
