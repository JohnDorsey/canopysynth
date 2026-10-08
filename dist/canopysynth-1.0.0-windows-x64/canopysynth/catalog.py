"""The node types a graph may name, and the migrations that bring a graph saved under an older type version up to date.

The types come from a registry of the DLL (the built-in ones, through `default_types()`) or from any registry a test or host made: a
catalog holds the registered descriptors as plain Python data (what `_descriptor.read_node_type` returns), so a Graph never touches the DLL
while it is edited. "Installed" in design section 14 ("a graph that names a node type that is not installed is rejected") means: present
in the catalog the graph was made with."""
import ctypes
import threading

from . import _descriptor
from .errors import GraphError


class TypeInfo:
    """One node type: the descriptor's data (`data`, a dict) with lookups by key for the graph model."""

    def __init__(self, data):
        self.data = data
        self.key = data["key"]
        self.name = data["name"]
        self.type_version = data["type_version"]
        self.realtime_safe = data["realtime_safe"]
        self.has_internal_rate = data["has_internal_rate"]
        self.inlets, self.outlets = data["inlets"], data["outlets"]
        self.settings, self.widgets = data["settings"], data["widgets"]
        self.inlet = {i["key"]: i for i in self.inlets}
        self.outlet = {o["key"]: o for o in self.outlets}
        self.setting = {s["key"]: s for s in self.settings}
        # the value a new node holds for each setting: the descriptor's default, except that a choice is held as its text (the descriptor
        # gives the INDEX of the default choice)
        self.defaults = {s["key"]: (s["choices"][s["default"]] if s["kind"] == "choice" else s["default"]) for s in self.settings}
        self.inlet_index = {i["key"]: n for n, i in enumerate(self.inlets)}
        self.outlet_index = {o["key"]: n for n, o in enumerate(self.outlets)}


class Migration:
    """What changes between one type version and the next: see NodeTypes.add_migration."""

    def __init__(self, upgrade, inlets, outlets):
        self.upgrade, self.inlets, self.outlets = upgrade, dict(inlets or {}), dict(outlets or {})


class NodeTypes:
    """A set of node types by key, with the migrations registered for them."""

    def __init__(self, descriptors=()):
        self._types = {}
        self._migrations = {}                # (type key, from version) -> Migration
        for data in descriptors:
            self.add(data)

    @classmethod
    def from_registry(cls, registry, dll):
        """The types registered in a C registry (a pointer from canopy_registry_new), read through `dll` (a loaded canopysynth.dll)."""
        dll.canopy_registry_count.argtypes = [ctypes.c_void_p]
        dll.canopy_registry_count.restype = ctypes.c_int32
        dll.canopy_registry_at.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        dll.canopy_registry_at.restype = ctypes.POINTER(_descriptor.NodeType)
        return cls(_descriptor.read_node_type(dll.canopy_registry_at(registry, i)) for i in range(dll.canopy_registry_count(registry)))

    def add(self, data):
        """Adds a descriptor as read by `_descriptor.read_node_type`; ValueError if its key is already there."""
        if data["key"] in self._types:
            raise ValueError(f"the node type {data['key']!r} is already in the catalog")
        self._types[data["key"]] = TypeInfo(data)

    def get(self, key):
        """The TypeInfo of a node type, or None if it is not installed."""
        return self._types.get(key)

    def keys(self):
        return list(self._types)

    def __contains__(self, key):
        return key in self._types

    def add_migration(self, type_key, from_version, *, upgrade=None, inlets=None, outlets=None):
        """Registers how a node saved under `from_version` of a type becomes a node of `from_version + 1` (design section 12: a type that
        changes its settings or ports registers a migration from each older version; a file saved under version 1 of a type now at version 3
        goes through the migrations 1 and 2 in turn).

        `upgrade(settings, knobs)`, if given, is called with plain dicts of what the file holds for the node (a copy: settings by setting
        key, knobs by inlet key, values as saved under the OLD version) and changes them in place: rename a setting, convert a value, add a
        new one. After it, `inlets` and `outlets` (dicts old key -> new key, or None for a port that no longer exists) rename the inlet keys
        of the knobs and the ends of the node's connections; a connection to a port that goes away is dropped. Everything the migrations
        leave is then checked against the CURRENT type like any file (unknown or ill-typed settings are refused).

        ValueError if the type is not in the catalog, `from_version` is not a version below the current one, or that migration exists."""
        info = self._types.get(type_key)
        if info is None:
            raise ValueError(f"cannot add a migration for the node type {type_key!r}: it is not in the catalog")
        if type(from_version) is not int or not 1 <= from_version < info.type_version:
            raise ValueError(f"a migration of {type_key!r} must start from a version from 1 to {info.type_version - 1} (the current version is "
                             f"{info.type_version}), not {from_version!r}")
        if (type_key, from_version) in self._migrations:
            raise ValueError(f"the migration of {type_key!r} from version {from_version} is already registered")
        if upgrade is not None and not callable(upgrade):
            raise ValueError("upgrade must be a function taking (settings, knobs), or None")
        for name, renames in (("inlets", inlets), ("outlets", outlets)):
            for old, new in (renames or {}).items():
                if not isinstance(old, str) or not (new is None or isinstance(new, str)):
                    raise ValueError(f"{name} must map port keys (text) to new keys (text) or None, not {old!r}: {new!r}")
        self._migrations[(type_key, from_version)] = Migration(upgrade, inlets, outlets)

    def migration(self, type_key, from_version):
        """The registered Migration of a type from a version, or None."""
        return self._migrations.get((type_key, from_version))


_default = None
_default_lock = threading.Lock()


def default_types():
    """The catalog of the built-in node types (the DLL's own registry), made on first use; Graph() uses it unless told another."""
    global _default
    with _default_lock:
        if _default is None:
            from . import _lib                       # only here: importing the package does not load the DLL
            dll = _lib.load_dll()
            dll.canopy_registry_new.restype = ctypes.c_void_p
            dll.canopy_registry_free.argtypes = [ctypes.c_void_p]
            registry = dll.canopy_registry_new()
            if not registry:
                raise GraphError("the node-type registry could not be made (out of memory)")
            try:
                _default = NodeTypes.from_registry(registry, dll)
            finally:
                dll.canopy_registry_free(registry)
        return _default


def register_migration(type_key, from_version, *, upgrade=None, inlets=None, outlets=None):
    """NodeTypes.add_migration on the catalog of the built-in types."""
    default_types().add_migration(type_key, from_version, upgrade=upgrade, inlets=inlets, outlets=outlets)
