# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: selecting nodes by dragging a rectangle on the background, and moving the selection together (the author's request after the step 11 try-out),
in a real off-screen window driven with synthetic events, using the helpers of test_editor.py. The sample graph is the one of test_editor.py: file_read at
(0, 40), vendor.safe at (250, 20), boundary_outlet at (500, 40), vendor.slow at (250, 200), boundary_inlet at (0, 250); the view is at scale 1, offset (50, 60)."""
from test_editor import at, hover, items, move, one, press, release, sample, send, window
from canopysynth.editor import geometry as geo
from canopysynth.editor import theme


def selected_outlines(editor, nodes):
    """The IDs of the nodes drawn with the outline of selected ones."""
    return {n.id for n in nodes.values() if editor.canvas.itemcget(one(editor, f"body:{n.id}"), "outline") == theme.NODE_OUTLINE_SELECTED}


def ids(nodes, *keys):
    return {nodes[key].id for key in keys}


def test_py_dragging_on_the_background_draws_a_rectangle_and_selects_the_nodes_it_touches_as_it_grows_and_shrinks():
    with sample() as (editor, graph, nodes):
        kinds = []
        editor.add_listener(kinds.append)
        order = [b.node_id for b in editor.layout()]
        press(editor, 20, 60)                                                              # world (-30, 0): nothing there
        assert editor._drag[0] == "marquee" and editor.selection == frozenset()
        move(editor, 470, 220)                                                             # world (420, 160): touches the file node and vendor.safe, not vendor.slow (y 200)
        assert editor.selection == ids(nodes, "file", "safe") and editor.selected is None
        coords = editor.canvas.coords(one(editor, "marquee"))
        assert coords == [20, 60, 470, 220] and editor.canvas.itemcget(one(editor, "marquee"), "outline") == theme.NODE_OUTLINE_SELECTED
        assert editor.canvas.itemcget(one(editor, "marquee"), "dash") != ""
        assert selected_outlines(editor, nodes) == ids(nodes, "file", "safe")              # and they are drawn as selected
        move(editor, 150, 100)                                                             # smaller: it lets go of vendor.safe
        assert editor.selection == ids(nodes, "file") and editor.selected == nodes["file"].id
        move(editor, 20, 60)
        assert editor.selection == frozenset() and items(editor, "marquee") != ()
        move(editor, 700, 450)                                                             # the whole window
        assert editor.selection == ids(nodes, "file", "safe", "out", "slow", "level")
        release(editor, 700, 450)
        assert editor._drag is None and items(editor, "marquee") == ()                     # the rectangle goes, the selection stays
        assert editor.selection == ids(nodes, "file", "safe", "out", "slow", "level") and selected_outlines(editor, nodes) == editor.selection
        assert kinds == [] and [b.node_id for b in editor.layout()] == order               # selecting is no edit, and moves nothing to the front


def test_py_a_rectangle_may_be_dragged_from_any_corner_and_only_bodies_count_not_knobs_or_ports():
    with sample() as (editor, graph, nodes):
        press(editor, 650, 430)                                                            # world (600, 370), nothing there
        move(editor, 300, 100)                                                             # up and to the left: world (250, 40)
        release(editor, 300, 100)
        assert editor.selection == ids(nodes, "safe", "out", "slow")
        press(editor, 230, 100)                                                            # world (180, 40), left of vendor.safe's knobs
        move(editor, 290, 160)                                                             # to world (240, 100): over the pill of its knob b (195..235 x 80..106), short of its body
        assert editor.selection == frozenset()
        release(editor, 290, 160)
        press(editor, 445, 100)                                                            # world (395, 40): right of vendor.safe's body (to 390), clear of its ports' reach
        move(editor, 450, 125)                                                             # to world (400, 65): the rectangle covers the outlet at (390, 63), which is not body
        assert editor.selection == frozenset()
        release(editor, 450, 125)


def test_py_a_click_on_the_background_clears_the_selection_and_a_click_on_a_node_selects_it_alone():
    with sample() as (editor, graph, nodes):
        editor.select_nodes(ids(nodes, "file", "safe", "slow"))
        press(editor, 650, 430)
        release(editor, 650, 430)
        assert editor.selection == frozenset() and items(editor, "marquee") == ()
        box = editor.box(nodes["slow"])
        press(editor, *at(editor, box.x + 30, box.y + 8))
        release(editor, *at(editor, box.x + 30, box.y + 8))
        assert editor.selection == ids(nodes, "slow") and editor.selected == nodes["slow"].id and editor.layout()[-1].node_id == nodes["slow"].id


def test_py_dragging_a_selected_node_moves_the_whole_selection_by_the_same_amount_and_tells_the_listeners_quietly():
    with sample() as (editor, graph, nodes):
        kinds, virtual = [], []
        editor.add_listener(kinds.append)
        editor.bind("<<GraphChanged>>", lambda event: virtual.append(1))
        editor.select_nodes(ids(nodes, "file", "safe"))
        before = {key: (n.x, n.y) for key, n in nodes.items()}
        box = editor.box(nodes["safe"])
        start = at(editor, box.x + 40, box.y + 8)
        press(editor, *start)
        assert editor.selection == ids(nodes, "file", "safe")                              # pressing a member does not narrow the selection
        move(editor, start[0] + 25, start[1] + 10)
        move(editor, start[0] + 40, start[1] + 30)
        assert editor.selection == ids(nodes, "file", "safe")
        release(editor, start[0] + 40, start[1] + 30)
        assert (nodes["file"].x, nodes["file"].y) == (before["file"][0] + 40, before["file"][1] + 30)
        assert (nodes["safe"].x, nodes["safe"].y) == (before["safe"][0] + 40, before["safe"][1] + 30)
        assert all((nodes[k].x, nodes[k].y) == before[k] for k in ("out", "slow", "level"))
        assert editor.selection == ids(nodes, "file", "safe") and kinds == ["moved", "moved"] and virtual == []
        editor.view = geo.View(2.0, 50.0, 60.0)                                            # at zoom 2 a pixel is half a unit, for every node of the group
        editor.redraw()
        box = editor.box(nodes["file"])
        start = at(editor, box.x + 40, box.y + 8)
        press(editor, *start)
        move(editor, start[0] + 60, start[1] - 20)
        release(editor, start[0] + 60, start[1] - 20)
        assert (nodes["file"].x, nodes["file"].y) == (before["file"][0] + 70, before["file"][1] + 20)
        assert (nodes["safe"].x, nodes["safe"].y) == (before["safe"][0] + 70, before["safe"][1] + 20)


def test_py_dragging_a_node_that_is_not_in_the_selection_selects_and_moves_only_that_node():
    with sample() as (editor, graph, nodes):
        editor.select_nodes(ids(nodes, "file", "safe"))
        before = {key: (n.x, n.y) for key, n in nodes.items()}
        box = editor.box(nodes["slow"])
        start = at(editor, box.x + 30, box.y + 8)
        press(editor, *start)
        move(editor, start[0] + 10, start[1] + 5)
        release(editor, start[0] + 10, start[1] + 5)
        assert editor.selection == ids(nodes, "slow") and (nodes["slow"].x, nodes["slow"].y) == (before["slow"][0] + 10, before["slow"][1] + 5)
        assert all((nodes[k].x, nodes[k].y) == before[k] for k in ("file", "safe", "out", "level"))


def test_py_a_click_on_a_node_of_the_selection_without_a_drag_leaves_just_that_node_selected():
    with sample() as (editor, graph, nodes):
        editor.select_nodes(ids(nodes, "file", "safe", "out"))
        box = editor.box(nodes["safe"])
        spot = at(editor, box.x + 40, box.y + 8)
        press(editor, *spot)
        assert editor.selection == ids(nodes, "file", "safe", "out")                       # still the whole group while the button is down
        release(editor, *spot)
        assert editor.selection == ids(nodes, "safe") and editor.layout()[-1].node_id == nodes["safe"].id
        assert (nodes["safe"].x, nodes["safe"].y) == (250, 20)
        editor.select_nodes(ids(nodes, "file", "safe"))                                    # and a group of two as well
        box = editor.box(nodes["file"])
        spot = at(editor, box.x + 40, box.y + 8)
        press(editor, *spot)
        release(editor, *spot)
        assert editor.selection == ids(nodes, "file")


def test_py_pressing_a_knob_or_a_widget_or_right_clicking_a_node_selects_just_that_node():
    with sample() as (editor, graph, nodes):
        shown = []
        editor._popup = lambda menu, x_root, y_root: shown.append(menu)
        box = editor.box(nodes["safe"])
        knob = box.knob("b")
        editor.select_nodes(ids(nodes, "file", "safe", "out"))
        press(editor, *at(editor, knob.cx, knob.cy))
        release(editor, *at(editor, knob.cx, knob.cy))
        assert editor.selection == ids(nodes, "safe")
        editor.select_nodes(ids(nodes, "file", "safe", "out"))
        out_box = editor.box(nodes["out"])
        press(editor, *at(editor, out_box.widgets[0].x + 10, out_box.widgets[0].y + 10))   # the name box of the boundary node
        release(editor, *at(editor, out_box.widgets[0].x + 10, out_box.widgets[0].y + 10))
        assert editor.selection == ids(nodes, "out")
        editor._close_entry(False)
        editor.select_nodes(ids(nodes, "file", "safe", "out"))
        slow_box = editor.box(nodes["slow"])                                                # a node that is not in the selection: it is selected alone
        send(editor, "<ButtonPress-3>", *at(editor, slow_box.x + 40, slow_box.y + 8))
        assert editor.selection == ids(nodes, "slow") and len(shown) == 1
        editor.select_nodes(ids(nodes, "file", "safe"))
        send(editor, "<ButtonPress-3>", 650, 430)                                           # a right click on the background leaves the selection alone
        assert editor.selection == ids(nodes, "file", "safe")


def labels(menu):
    return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]


def test_py_right_clicking_a_node_of_a_group_keeps_the_group_and_offers_to_delete_all_of_it_at_once():
    with sample() as (editor, graph, nodes):
        shown, kinds, virtual = [], [], []
        editor._popup = lambda menu, x_root, y_root: shown.append(menu)
        editor.add_listener(kinds.append)
        editor.bind("<<GraphChanged>>", lambda event: virtual.append(1))
        editor.select_nodes(ids(nodes, "file", "safe", "slow"))
        box = editor.box(nodes["safe"])
        send(editor, "<ButtonPress-3>", *at(editor, box.x + 40, box.y + 8))
        assert editor.selection == ids(nodes, "file", "safe", "slow")                       # the group is still selected
        assert labels(shown[-1]) == ["Delete selected"]
        shown[-1].invoke(0)
        assert [n.graph is None for n in nodes.values()] == [True, True, False, True, False]     # file, safe, slow gone; out and level stay
        assert sorted(n.id for n in graph.nodes()) == sorted([nodes["out"].id, nodes["level"].id])
        assert graph.connections() == [] and editor.selection == frozenset()
        assert kinds == ["removed"] and virtual == [1]                                      # one event for the whole deletion
        assert editor.last_edit.kind == "removed" and set(editor.last_edit.node_ids) == ids(nodes, "file", "safe", "slow")
        editor.redraw()
        assert len(items(editor, "body")) == 2


def test_py_the_menu_of_a_group_member_keeps_the_nodes_own_items_and_a_lone_selected_node_still_has_a_plain_delete():
    with sample() as (editor, graph, nodes):
        shown = []
        editor._popup = lambda menu, x_root, y_root: shown.append(menu)
        editor.select_nodes(ids(nodes, "out", "level"))                                     # two boundary nodes
        box = editor.box(nodes["out"])
        send(editor, "<ButtonPress-3>", *at(editor, box.x + 40, box.y + 8))
        assert labels(shown[-1]) == ["Delete selected", "Rename..."]
        shown[-1].invoke(1)                                                                  # Rename... is for the node right-clicked
        assert editor._entry is not None and editor._entry[0].get() == "out"
        editor._close_entry(False)
        editor.select(nodes["out"].id)                                                       # one selected node: the plain item, deleting just it
        send(editor, "<ButtonPress-3>", *at(editor, box.x + 40, box.y + 8))
        assert labels(shown[-1]) == ["Delete", "Rename..."] and editor.selection == ids(nodes, "out")
        editor.select_nodes(ids(nodes, "file", "safe"))                                      # a node outside the group: selected alone, plain Delete
        slow_box = editor.box(nodes["slow"])
        send(editor, "<ButtonPress-3>", *at(editor, slow_box.x + 40, slow_box.y + 8))
        assert editor.selection == ids(nodes, "slow") and labels(shown[-1]) == ["Delete"]
        shown[-1].invoke(0)
        assert nodes["slow"].graph is None and nodes["file"].graph is graph and nodes["safe"].graph is graph


def test_py_the_selection_api_select_nodes_ignores_unknown_ids_selected_means_exactly_one_and_removed_nodes_leave_the_selection():
    with sample() as (editor, graph, nodes):
        assert editor.selection == frozenset() and editor.selected is None
        order = [b.node_id for b in editor.layout()]
        editor.select_nodes([nodes["file"].id, nodes["slow"].id, 999])
        assert editor.selection == ids(nodes, "file", "slow") and editor.selected is None
        assert [b.node_id for b in editor.layout()] == order                               # (select_nodes does not reorder; select does)
        editor.select_nodes([nodes["file"].id])
        assert editor.selected == nodes["file"].id
        editor.select(nodes["safe"].id)
        assert editor.selection == ids(nodes, "safe") and editor.layout()[-1].node_id == nodes["safe"].id
        editor.select(None)
        assert editor.selection == frozenset()
        editor.select_nodes(ids(nodes, "file", "slow", "level"))
        editor.remove_node(nodes["slow"])
        assert editor.selection == ids(nodes, "file", "level")
        graph.remove(nodes["file"])                                                        # removed behind the editor's back
        editor.redraw()
        assert editor.selection == ids(nodes, "level") and editor.selected == nodes["level"].id
        assert isinstance(editor.selection, frozenset)
        editor.set_graph(type(graph)(types=graph.types))
        assert editor.selection == frozenset()                                             # another graph: nothing is selected, even if its IDs match


def test_py_a_new_connection_hides_the_knob_of_its_inlet_at_once_and_removing_it_brings_the_knob_back():
    with sample() as (editor, graph, nodes):
        assert items(editor, f"knob:{nodes['slow'].id}:in") != ()
        start, end = at(editor, *[(p.x, p.y) for p in [editor.box(nodes["safe"]).port("outlet", "out")]][0]), None
        port = editor.box(nodes["slow"]).port("inlet", "in")
        end = at(editor, port.x, port.y)
        press(editor, *start)
        move(editor, end[0], end[1])
        release(editor, *end)
        assert graph.connection_into(nodes["slow"].inlet("in")) is not None
        assert items(editor, f"knob:{nodes['slow'].id}:in") == () and items(editor, f"dial:{nodes['slow'].id}:in") == ()
        hover(editor, end[0] - 35, end[1])
        assert items(editor, "tooltip") == ()                                              # nothing under the pointer where the knob was
        editor.disconnect(nodes["slow"].inlet("in"))
        editor.redraw()
        one(editor, f"knob:{nodes['slow'].id}:in")
