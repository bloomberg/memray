memray run
============

General Form
------------

The ``run`` (where x is the minor Python version) subcommand takes the following form:

.. code:: shell

    memray3.x run [-m module | file] [args]


The ``run`` subcommand runs either a library module as a script when using ``-m``, or a Python file,
and tracks memory allocations and deallocations throughout the program. The results are saved into a file.


Results File
------------

By default the results are saved into a file with the following pattern:

``memray-<script>.<pid>.bin``

- script: the name of the executed script
- pid: the process ID of the running program

This file can be overridden with the ``-o`` or ``--output`` argument.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: run
   :prog: memray
