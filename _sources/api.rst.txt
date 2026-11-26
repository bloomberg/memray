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

.. autoclass:: memray.FileFormat()

   This enumeration lists the capture file formats that Memray can write. The
   `Tracker` constructor accepts a *file_format* keyword argument for choosing
   a different format than the default.

    .. autoattribute:: memray.FileFormat.ALL_ALLOCATIONS
       :annotation:

    Record every allocation that the tracked process performs. This is the
    default format. The produced capture files may be very large if the process
    performs many allocations. This is the only format that allows detecting
    :doc:`temporary allocations </temporary_allocations>` or using the
    :doc:`stats reporter <stats>`.

    .. autoattribute:: memray.FileFormat.AGGREGATED_ALLOCATIONS
       :annotation:

    For every location where the tracked process performed any allocations, the
    capture file includes a count of:

    - How many allocations at that location had not yet been deallocated when
      the process reached its heap memory high water mark
    - How many bytes had been allocated at that location and not yet
      deallocated when the process reached its heap memory high water mark
    - How many allocations at that location were leaked (i.e. not deallocated
      before tracking stopped)
    - How many bytes were leaked by allocations at that location

    You cannot find :doc:`temporary allocations </temporary_allocations>` using
    this capture file format, since finding temporary allocations requires
    knowing when each allocation was deallocated, and that information is lost
    by the aggregation. You also cannot use the :doc:`stats reporter <stats>`
    with this capture file format, because it needs to see every allocation's
    size to compute its statistics.

    Additionally, if the process is killed before tracking ends (for instance,
    by the Linux OOM killer), then no useful information is ever written to the
    capture file, because aggregation was still happening inside the process
    when it died.

    If you can live with these limitations, then ``AGGREGATED_ALLOCATIONS``
    results in much smaller capture files that can be used seamlessly with most
    reporters.
