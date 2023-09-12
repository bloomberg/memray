import atexit

import memray


def deactivate_last_tracker() -> None:
    global _last_tracker
    tracker = _last_tracker

    if tracker:
        _last_tracker = None
        tracker.__exit__(None, None, None)


def activate_tracking(**tracker_kwargs) -> None:
    global _last_tracker
    deactivate_last_tracker()

    tracker = memray.Tracker(**tracker_kwargs)
    try:
        tracker.__enter__()
        _last_tracker = tracker
    finally:
        # Prevent any exception from keeping the tracker alive.
        # This way resources are cleaned up ASAP.
        del tracker


def callback(**tracker_kwargs) -> None:
    activate_tracking(**tracker_kwargs)


_last_tracker = None
atexit.register(deactivate_last_tracker)
