The ``run`` subcommand
======================

The ``run`` subcommand is used to launch a new Python process and track the memory allocations it
performs while it runs.

Basic tracking
--------------

The general form of the ``run`` subcommand is one of:

.. code:: shell

    memray3.x run [options] file.py [args]
    memray3.x run [options] -m module [args]

(where "x" is the Python minor version).

Like the Python interpreter itself, the ``run`` subcommand can take a path to a Python file to run,
or the name of a Python module to run if you use the ``-m`` flag. While it runs, memory allocations
and deallocations throughout the program are tracked. By default they are saved into a file with the
following pattern:

``memray-<script>.<pid>.bin``

where ``<script>`` is the name of the executed script and ``<pid>`` is the process id it ran with.

A different filename can be provided with the ``-o`` or ``--output`` argument.


.. _Native tracking:

Native tracking
---------------

Overview
~~~~~~~~

Memray supports tracking native C/C++ functions as well as Python functions. This can be especially useful
when profiling libraries that have extension modules (such as ``numpy`` or ``pandas``) as this
gives a holistic vision of how much memory is allocated by the extension and how much is allocated by Python itself.

For instance, consider the Mandelbrot example from the :ref:`example-applications` section with native tracking
disabled. Some of the most important allocations happen when operating on NumPy arrays:

.. image:: _static/images/mandelbrot_operation_non_native.png

Here, we can see some that the allocation happens when doing some math on NumPy arrays but unfortunately this doesn't inform us a of what exact operation is allocating memory or how temporaries are being used. We also don't know if the memory was allocated by NumPy or by the interpreter itself. By using the native tracking mode with Memray we can get a much richer report:

.. image:: _static/images/mandelbrot_operation_native.png

In this native report, we can see all the internal C calls that are underneath. We can see that the memory allocation
happens when the NumPy arrays are being added, due to ``PyNumber_Add`` appearing in the stack trace. Based on
``PyNumber_Multiply`` not appearing in the stack trace, we can conclude that the temporary array created by NumPy is
immediately freed (or that it didn't need to allocate memory in the first place, perhaps because it could reuse some
already allocated memory).

.. tip::
    Memray will also include *inlined* functions and *macros* when native tracking is enabled.

.. caution::
    Activating native tracking has a moderate impact on performance as every instruction pointer in the call stack needs
    to be resolved whenever an allocation happens. This effect is more noticeable the more allocations the traced
    application performs.

Usage
~~~~~

To activate native tracking, you need to provide the ``--native`` argument when using the ``run`` subcommand:

.. code:: shell

  python3.9 -m memray run --native example.py

This will add native stack information to the result file, which any reporter will automatically use.

.. important::
   When generating reports for result files that contain native frames, the report needs to be generated **on the same
   machine** where the result file was generated. This is because the shared libraries that were loaded by the process
   need to be inspected by Memray to get the correct symbol names.

When reporters display native information they will normally use a different color for the Python frames than the native
frames. This can also be distinguished by looking at the file name in a frame, since Python frames will generally come
from source files with a ``.py`` extension.

Live tracking
-------------

Overview
~~~~~~~~

Memray supports presenting a "live" view for observing the memory usage of a running Python program.

.. image:: _static/images/live_running.png

Usage
~~~~~

You can run a program in live mode using ``run --live``:

.. code:: shell

  memray3.9 run --live application.py

Immediately Memray will start your application in the background and will run a TUI in the foreground that you can use
to analyze your application's memory usage. If you don't want to run your program in the background, you can instead
use ``run --live-remote``:

.. code:: shell

  memray3.9 run --live-remote application.py

In this mode it will choose an unused port and bind to it, waiting for you to run:

.. code:: shell

   memray3.9 live $port

in another terminal window to attach to it. Regardless of whether you choose to use one terminal or two, the resulting
TUI is exactly the same. See :doc:`live` for details on how to interpret and control the TUI.


Tracking across forks
---------------------

Overview
~~~~~~~~

Memray can optionally continue tracking in a child process after a parent process forks. This can be useful when using
``multiprocessing``, or a framework utilizing a pre-fork pattern like Celery or Gunicorn.

Usage
~~~~~

To activate tracking through forks, you need to provide the ``--follow-fork`` argument to the ``run`` subcommand:

.. code:: shell

  python3.9 -m memray run --follow-fork example.py

In this mode, each time the process forks, a new output file will be created for the new child process, with the new
child's process ID appended to the original capture file's name. The capture files for child processes are exactly like
any other capture file, and can be fed into any reporter of your choosing.

.. note::

  ``--follow-fork`` mode can only be used with an output file. It is incompatible with ``--live``
  mode and ``--live-remote`` mode, since the TUI can't be attached to multiple processes at once.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: run
   :prog: memray
