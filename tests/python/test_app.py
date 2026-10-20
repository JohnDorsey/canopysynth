# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the stand-alone editor of plan step 14 (canopysynth/app.py: `python -m canopysynth`, run_editor.bat): saving and loading a graph as JSON, the File
menu's commands with the dialogs replaced, an engine that follows the window, and the command line. Windows are off-screen and the audio is null."""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk

import canopysynth
from canopysynth import BoundaryError, Graph, GraphError
from canopysynth import app

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sample_graph():
    graph = Graph()
    source = graph.add("boundary_inlet", x=10, y=20, name="level")
    sink = graph.add("boundary_outlet", x=300, y=40, name="out")
    graph.connect(source.outlet("out"), sink.inlet("in"))
    graph.add("file_read", x=5, y=200, path="C:/audio/none.wav")
    sink.set_knob("in", 0.25)
    graph.loop_protection = False
    return graph


@contextlib.contextmanager
def folder():
    with tempfile.TemporaryDirectory() as path:
        yield path


@contextlib.contextmanager
def application(path=None):
    """Yields (the App, the list of errors it showed, the Tk problems): off-screen, null audio, every dialog a recording stub."""
    root = tk.Tk()
    problems = []
    root.report_callback_exception = lambda *details: problems.append(details)
    root.withdraw()
    application = app.App(root, "null", path)
    root.geometry("1000x700+6000+6000")
    root.deiconify()
    errors = []
    application.show_error = errors.append
    application.ask_open = lambda: (_ for _ in ()).throw(AssertionError("no dialog was expected"))
    application.ask_save = lambda initial: (_ for _ in ()).throw(AssertionError("no dialog was expected"))
    application.confirm_discard = lambda: (_ for _ in ()).throw(AssertionError("no question was expected"))
    try:
        root.update()
        yield application, errors, problems
        with contextlib.suppress(tk.TclError):                     # (a test that quits has destroyed the window)
            root.update()
        assert not problems, problems
    finally:
        try:
            if application.engine is not None:
                application.engine.close()
        finally:
            with contextlib.suppress(tk.TclError):
                root.destroy()


def test_py_a_graph_written_to_a_file_and_read_back_is_the_same_graph_and_no_temporary_file_is_left():
    graph = sample_graph()
    with folder() as directory:
        path = os.path.join(directory, "g.json")
        app.write_graph(graph, path)
        assert os.listdir(directory) == ["g.json"], os.listdir(directory)
        with open(path, "rb") as handle:
            raw = handle.read()
        assert b"\r" not in raw and raw.endswith(b"}\n"), raw[-10:]
        assert json.loads(raw) == graph.to_dict()
        back = app.read_graph(path)
        assert back.to_dict() == graph.to_dict()
        assert back.loop_protection is False


def test_py_a_write_that_fails_leaves_the_old_file_as_it_was_and_no_temporary_file():
    graph = sample_graph()
    with folder() as directory:
        path = os.path.join(directory, "g.json")
        app.write_graph(graph, path)
        before = open(path, "rb").read()
        graph.add("file_read")
        os.mkdir(path + ".tmp")                       # the temporary file cannot be made: the write fails before it touches the old file
        try:
            app.write_graph(graph, path)
        except OSError:
            pass
        else:
            raise AssertionError("a write that cannot make its temporary file succeeded")
        assert open(path, "rb").read() == before
        os.rmdir(path + ".tmp")
        try:
            app.write_graph(graph, os.path.join(directory, "missing", "g.json"))
        except OSError:
            pass
        else:
            raise AssertionError("a write into a folder that does not exist succeeded")
        assert os.listdir(directory) == ["g.json"]


def test_py_a_file_that_is_not_a_saved_graph_is_a_graph_error_that_names_the_file_and_a_missing_one_an_os_error():
    with folder() as directory:
        text = os.path.join(directory, "t.json")
        with open(text, "w") as handle:
            handle.write("this is not json")
        wrong = os.path.join(directory, "w.json")
        with open(wrong, "w") as handle:
            json.dump({"format": "something-else"}, handle)
        for path in (text, wrong):
            try:
                app.read_graph(path)
            except GraphError as error:
                if path == text:
                    assert "not JSON" in str(error), str(error)
            else:
                raise AssertionError(f"{path} was read as a graph")
        try:
            app.read_graph(os.path.join(directory, "none.json"))
        except OSError:
            pass
        else:
            raise AssertionError("a file that does not exist was read")


