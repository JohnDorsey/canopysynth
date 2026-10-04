"""The mutations of plan step 9 (the Python bridge: Engine, Instance, the native bindings, QueryError, and the C point read with a status): run with
    python dev/mutation/mutate.py dev/mutation/step9.py
Every one of them should be reported as caught; see mutate.py. (A name starting E is canopysynth/engine.py, N _native.py, X errors.py,
I src/canopy_instance.c. A mutation in a .py file runs only the Python-side suite plus the C tests once; a run that crashes without printing a
total counts as caught. Not mutated, because the tests cannot tell: the exact bounds of n in `Instance.audio` (the C engine refuses the same
values with the same status, the Python check only avoids allocating a huge buffer, which the test with n = 10 ** 12 pins), and the choice of
who frees a registry the caller made.)"""
E = "canopysynth/engine.py"
N = "canopysynth/_native.py"
X = "canopysynth/errors.py"
I = "src/canopy_instance.c"

MUTATIONS = [
    # ---- names and times ----
    ("E01 a name need not be text", E, '    if not isinstance(name, str):\n        raise BoundaryError(f"a boundary name is text', '    if False:\n        raise BoundaryError(f"a boundary name is text'),
    ("E02 a lone surrogate in a name is not handled", E, '    except UnicodeEncodeError:\n        raise BoundaryError("there is no boundary node with that name', '    except ZeroDivisionError:\n        raise BoundaryError("there is no boundary node with that name'),
    ("E03 a NUL in a name is passed on", E, r'    if b"\0" in data:', '    if False:'),
    ("E04 a time has no range", E, 'if not _values.is_int(value) or not native.INT64_MIN <= value <= native.INT64_MAX:', 'if not _values.is_int(value):'),
    ("E05 a time need not be a whole number", E, 'if not _values.is_int(value) or not native.INT64_MIN <= value <= native.INT64_MAX:', 'if not native.INT64_MIN <= value <= native.INT64_MAX:'),
    # ---- describing the graph to the engine ----
    ("E06 out of memory in a description is not noticed", E, '    if status == native.ERR_MEMORY:\n        raise MemoryError("out of memory while describing', '    if False:\n        raise MemoryError("out of memory while describing'),
    ("E07 other faults in a description are not noticed", E, '    if status != native.OK:\n        raise GraphError(native.message(status))\n\n\ndef _describe', '    if False:\n        raise GraphError(native.message(status))\n\n\ndef _describe'),
    ("E08 a choice always goes as index 0", E, 'desc["choices"].index(value)', '0'),
    ("E09 knobs are not described", E, '            _check(lib.canopy_graph_set_knob(c_graph, node.id, inlet["key"].encode("utf-8"), node.knobs[inlet["key"]]))', '            pass'),
    ("E10 connections are not described", E, '    for connection in graph.connections():\n        _check(', '    for connection in []:\n        _check('),
    ("E11 a float setting is described as 0.0", E, '                _check(lib.canopy_graph_set_float(c_graph, node.id, key, value))', '                _check(lib.canopy_graph_set_float(c_graph, node.id, key, 0.0))'),
    ("E12 text goes to the engine in Latin-1", E, 'lib.canopy_graph_set_string(c_graph, node.id, key, value.encode("utf-8"))', 'lib.canopy_graph_set_string(c_graph, node.id, key, value.encode("latin-1", "replace"))'),
    # ---- the engine ----
    ("E13 a failed start does not free what it made", E, '        except BaseException:\n            self.close()\n            raise', '        except BaseException:\n            raise'),
    ("E14 out of memory in set_graph is a graph error", E, '                if status == native.ERR_MEMORY:\n                    raise MemoryError("out of memory while installing the graph")', '                if False:\n                    raise MemoryError("out of memory while installing the graph")'),
    ("E15 the engine's reason is replaced by a sentence", E, '                    raise GraphError(reason.decode("utf-8", "replace") if reason else native.message(status))', '                    raise GraphError(native.message(status))'),
    ("E16 the description is not freed", E, '                lib.canopy_graph_free(c_graph)', '                pass'),
    ("E17 a description that could not be made goes on", E, '            if not c_graph:\n                raise MemoryError("out of memory while describing', '            if False:\n                raise MemoryError("out of memory while describing'),
    ("E18 the boundary list is read once", E, '        for _attempt in range(10):', '        for _attempt in range(1):'),
    ("E19 a long name is cut", E, '                    if length.value < capacity:\n                        break', '                    if True:\n                        break'),
    ("E20 a boundary of the other kind is not said to be", E, '        if other is None:\n            return BoundaryError(f"the graph has no boundary node called', '        if True:\n            return BoundaryError(f"the graph has no boundary node called'),
    ("E45 update does not check the boundary names first", E, '            handle = self._handle()\n            self._graph.validate()\n', '            handle = self._handle()\n'),
    ("E46 a missing boundary name is a graph error", E, '            return BoundaryError(f"the graph has no boundary node called {name!r}")\n        return BoundaryError', '            return GraphError(f"the graph has no boundary node called {name!r}")\n        return BoundaryError'),
    ("E47 another status of a boundary write is a graph error", E, '            raise self._missing(name, "inlet")\n        raise BoundaryError(native.message(status))', '            raise self._missing(name, "inlet")\n        raise GraphError(native.message(status))'),
    ("E21 a boundary value need not be a number", E, '        if not _values.is_number(value):', '        if False:'),
    ("E22 a value too big for a float is not a value error", E, '        except OverflowError:\n            raise ValueError(f"a boundary value must fit', '        except ZeroDivisionError:\n            raise ValueError(f"a boundary value must fit'),
    ("E23 a missing boundary inlet is a generic error", E, '        if status == native.ERR_NODE:\n            raise self._missing(name, "inlet")', '        if False:\n            raise self._missing(name, "inlet")'),
    ("E24 an instance is not counted", E, '            self._instances += 1', '            pass'),
    ("E25 a closed instance is not uncounted", E, '        with self._lock:\n            self._instances -= 1', '        with self._lock:\n            pass'),
    ("E26 the engine closes with open instances", E, '            if self._instances:\n                raise RuntimeError(f"the engine still has', '            if False:\n                raise RuntimeError(f"the engine still has'),
    ("E27 the registry is not freed with the engine", E, '            self._engine = None\n            self._free_registry()', '            self._engine = None'),
    ("E28 a busy engine is closed as if it were not", E, '            if status != native.OK:\n                raise RuntimeError(native.message(status))\n            self._engine = None', '            self._engine = None'),
    ("E29 a closed engine is used", E, '        if self._engine is None:\n            raise RuntimeError("the engine is closed")', '        if False:\n            raise RuntimeError("the engine is closed")'),
    ("E30 an engine dropped without closing is not freed", E, '        try:\n            self.close()\n        except Exception:                                  # noqa: BLE001 - nothing', '        try:\n            pass\n        except Exception:                                  # noqa: BLE001 - nothing'),
    # ---- instances ----
    ("E31 a closed instance is used", E, '        if self._pointer is None:\n            raise RuntimeError("the instance is closed")', '        if False:\n            raise RuntimeError("the instance is closed")'),
    ("E32 a missing boundary outlet is a query error", E, '        if status == native.ERR_NODE:\n            return self._engine._missing(name, "outlet")', '        if False:\n            return self._engine._missing(name, "outlet")'),
    ("E33 a query error carries no status", E, '        return QueryError(status, f"{native.message(status)} ({what})")', '        return QueryError(0, f"{native.message(status)} ({what})")'),
    ("E34 a point query does not look at its status", E, '        if status != native.OK:\n            raise self._fail(status, name, f"point query', '        if False:\n            raise self._fail(status, name, f"point query'),
    ("E35 a point query answers 0.0", E, '        return out.value', '        return 0.0'),
    ("E36 n is not checked before allocating", E, '        if not 1 <= n <= native.MAX_N:', '        if False:'),
    ("E37 n need not be a whole number", E, '        if not _values.is_int(n):\n            raise ValueError(f"n must be', '        if False:\n            raise ValueError(f"n must be'),
    ("E38 the span ends are taken the wrong way round", E, '        raw, t0, t1 = _name_bytes(name), _time(t0_ns, "t0_ns"), _time(t1_ns, "t1_ns")', '        raw, t1, t0 = _name_bytes(name), _time(t0_ns, "t0_ns"), _time(t1_ns, "t1_ns")'),
    ("E39 a span is returned read-only", E, '        return memoryview(samples)', '        return memoryview(samples).toreadonly()'),
    ("E40 a span is returned as doubles", E, '        samples = array.array("f", bytes(4 * n))', '        samples = array.array("d", bytes(8 * n))'),
    ("E41 a span failure is not noticed", E, '        if status != native.OK:\n            raise self._fail(status, name, what)', '        if False:\n            raise self._fail(status, name, what)'),
    ("E42 an instance is not freed when closed", E, '            self._lib.canopy_instance_free(pointer)', '            pass'),
    ("E43 an instance does not tell its engine it is closed", E, '            self._engine._instance_closed()', '            pass'),
    ("E44 an instance dropped without closing is not freed", E, '            self.close()\n        except Exception:                                  # noqa: BLE001\n            pass', '            pass\n        except Exception:                                  # noqa: BLE001\n            pass'),
    # ---- the native bindings and the exception ----
    ("N01 boundary kinds swapped", N, 'BOUNDARY_KINDS = {0: "inlet", 1: "outlet"}', 'BOUNDARY_KINDS = {0: "outlet", 1: "inlet"}'),
    ("N03 the point read takes a 32-bit time", N, '("canopy_instance_read_at", _i32, [_vp, _str, _i64, _p_float])', '("canopy_instance_read_at", _i32, [_vp, _str, _i32, _p_float])'),
    ("N02 the span read takes a 32-bit start", N, '("canopy_instance_read_span", _i32, [_vp, _str, _i64, _i64, _i64, _p_float])', '("canopy_instance_read_span", _i32, [_vp, _str, _i32, _i64, _i64, _p_float])'),
    ("N04 a boundary value goes as a double", N, '("canopy_engine_set_boundary", _i32, [_vp, _str, _f32])', '("canopy_engine_set_boundary", _i32, [_vp, _str, _f64])'),
    ("N05 a knob goes as a double", N, '("canopy_graph_set_knob", _i32, [_vp, _i64, _str, _f32])', '("canopy_graph_set_knob", _i32, [_vp, _i64, _str, _f64])'),
    ("N06 a float setting goes as a float", N, '("canopy_graph_set_float", _i32, [_vp, _i64, _str, _f64])', '("canopy_graph_set_float", _i32, [_vp, _i64, _str, _f32])'),
    ("N07 an int setting goes as 32 bits", N, '("canopy_graph_set_int", _i32, [_vp, _i64, _str, _i64])', '("canopy_graph_set_int", _i32, [_vp, _i64, _str, _i32])'),
    ("N08 a node ID goes as 32 bits", N, '("canopy_graph_add_node", _i32, [_vp, _i64, _str])', '("canopy_graph_add_node", _i32, [_vp, _i32, _str])'),
    ("X01 a query error forgets its status", X, '        self.status = status', '        self.status = 0'),
    # ---- the point query with a status (ABI 2): the engine's side ----
    ("I01 a span-only node's failure is not passed on by a point query", I, '        status = handlers->query_span(&ctx, outlet, t, t, 1, &value);', '        handlers->query_span(&ctx, outlet, t, t, 1, &value);\n        status = CANOPY_OK;'),
    ("I02 a point handler's status is dropped", I, '        status = handlers->query_at(&ctx, outlet, t, &value);', '        handlers->query_at(&ctx, outlet, t, &value);\n        status = CANOPY_OK;'),
    ("I03 a derived span goes on after a failure", I, '            for (i = 0; i < n && status == CANOPY_OK; i++) {', '            for (i = 0; i < n; i++) {'),
    ("I04 a derived span forgets the status of a point", I, '                status = handlers->query_at(&ctx, outlet, canopy_span_plan_time(&plan, i), &value);', '                handlers->query_at(&ctx, outlet, canopy_span_plan_time(&plan, i), &value);'),
    ("I05 a derived span stores zeros", I, '                out[i] = value;', '                out[i] = 0.0f;'),
    ("I06 a bad inlet is reported as a bad argument by a point query", I, '        return CANOPY_ERR_PORT;\n    }\n    link = node->links[inlet];\n    if (link.node < 0) {\n        *out', '        return CANOPY_ERR_ARGUMENT;\n    }\n    link = node->links[inlet];\n    if (link.node < 0) {\n        *out'),
    ("I07 a NULL out is not refused by the context call", I, '    if (!out) return CANOPY_ERR_ARGUMENT;\n    if (!ctx || !ctx->querying) {\n        *out = 0.0f;', '    if (!ctx || !ctx->querying) {\n        *out = 0.0f;'),
    ("I08 the context call outside a query leaves out alone", I, '        *out = 0.0f;\n        return CANOPY_ERR_ARGUMENT;\n    }\n    return inlet_at(ctx->instance', '        return CANOPY_ERR_ARGUMENT;\n    }\n    return inlet_at(ctx->instance'),
    ("I09 the host inlet read does not zero out on failure", I, '    if (out) *out = 0.0f;\n    if (!instance || !out) return CANOPY_ERR_ARGUMENT;\n    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);                                          /*', '    if (!instance || !out) return CANOPY_ERR_ARGUMENT;\n    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);                                          /*'),
    ("I10 the host inlet read reports an unknown node as a bad port", I, '    else status = CANOPY_ERR_NODE;\n    release(instance);\n    return status;\n}\n\n/* The boundary outlet', '    else status = CANOPY_ERR_PORT;\n    release(instance);\n    return status;\n}\n\n/* The boundary outlet'),
    ("I11 the host inlet read reports a busy instance as a missing node", I, '    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);                                          /*', '    if (!acquire(instance)) return CANOPY_ERR_NODE;\n    canopy_instance_adopt(instance);                                          /*'),
    ("I12 the host inlet read accepts a NULL out", I, '    if (!instance || !out) return CANOPY_ERR_ARGUMENT;\n    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);                                          /*', '    if (!instance) return CANOPY_ERR_ARGUMENT;\n    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);                                          /*'),
    ("I13 the boundary read does not zero out on failure", I, '    if (out) *out = 0.0f;\n    if (!instance || !name || !out) return CANOPY_ERR_ARGUMENT;', '    if (!instance || !name || !out) return CANOPY_ERR_ARGUMENT;'),
    ("I14 the boundary read accepts a NULL name", I, '    if (!instance || !name || !out) return CANOPY_ERR_ARGUMENT;', '    if (!instance || !out) return CANOPY_ERR_ARGUMENT;'),
    ("I15 the boundary read accepts a NULL out", I, '    if (!instance || !name || !out) return CANOPY_ERR_ARGUMENT;', '    if (!instance || !name) return CANOPY_ERR_ARGUMENT;'),
    ("I16 the boundary read reports a busy instance as a missing node", I, '    if (!acquire(instance)) return CANOPY_ERR_BUSY;\n    canopy_instance_adopt(instance);\n    index = outlet_by_name(instance, name);\n    if (index >= 0) status = inlet_at', '    if (!acquire(instance)) return CANOPY_ERR_NODE;\n    canopy_instance_adopt(instance);\n    index = outlet_by_name(instance, name);\n    if (index >= 0) status = inlet_at'),
    ("I17 the boundary read reports a missing name as a bad port", I, '    else status = CANOPY_ERR_NODE;\n    release(instance);\n    return status;\n}\n\nint32_t canopy_instance_read_span', '    else status = CANOPY_ERR_PORT;\n    release(instance);\n    return status;\n}\n\nint32_t canopy_instance_read_span'),
    ("I18 the boundary read does not release the instance", I, '    else status = CANOPY_ERR_NODE;\n    release(instance);\n    return status;\n}\n\nint32_t canopy_instance_read_span', '    else status = CANOPY_ERR_NODE;\n    return status;\n}\n\nint32_t canopy_instance_read_span'),
    # ---- ... and the Python side of it ----
    ("D01 a Python point handler gets a double to write into", "canopysynth/_descriptor.py", 'ctypes.c_int64, ctypes.POINTER(ctypes.c_float))\nQUERY_SPAN', 'ctypes.c_int64, ctypes.POINTER(ctypes.c_double))\nQUERY_SPAN'),
    ("D02 the node-type descriptor says ABI version 1", "canopysynth/version.py", 'ABI_VERSION = 2', 'ABI_VERSION = 1'),
]
