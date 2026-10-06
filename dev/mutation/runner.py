"""The mutations of the two runners themselves (the changes that make mutation campaigns fast: run_tests.py's --fail-fast, --no-c, --record-times and
--order-by-times, and mutate.py's fast order, its check of that order, its rebuild after a mutation of a C file): run with
    python dev/mutation/mutate.py dev/mutation/runner.py
Every one of them should be reported as caught; see mutate.py. (T is run_tests.py, M is dev/mutation/mutate.py: both are Python files, so the runner
skips the build and the extra C runs, and AREAS limits the tests to tests/python/test_runner.py.) Run it in a copy of the project, as every campaign is run:
it breaks the very files the other campaigns run. The runner treats the mutations of run_tests.py (the R ones) specially, on purpose: it runs them the
thorough way, because the fast flags are part of what they break (R07 below once looked like a survivor for that reason: the run that judged it stopped
after one passing test)."""
T = "run_tests.py"
M = "dev/mutation/mutate.py"

AREAS = ["runner"]

MUTATIONS = [
    # ---- run_tests.py: --no-c and --fail-fast ----
    ("R01 --no-c is ignored", T, 'passed, failed = (0, 0) if "--no-c" in options else run_c_tests(', 'passed, failed = run_c_tests('),
    ("R02 --no-c has the opposite meaning", T, '(0, 0) if "--no-c" in options else', '(0, 0) if "--no-c" not in options else'),
    ("R03 the C phases are never told to stop at a failure", T, '"--no-asan" not in options, fail_fast)', '"--no-asan" not in options, False)'),
    ("R04 a failing C run does not stop the Python tests", T, "    stopped = fail_fast and failed > 0", "    stopped = False"),
    ("R05 the Python tests start after a failing C run", T, "    for name, fn in [] if stopped else python_tests(areas, contains, times):", "    for name, fn in python_tests(areas, contains, times):"),
    ("R06 a failing Python test never stops the run", T, "        if fail_fast and failed:\n            stopped = True", "        if False:\n            stopped = True"),
    ("R07 the run stops after any test", T, "        if fail_fast and failed:\n            stopped = True", "        if fail_fast:\n            stopped = True"),
    ("R08 the run stops at the second failure", T, "        if fail_fast and failed:\n            stopped = True", "        if fail_fast and failed > 1:\n            stopped = True"),
    ("R09 the run does not say it stopped early", T, '    if stopped:\n        print("(stopped at the first failure', '    if False:\n        print("(stopped at the first failure'),
    ("R10 --fail-fast is not the flag it is called", T, '    fail_fast = "--fail-fast" in options', '    fail_fast = "--failfast" in options'),
    ("R11 the debug-heap run happens after a failure", T, "    if with_debug and not (fail_fast and failed):", "    if with_debug:"),
    ("R12 the sanitizer run happens after a failure", T, "    if with_asan and not (fail_fast and failed):", "    if with_asan:"),
    ("R13 a leak in the debug-heap run is not a failure", T, "            failed += debug_failed + (1 if leaked else 0)", "            failed += debug_failed"),
    # ---- run_tests.py: times ----
    ("R14 --record-times records nothing", T, '    if "--record-times" in options:\n        write_times(', '    if False:\n        write_times('),
    ("R15 a time is rounded to whole seconds", T, "        measured[name] = time.perf_counter() - started", "        measured[name] = round(time.perf_counter() - started)"),
    ("R16 a time is kept under the wrong name", T, "        measured[name] = time.perf_counter() - started", '        measured[name + "x"] = time.perf_counter() - started'),
    ("R17 the times are written over the old file with a rename", T, "    os.replace(temporary, path)", "    os.rename(temporary, path)"),
    ("R18 the dearest test runs first", T, "chosen.sort(key=lambda item: times.get(item[0], -1.0))", "chosen.sort(key=lambda item: -times.get(item[0], -1.0))"),
    ("R19 a test with no time runs last", T, "chosen.sort(key=lambda item: times.get(item[0], -1.0))", "chosen.sort(key=lambda item: times.get(item[0], 1e9))"),
    ("R20 the times are not used to order the tests", T, "    if times is not None:\n        chosen.sort(", "    if False:\n        chosen.sort("),
    ("R21 the times file is not read", T, '    times = read_times(options["--order-by-times"]) if "--order-by-times" in options else None', "    times = None"),
    ("R22 a times file that is missing is taken as empty", T, "    except (OSError, ValueError) as error:", "    except ValueError as error:"),
    ("R23 a times file of the wrong shape is used", T, "        if not isinstance(times, dict) or not all(isinstance(seconds, (int, float)) for seconds in times.values()):", "        if False:"),
    ("R24 the sentence about the times file is lost", T, '        raise SystemExit(f"cannot use the times file {path}: {error}")', '        raise SystemExit(f"{error}")'),
    # ---- run_tests.py: the command line ----
    ("R25 the tests come in reverse name order", T, "for n, f in sorted(tests.items()) if not contains", "for n, f in sorted(tests.items(), reverse=True) if not contains"),
    ("R26 a test needs all the -k texts", T, "if not contains or any(c in n for c in contains)]", "if not contains or all(c in n for c in contains)]"),
    ("R27 the text after -k is taken for a test file too", T, "            contains.append(argv[index + 1])\n            index += 2", "            contains.append(argv[index + 1])\n            index += 1"),
    ("R28 the file after --record-times is taken for a test file", T, "            options[argument] = argv[index + 1]\n            index += 2", "            options[argument] = argv[index + 1]\n            index += 1"),
    ("R29 a flag takes the word after it with it", T, "            options[argument] = True\n            index += 1", "            options[argument] = True\n            index += 2"),
    ("R30 an option with no file name crashes", T, "            if index + 1 >= len(argv):\n                raise SystemExit", "            if False:\n                raise SystemExit"),
    ("R31 a -k with no text crashes", T, '        if argument == "-k" and index + 1 < len(argv):', '        if argument == "-k":'),
    ("R32 the build is always made", T, '    if "--no-build" not in options:\n        build()', "    if True:\n        build()"),
    # ---- mutate.py: asking for a run ----
    ("M01 a fast run for a Python file still builds", M, '["--no-build", "--no-c"] if times is not None', '["--no-c"] if times is not None'),
    ("M02 a fast run for a Python file still runs the C tests", M, '["--no-build", "--no-c"] if times is not None', '["--no-build"] if times is not None'),
    ("M03 a thorough run for a Python file runs the sanitizer", M, 'else ["--no-build", "--no-debug", "--no-asan"]', 'else ["--no-build", "--no-debug"]'),
    ("M04 a run for a Python file runs every test file", M, "        command += list(areas or [])", "        command += []"),
    ("M05 a fast run does not stop at the first failure", M, '        command += ["--fail-fast", "--order-by-times", times]', '        command += ["--order-by-times", times]'),
    ("M06 a fast run does not use the order", M, '        command += ["--fail-fast", "--order-by-times", times]', '        command += ["--fail-fast"]'),
    ("M07 the first run does not record the times", M, '        command += ["--record-times", record]', "        command += []"),
    ("M08 a fast run for a Python file is a run for a C file", M, "    if python_only:\n        command += list(areas or [])", "    if python_only and times is None:\n        command += list(areas or [])"),
    # ---- mutate.py: reading the result ----
    ("M09 a failed build is not seen when it says so in lower case", M, 'if "the build failed" in out or "Build failed" in out:', 'if "Build failed" in out:'),
    ("M10 a program that did not finish is not a detection by itself", M, '    if "did not finish" in out:', "    if False:"),
    ("M11 a green run is a detection", M, 'summary[-1][1] != "0")', 'summary[-1][1] == "0")'),
    ("M12 a run with no total is not a detection", M, "    if not summary:", "    if False:"),
    # ---- mutate.py: the campaign ----
    ("M13 the rebuild is made with the user's profile", M, '["powershell", "-NoProfile", "-ExecutionPolicy"', '["powershell", "-ExecutionPolicy"'),
    ("M14 a rebuild that fails goes unnoticed", M, '    if result.returncode != 0:\n        raise SystemExit("the build after', '    if False:\n        raise SystemExit("the build after'),
    ("M15 a run for a C file uses the Python files of AREAS", M, '        wanted = areas if path.endswith(".py") else None', "        wanted = areas"),
    ("M16 the same fast order is checked again for every mutation", M, "        if wanted not in kinds:", "        if True:"),
    ("M17 --thorough is not seen", M, '    thorough = "--thorough" in argv', "    thorough = False"),
    ("M18 --thorough is taken for the name of a mutation", M, '    argv = [a for a in argv if a != "--thorough"]', "    argv = argv"),
    ("M19 the fast order is never run before mutating", M, '            for areas in python_runs(mutations, namespace.get("AREAS")):', "            for areas in []:"),
    ("M20 a fast order that fails does not stop the campaign", M, '                    raise SystemExit("the suite must be green in the fast order too before mutating")', "                    pass"),
    ("M21 a whole suite that fails does not stop the campaign", M, '            raise SystemExit("the suite must be green before mutating")', "            pass"),
    ("M22 the DLL is never built again after a C mutation", M, "            if python_file and dll_mutated:", "            if False:"),
    ("M23 the DLL is built again before every Python mutation", M, "            if python_file and dll_mutated:", "            if python_file:"),
    ("M24 the DLL stays marked as mutated after it was built again", M, "                rebuild()\n                dll_mutated = False", "                rebuild()"),
    ("M25 a C mutation does not mark the DLL as mutated", M, "            dll_mutated = dll_mutated or not python_file", "            dll_mutated = False"),
    ("M26 the exit code is always 0", M, '    return 0 if state == "SURVIVED" and all_caught else 1', "    return 0"),
    ("M26b the suite after restoring does not count for the exit code", M, '    return 0 if state == "SURVIVED" and all_caught else 1', "    return 0 if all_caught else 1"),
    ("M26c a survivor does not spoil the exit code", M, 'tally["SURVIVED"] == 0 and tally["BUILD FAILED"] == 0', 'tally["BUILD FAILED"] == 0'),
    ("M26d a build failure does not spoil the exit code", M, 'tally["BUILD FAILED"] == 0 and tally["SKIPPED"] == 0', 'tally["SKIPPED"] == 0'),
    ("M26e a skipped mutation does not spoil the exit code", M, ' and tally["SKIPPED"] == 0', ""),
    ("M27 a file is not put back after its run", M, "            shutil.copy2(backups[full], full)\n            dll_mutated", "            dll_mutated"),
    ("M28 a file is not put back when the campaign fails", M, "        for full, backup in backups.items():\n            shutil.copy2(backup, full)\n            os.remove(backup)", "        for full, backup in backups.items():\n            os.remove(backup)"),
    ("M29 the times file is left behind", M, "                os.remove(leftover)", "                pass"),
    ("M30 a mutation is run without the fast order", M, 'areas=namespace.get("AREAS") if python_file else None, times=fast)', 'areas=namespace.get("AREAS") if python_file else None, times=None)'),
    ("M31 a mutation of a C file is run with AREAS", M, 'areas=namespace.get("AREAS") if python_file else None, times=fast)', 'areas=namespace.get("AREAS"), times=fast)'),
    ("M37 a mutation of run_tests.py is run the fast way", M, 'None if os.path.normpath(path) == "run_tests.py" else times', "times"),
    ("M38 no mutation is run the fast way", M, 'None if os.path.normpath(path) == "run_tests.py" else times', "None"),
    ("M39 a mutation of any file is run the thorough way", M, 'None if os.path.normpath(path) == "run_tests.py" else times', 'None if os.path.normpath(path).endswith(".py") else times'),
    ("M32 a text to replace that is there once is skipped", M, "            if original.count(old) != 1:", "            if original.count(old) != 0:"),
    ("M33 the first run does not record", M, "        state, failed, out = run_suite(record=times)", "        state, failed, out = run_suite()"),
    ("M34 the last run is a fast one", M, '    state, failed, out = run_suite()\n    print("after restoring:"', '    state, failed, out = run_suite(python_only=True)\n    print("after restoring:"'),
    ("M35 the names given are not used to pick mutations", M, '    mutations = [m for m in namespace["MUTATIONS"] if not only or m[0].split()[0] in only]', '    mutations = list(namespace["MUTATIONS"])'),
    ("M36 a times file is made also for a thorough run", M, "    if not thorough:\n        handle, times = tempfile.mkstemp(", "    if True:\n        handle, times = tempfile.mkstemp("),
]
