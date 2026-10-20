# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests (plan step 13): a short run of the Python-level multi-thread stress (tests/python/stress_threads.py: the real editor making random edits while threads
write a boundary inlet, read what it feeds, replace the file node's file and ask the engine what it holds). `dev/stress.py` runs the same for as long as asked."""
import stress_threads


def test_py_the_editor_edits_at_random_while_threads_write_read_and_ask_through_the_public_api_and_every_answer_fits():
    counts = stress_threads.run(seconds=3.0, seed=20261006, readers=3)
    assert counts["writes"] > 100 and counts["reads"] + counts["spans"] > 20 and counts["file_spans"] > 5 and counts["info_calls"] > 5, counts
    assert min(counts["edits_by_kind"].values()) > 0, counts                      # (every kind of edit was made)
    assert counts["file_a"] + counts["file_b"] > 0 and counts["opens"] > 0 and counts["buttons"] > 0, counts
