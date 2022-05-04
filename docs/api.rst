.. module:: memray

Memray API
==========

Memray exposes an API that can be used to programmatically activate or
deactivate tracking of a Python process's memory allocations. You do this by
creating a `Tracker` object and using it as a context manager in a ``with``
statement. While the body of the ``with`` statement runs, tracking will be
enabled, with output being sent to a destination you specify when creating the
`Tracker`. When the ``with`` block ends, tracking will be disabled and the
output will be flushed and closed.

API Usage
---------

.. autoclass:: memray.Tracker
   :members:

.. autoclass:: memray.FileDestination
   :members:

.. autoclass:: memray.SocketDestination
   :members:
