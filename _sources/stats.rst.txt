Stats Reporter
==============

The stats reporter generates high level statistics about the tracked process's
memory allocations.

.. image:: _static/images/stats_example.png

The output includes the following:

* Total number of allocations performed

* Total amount of memory allocated

* Histogram displaying the distribution of allocation sizes. The y-axis data (size) is logarithmic.

* Distribution of allocation types (e.g. *MALLOC*, *CALLOC*, *MMAP*, etc.)

* Stack trace and **size** of the top 'n' largest allocating locations by size (*default: 5*, configurable with the ``-n`` command line param)

* Stack trace and **count** of the top 'n' largest allocating locations by number of allocations (*default: 5*, configurable with the ``-n`` command line param)

* (for JSON output only) Metadata about the tracked process

Basic Usage
-----------

The general form of the ``stats`` subcommand is:

.. code:: shell

    memray stats [options] <results>

The only argument the ``stats`` subcommand requires is the capture file
previously generated using :doc:`the run subcommand <run>`.

The output will be printed directly to the standard output of the terminal.

JSON Output
-----------

If you supply the ``--json`` flag, the ``stats`` subcommand will write its
output to a JSON file, rather than to the terminal. Like other commands that
output to files, the default output file name is based on the name of your
capture file, but it can be overridden with the ``-o`` / ``--output`` option.
By default Memray will refuse to overwrite an existing file, but you can force
it to by supplying the ``-f`` / ``--force`` option.

Note that new fields may be added to the JSON output over time, though we'll
try to avoid removing existing fields.

CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: stats
   :prog: memray
