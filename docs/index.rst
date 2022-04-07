memray
======

.. image:: _static/images/output.png

``Memray`` is a memory profiler for Python. It can track memory allocations both in Python code and
native extensions and generate various reports to help analyze memory usage in libraries and applications.
It can be used as a CLI tool or as a library to perform more fine-grained profiling tasks.

Notable features:

- 🕵️‍♀️ Traces every function call so it can accurately represent the call stack, unlike sampling profilers.
- ℭ Also handles native calls in C/C++ libraries so the entire call stack is present in the results.
- 🏎 Blazing fast! Profiling causes minimal slowdown in the application. Tracking native code is somewhat slower, but this can be enabled or disabled on demand.
- 📈 It can generate various reports about the collected memory usage data, like flame graphs.
- 🧵 Works with Python threads.
- 👽🧵 Works with native-threads (e.g. C++ threads in native extensions)

``Memray`` can help with the following problems:

- Analyze allocations in applications to help reduce memory usage.
- Find memory leaks.
- Find hotspots in code which cause a lot of allocations.


.. note::
    ``Memray`` only works on Linux and cannot be installed on other platforms.


.. toctree::
   :hidden:

   usage
   native
   live
   examples/README

.. toctree::
   :hidden:
   :caption: Reporters

   summary
   flamegraph
   table
   tree
   stats
.. toctree::
   :hidden:
   :caption: Command Line Interface

   cli/summary
   cli/run
   cli/live
   cli/flamegraph
   cli/table
   cli/tree
   cli/stats
