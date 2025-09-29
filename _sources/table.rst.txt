Table Reporter
==============

The table reporter generates an HTML document showing a simple tabular view of
the allocations contributing to the tracked process's peak memory usage. Each
source line that contributed to that peak memory usage is given a row in the
generated table, showing the amount of memory it allocated, the type of
allocator it used, and the number of allocations it was responsible for.

.. image:: _static/images/table_example.png


The table can be sorted by each column and searched in the search field. The columns show the following data:

- Thread ID: thread where the allocation happened
- Size: total amount of memory used by all of these allocations
- Allocator: allocator or deallocator function which acquired the memory
- Allocations: total number of allocations performed by this entry
- Location: function name, file and line of the allocation or "???" if unknown

Basic Usage
-----------

The general form of the ``table`` subcommand is:

.. code:: shell

    memray table [options] <results>

The only argument the ``table`` subcommand requires is the capture file
previously generated using :doc:`the run subcommand <run>`.


The output file will be named as ``memray-table-<input file name>.html`` unless the ``-o`` argument was
specified to override the default name.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: table
   :prog: memray