def test_py_the_window_starts_empty_and_untitled_with_an_engine_and_shows_an_edit_in_the_title_until_it_is_saved():
    with application() as (window, errors, _problems), folder() as directory:
        assert window.graph.nodes() == [] and window.path is None and not window.modified
        assert window.root.title() == "CANOPY - untitled"
        assert window.graph.engines() == [window.engine] and not window.engine.closed
        window.editor.add_node("boundary_inlet", 10, 10)
        assert window.modified and window.root.title() == "CANOPY - untitled *"
        path = os.path.join(directory, "mine.json")
        window.ask_save = lambda initial: path if initial == "graph.json" else None
        assert window.save() is True
        assert window.path == path and not window.modified and window.root.title() == "CANOPY - mine.json"
        assert [n["type"] for n in json.load(open(path))["nodes"]] == ["boundary_inlet"]
        window.editor.add_node("file_read", 100, 10)
        assert window.save() is True                               # a graph with a file saves there without asking again
        assert [n["type"] for n in json.load(open(path))["nodes"]] == ["boundary_inlet", "file_read"]
        assert errors == []


def test_py_save_as_that_is_cancelled_saves_nothing_and_leaves_the_graph_modified():
    with application() as (window, errors, _problems):
        window.editor.add_node("file_read", 10, 10)
        window.ask_save = lambda initial: ""
        assert window.save() is False and window.modified and window.path is None and errors == []


def test_py_a_save_that_cannot_be_written_says_so_and_leaves_the_graph_modified():
    with application() as (window, errors, _problems), folder() as directory:
        window.editor.add_node("file_read", 10, 10)
        window.ask_save = lambda initial: os.path.join(directory, "missing", "g.json")
        assert window.save() is False and window.modified and window.path is None
        assert len(errors) == 1 and "could not be saved" in errors[0], errors


def test_py_open_replaces_the_graph_and_the_engine_and_a_bad_file_leaves_both_as_they_were():
    with application() as (window, errors, _problems), folder() as directory:
        good = os.path.join(directory, "good.json")
        app.write_graph(sample_graph(), good)
        old_engine = window.engine
        window.open(good)
        assert window.path == good and not window.modified and old_engine.closed
        assert [b.name for b in window.engine.boundary_nodes()] == ["level", "out"]
        assert window.graph.engines() == [window.engine] and window.editor.graph is window.graph
        graph, engine, editor = window.graph, window.engine, window.editor
        bad = os.path.join(directory, "bad.json")
        with open(bad, "w") as handle:
            handle.write("{")
        window.open(bad)
        window.open(os.path.join(directory, "none.json"))
        assert len(errors) == 2 and all("could not be opened" in e for e in errors), errors
        assert window.graph is graph and window.engine is engine and window.editor is editor and not engine.closed
        assert window.path == good and window.root.title() == "CANOPY - good.json"
        unnamed = Graph()
        unnamed.add("boundary_outlet")                            # (a file written by another program: the engine refuses to compile it)
        refused = os.path.join(directory, "unnamed.json")
        app.write_graph(unnamed, refused)
        window.open(refused)
        assert len(errors) == 3 and window.graph is graph and not engine.closed, errors


def test_py_unsaved_changes_are_asked_about_before_new_open_and_quit_and_declining_changes_nothing():
    with application() as (window, errors, _problems), folder() as directory:
        other = os.path.join(directory, "o.json")
        app.write_graph(Graph(), other)
        window.editor.add_node("file_read", 10, 10)
        asked = []
        window.confirm_discard = lambda: asked.append(1) or False
        graph = window.graph
        window.new()
        window.open(other)
        window.quit()
        assert len(asked) == 3 and window.graph is graph and window.modified and not window.engine.closed
        window.confirm_discard = lambda: asked.append(1) or True
        window.new()
        assert len(asked) == 4 and window.graph is not graph and window.graph.nodes() == [] and not window.modified and graph.engines() == []
        window.ask_open = lambda: other
        window.open()
        assert window.path == other
        window.ask_open = lambda: ""
        window.open()                                              # a cancelled dialog changes nothing
        assert window.path == other and errors == []
        window.quit()                                              # unmodified: no question
        assert len(asked) == 4 and window.engine is None and window.editor is None


def test_py_the_window_opens_a_graph_given_at_the_start_and_its_engine_answers_for_it():
    with folder() as directory:
        path = os.path.join(directory, "g.json")
        app.write_graph(sample_graph(), path)
        with application(path) as (window, _errors, _problems):
            assert window.path == path and window.root.title() == "CANOPY - g.json"
            window.engine.set_boundary("level", 0.5)
            with window.engine.new_instance() as instance:
                assert instance.value("out", 0) == 0.5
            window.root.update()


def test_py_python_dash_m_canopysynth_refuses_a_file_that_is_not_a_graph_with_a_message_and_exit_code_1():
    with folder() as directory:
        path = os.path.join(directory, "bad.json")
        with open(path, "w") as handle:
            handle.write("nonsense")
        result = subprocess.run([sys.executable, "-m", "canopysynth", path, "--audio", "null"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert result.returncode == 1, (result.returncode, result.stderr)
        assert "could not be opened" in result.stderr and "bad.json" in result.stderr, result.stderr
        help_result = subprocess.run([sys.executable, "-m", "canopysynth", "--help"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert help_result.returncode == 0 and "--audio" in help_result.stdout
