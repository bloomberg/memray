<img src="https://github.com/bloomberg/memray/blob/main/docs/_static/images/memray.png" align="right" height="150" width="130"/>

# memray

[![Tests](https://github.com/bloomberg/memray/actions/workflows/build.yml/badge.svg)](https://github.com/bloomberg/memray/actions/workflows/build.yml)
[![Linux Wheels](https://github.com/bloomberg/memray/actions/workflows/build_wheels.yml/badge.svg)](https://github.com/bloomberg/memray/actions/workflows/build_wheels.yml)
![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)

<p align="center"><img src="https://github.com/bloomberg/memray/blob/main/docs/_static/images/output.png" alt="Memray output"></p>

Memray is a memory profiler for Python. It can track memory allocations both in Python code and native extensions and
generate various reports to help analyze memory usage in libraries and applications. It can be used as a CLI tool or as
a library to perform more fine-grained profiling tasks.

Notable features:

- 🕵️‍♀️ Traces every function call so it can accurately represent the call stack, unlike sampling profilers.
- ℭ Also handles native calls in C/C++ libraries so the entire call stack is present in the results.
- 🏎 Blazing fast! Profiling causes minimal slowdown in the application. Tracking native code is somewhat slower,
  but this can be enabled or disabled on demand.
- 📈 It can generate various reports about the collected memory usage data, like flame graphs.
- 🧵 Works with Python threads.
- 👽🧵 Works with native-threads (e.g. C++ threads in C extensions).

Memray can help with the following problems:

- Analyze allocations in applications to help reduce memory usage.
- Find memory leaks.
- Find hotspots in code which cause a lot of allocations.

Note that memray only works on Linux and cannot be installed on other platforms.
