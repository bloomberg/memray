Detect when another tool, such as ``tracemalloc``, replaces or removes the
Python reference tracer while a ``Tracker`` with ``track_object_lifetimes=True``
is active. Exiting the tracker now raises ``RuntimeError`` instead of reporting
stale objects, and Memray no longer removes a reference tracer installed by
another tool during its own cleanup.
