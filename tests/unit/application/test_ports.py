"""TASK-205 - ports are a contract, so the contract itself is tested.

A Protocol that nothing checks is a comment. These tests fail if an adapter drifts.
"""

from __future__ import annotations

import inspect

import pytest

from anuvritti.application import ports
from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    IntentEngine,
    LittleThingRepository,
    MediaStore,
    MomentRepository,
    RightNowRepository,
    SparkRepository,
    Transcriber,
    UnitOfWork,
)

ALL_PORTS = [
    FamilyRepository,
    SparkRepository,
    MomentRepository,
    LittleThingRepository,
    RightNowRepository,
    MediaStore,
    IntentEngine,
    Transcriber,
    EventPublisher,
    UnitOfWork,
]


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_every_port_is_a_runtime_checkable_protocol(port):
    assert issubclass(port, ports.Protocol)  # type: ignore[arg-type]
    assert getattr(port, "_is_runtime_protocol", False), f"{port.__name__} is not runtime-checkable"


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_every_port_declares_at_least_one_method(port):
    methods = [n for n in dir(port) if not n.startswith("_")]
    assert methods, f"{port.__name__} declares nothing"


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_every_port_method_is_fully_annotated(port):
    for name, member in inspect.getmembers(port, inspect.isfunction):
        if name.startswith("_"):
            continue
        hints = inspect.get_annotations(member)
        params = [p for p in inspect.signature(member).parameters if p != "self"]
        assert "return" in hints, f"{port.__name__}.{name} has no return annotation"
        for param in params:
            assert param in hints, f"{port.__name__}.{name}({param}) is unannotated"


def test_repository_reads_and_writes_return_result():
    """Persistence fails for ordinary reasons; those are values, not exceptions (ADR-0002)."""
    for name, member in inspect.getmembers(SparkRepository, inspect.isfunction):
        if name.startswith("_"):
            continue
        assert "Result" in str(inspect.get_annotations(member)["return"]), name


def test_the_intent_engine_returns_a_plain_domain_value():
    """The domain must not learn what an LLM response looks like (ADR-0004)."""
    hints = inspect.get_annotations(IntentEngine.infer)
    assert hints["return"] is not None
    assert "Inference" in str(hints["return"])


def test_every_family_scoped_store_can_delete_everything():
    """PRD 44 - "delete everything" is only real if every store implements it."""
    deletable = [
        FamilyRepository,
        SparkRepository,
        MomentRepository,
        LittleThingRepository,
        RightNowRepository,
        MediaStore,
        EventPublisher,
    ]
    for port in deletable:
        assert any(
            name in {"delete", "delete_for_family"}
            for name, _ in inspect.getmembers(port, inspect.isfunction)
        ), f"{port.__name__} cannot be erased"


def test_ports_module_imports_no_adapter():
    """Dependency inversion, checked at the one place it matters most."""
    source = inspect.getsource(ports)
    assert "anuvritti.adapters" not in source
