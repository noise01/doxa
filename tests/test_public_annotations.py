"""Every exported signature can be read back at runtime.

Shipping ``py.typed`` and the ``Typing :: Typed`` classifier is a promise that
the annotations in here are usable. Under PEP 649 an annotation is evaluated when
something reads it -- ``typing.get_type_hints``, ``inspect.signature``, a
dataclass adapter, a docs generator -- and a name imported only under
``if TYPE_CHECKING`` is not there when that happens.

The package was published twice with 26 of its 63 exported callables raising
``NameError`` on ``get_type_hints``: the whole solver construction API, five of
governance, every windowed calibration function. Nothing failed at import and
nothing failed in a test, because none of it is read unless someone reads it.

The list of modules is read off the source tree rather than written down here. A
list would have to be kept in step with the package, and a check that silently
stops covering a new module is the shape of thing this file exists to prevent.
"""

import importlib
import inspect
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _packages_declaring_exports() -> list[str]:
    """Public packages, excluding internal packages."""
    root = ROOT / "src" / "endoxa"
    found = []
    for path in sorted(root.rglob("__init__.py")):
        relative = path.parent.relative_to(root).as_posix()
        if any(part.startswith("_") for part in path.parent.relative_to(root).parts):
            continue
        dotted = "endoxa" if relative == "." else f"endoxa.{relative.replace('/', '.')}"
        if getattr(importlib.import_module(dotted), "__all__", None):
            found.append(dotted)
    return found


EXPORTING_PACKAGES = _packages_declaring_exports()


def _exported(module_name: str) -> list[tuple[str, object]]:
    module = importlib.import_module(module_name)
    return [
        (f"{module_name}.{name}", getattr(module, name))
        for name in module.__all__
        if inspect.isfunction(getattr(module, name)) or inspect.isclass(getattr(module, name))
    ]


def _unresolvable(module_name: str) -> list[str]:
    offences = []
    for qualified, obj in _exported(module_name):
        try:
            typing.get_type_hints(obj)
        except Exception as exc:  # noqa: BLE001 - any failure to read is the failure
            offences.append(f"{qualified}: {type(exc).__name__}: {exc}")
    return offences


@pytest.mark.parametrize("module_name", EXPORTING_PACKAGES)
def test_every_exported_annotation_resolves(module_name):
    offences = _unresolvable(module_name)
    assert not offences, "annotations that cannot be read back:\n" + "\n".join(offences)


def test_the_walk_covers_the_packages_a_reader_imports_from():
    """The control: walking an empty list passes the test above for free."""
    assert len(EXPORTING_PACKAGES) >= 6, EXPORTING_PACKAGES
    for layer in ("endoxa.governance", "endoxa.solver", "endoxa.syntax", "endoxa.trace"):
        assert layer in EXPORTING_PACKAGES
        assert _exported(layer), f"{layer} exported no callable, so nothing above was checked"


def test_a_planted_type_checking_import_is_caught():
    """The exact shape that broke it, built here so the detector is seen firing."""
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - the point is to compile a module whose annotation cannot resolve
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Sequence\n"
        "def f(xs: 'Sequence[int]') -> int: return len(xs)\n",
        namespace,
    )
    with pytest.raises(NameError, match="Sequence"):
        typing.get_type_hints(namespace["f"])
