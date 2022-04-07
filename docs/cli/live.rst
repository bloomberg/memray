memray live
==============

The ``live`` subcommand generates a simple live view of all allocations of a program that is currently
executing. It displays the how much memory is being allocated, what the peak heap usage has been, how long the program
has been running, the source location for memory allocations and the count of allocations at each source location.

General Form
------------

The ``live`` subcommand takes the following form:

.. code:: shell

    memray3.x live [-h] port

The only positional argument the ``live`` subcommand requires is the port, where a ``run --live`` command is waiting on
a connection.

CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: live
   :prog: memray
