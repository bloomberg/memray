Introduction
============

**Memray** is an open-source memory profiler for Python, built at Bloomberg. It can track memory allocations in Python code, in native extension modules, and in the Python interpreter itself. It can generate several different types of reports to help you analyze the captured memory usage data. While commonly used as a CLI tool, it can also be used as a library to perform more fine-grained profiling tasks.

Memray can help with the following problems:

- Analyse allocations in applications to help discover the cause of high memory usage
- Find memory leaks
- Find hotspots in code which cause a lot of allocations


Notable Features
----------------

- Traces every function call so it can accurately represent the call stack, unlike sampling profilers
- It can generate various reports about the collected memory usage data
- Also handles native calls in C/C++ libraries so the entire call stack is present in the results
- Works with
    - Python threads
    - Native-threads (e.g. C++ threads in native extensions)
- Blazing fast - profiling causes minimal slowdown in the application. Tracking native code is somewhat slower, but this can be enabled or disabled on demand
- Pytest API
