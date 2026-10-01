"""Shared Ollama access gate so study never blocks user Layer-1 replies."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

# User turns set this so in-flight study generations abort ASAP.
_user_priority = threading.Event()
# Only one Ollama generate at a time (study + Layer 1 share the GPU model).
_ollama_lock = threading.Lock()
_study_abort = threading.Event()


def begin_user_turn() -> None:
    _user_priority.set()
    _study_abort.set()


def end_user_turn() -> None:
    _user_priority.clear()
    # Keep abort cleared only when no nested user turns — callers use study notify depth.
    if not _user_priority.is_set():
        _study_abort.clear()


def user_wants_priority() -> bool:
    return _user_priority.is_set()


def clear_study_abort() -> None:
    if not _user_priority.is_set():
        _study_abort.clear()


def study_must_abort() -> bool:
    return _study_abort.is_set() or _user_priority.is_set()


@contextmanager
def ollama_exclusive(*, for_user: bool = False, wait: float = 30.0) -> Iterator[bool]:
    """
    Acquire exclusive Ollama access.
    Returns True if lock acquired. Study should pass for_user=False and short wait.
    """
    got = _ollama_lock.acquire(timeout=wait if for_user else min(wait, 0.05))
    try:
        if not got and for_user:
            # One more try — study may release soon after abort
            got = _ollama_lock.acquire(timeout=max(0.5, wait))
        yield got
    finally:
        if got:
            _ollama_lock.release()
