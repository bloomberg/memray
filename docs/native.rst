Native mode
===========

.. caution::
    Activating native mode has a moderate effect on performance as every instruction pointer in the call stack needs to
    be resolved every time an allocation happens in order to gather native information. This effect is more noticeable
    the more allocations the application under tracing performs.

Overview
--------

``memray`` supports tracking native C/C++ functions as well as Python functions. This can be especially useful
when profiling applications that have C extensions (such as ``numpy``, ``pandas``, ...) as this
allows to have a holistic vision of how much memory is allocated by the extension and how much is allocated by Python itself.

For instance, consider the ``mandelbrot`` example from the :ref:`example-applications` section in non native mode. One
of the most important set of allocations happens when operating with some of the ``numpy`` arrays:

.. image:: _static/images/mandelbrot_operation_non_native.png

Here, we can see some that the allocation happens when doing some math on ``numpy`` arrays but unfortunately this doesn't inform us a of what exact operation is allocating memory or how temporaries are being usedy. We also don't know if the memory was allocated by ``numpy`` or by the interpreter itself. By using
the native tracking mode with ``memray`` we can get a much richer report:

.. image:: _static/images/mandelbrot_operation_native.png

In this native report, you can see all the internal ``C`` calls that are underneath and now we can see that the memory allocation comes
when the ``numpy`` arrays are being added. In particular, it seems that the
memory of the temporary array that happens when the miltiplication is done is either reused or freed (we know that because we don't see that in the call stack).

.. tip::
    ``memray`` will also include *inlined* functions and *macros* when tracking in native mode.

Usage
-----

To activate native tracking, you need to provide the ``--native`` argument when using the ``run`` subcommand:

.. code:: shell

  > python3.9 -m memray run --native example.py

  Writing profile results into memray-example.py.4131.bin
  ...

This will automatically add native information to the result file and it will be automatically detected by any reporter
(such the *flamegraph* or *table* reporters) and the information will be displayed accordingly.

.. important::
   When generating reports for result files that contain native frames, the report needs to be generated **on the same
   machine** where the result file was generated. This is because the shared libraries that were in the memory space of
   the process needs to be inspected by ``memray`` to get the correct symbol names.

When the different reporters display native information they will normally use a different color for the Python frames
and the native frames but this can also be distinguished by looking at the file location in every frame (Python frames will
generally be generated from files with a ``.py`` extension while native frames will be generated from files with ``.c``,
``.cpp`` or ``.h`` extensions).
