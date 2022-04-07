memray table
==============

The ``table`` subcommand generates a simple table view of all allocations at the time when the memory usage
was at its peak. The table displays the source location and type of the allocator, the count of allocations and the
overall amount of memory used.

General Form
------------

The ``table`` subcommand takes the following form:

.. code:: shell

    memray3.x table [-h] [-o OUTPUT] [--leaks] [--split-threads] results


The only positional argument the ``table`` subcommand requires is the file previously generated with
the :doc:`run <run>` subcommand.


The output file will be named as ``memray-table-<input file name>.html`` unless the ``-o`` argument was
specified to override the default name.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: table
   :prog: memray
