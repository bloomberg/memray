memray flamegraph
===================

The ``flamegraph`` subcommand generates a flame graph representation of memory usage from a previously generated
output file. You can read more about flame graphs in the :doc:`Flame Graph section <../flamegraph>` of the documentation.

General Form
------------

The ``flamegraph`` subcommand takes the following form:

.. code:: shell

    memray3.x flamegraph [-h] [-o OUTPUT] [--leaks] [--split-threads] results


The only positional argument the ``flamegraph`` subcommand requires is the file previously generated with
the :doc:`run <run>` subcommand.

The output file will be named as ``memray-flamegraph-<input file name>.html`` unless the ``-o`` argument was
specified to override the default name.

Reference
---------

.. argparse::
    :ref: memray.commands.get_argument_parser
    :path: flamegraph
    :prog: memray

    --leaks : @replace
        Enables :ref:`memory-leaks-view`, where memory that was not deallocated is displayed, instead of peak memory
        usage.

    --split-threads : @replace
        Enables :ref:`split-threads-view`, where each thread can be displayed separately. Allocations on the same source
        line across different threads are not merged, if this flag is passed.
