"""The skeleton imports, and its packages are the ones the contracts name."""

import importlib

import endoxa

PACKAGES = [
    "endoxa.governance",
    "endoxa.instruments",
    "endoxa.instruments.calibration",
    "endoxa.instruments.coverage",
    "endoxa.solver",
    "endoxa.syntax",
    "endoxa.trace",
]


def test_package_imports():
    assert endoxa.__doc__


def test_every_declared_package_imports():
    for name in PACKAGES:
        assert importlib.import_module(name) is not None
