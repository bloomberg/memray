import threading
from typing import Callable


class ThreadNameInterceptor:
    """Record the name of each threading.Thread for Memray's reports.

    The name can be set either before or after the thread is started, and from
    either the same thread or a different thread. Whenever an assignment to
    either `Thread._name` or `Thread._ident` is performed and the other has
    already been set, we call a callback with the thread's ident and name.
    """

    def __init__(self, attr: str, callback: Callable[[int, str], None]) -> None:
        self._attr = attr
        self._callback = callback

    def __set__(self, instance: threading.Thread, value: object) -> None:
        instance.__dict__[self._attr] = value
        ident = instance.__dict__.get("_ident")
        name = instance.__dict__.get("_name")
        if ident is not None and name is not None:
            self._callback(ident, name)
