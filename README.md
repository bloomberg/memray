<img src="https://raw.githubusercontent.com/bloomberg/memray/main/docs/_static/images/memray.png" align="right" height="150" width="130"/>

# memray

![PyPI - Python Version](https://img.shields.io/pypi/pyversions/memray)
![PyPI - Implementation](https://img.shields.io/pypi/implementation/memray)
![PyPI](https://img.shields.io/pypi/v/memray)
![PyPI - Downloads](https://img.shields.io/pypi/dm/memray)
[![Tests](https://github.com/bloomberg/memray/actions/workflows/build.yml/badge.svg)](https://github.com/bloomberg/memray/actions/workflows/build.yml)
![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)

<p align="center"><img src="https://raw.githubusercontent.com/bloomberg/memray/main/docs/_static/images/output.png" alt="Memray output"></p>

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

# Installation

Memray requires Python 3.7+ and can be easily installed using most common Python
packaging tools. We recommend installing the latest stable release from
[PyPI](https://pypi.org/project/memray/) with pip:

```shell
    pip install memray
```

Notice that Memray contains a C extension so releases are distributed as binary
wheels as well as the source code. If a binary wheel is not available for your system
(Linux x86/x64), you'll need a recent to ensure that all the binary dependencies are
satisfied in the system where you are doing the installation.

## Building from source

If you wish to build Memray from source you need the following binary dependencies in your system:

- libunwind

Check your package manager on how to install these dependencies (for example `apt-get install libunwind-dev` in Debian-based systems).

Once you have the binary dependencies installed, you can clone the repository and follow with the normal building process:

```python
git clone git@github.com:bloomberg/memray.git memray
cd memray
python3 -m venv ../memray-env/  # just an example, put this wherever you want
source ../memray-env/bin/activate
pip install --upgrade pip
pip install -e . -r requirements-test.txt -r requirements-extra.txt
```

This will install Memray in the virtual environment in development mode (the `-e` of the last `pip install` command).

# Documentation

You can find the latest documentation available in [here](https://libcst.readthedocs.io/).

# Usage

There are many ways to use Memray. The easiest way is to use it as a command line tool to run your script, application or library.

```
usage: memray [-h] [-v] {run,flamegraph,table,live,tree,parse,summary,stats} ...

Memory profiler for Python applications

Run `memray run` to generate a memory profile report, then use a reporter command
such as `memray flamegraph` or `memray table` to convert the results into HTML.

Example:

    $ python3 -m memray run my_script.py -o output.bin
    $ python3 -m memray flamegraph output.bin

positional arguments:
  {run,flamegraph,table,live,tree,parse,summary,stats}
                        Mode of operation
    run                 Run the specified application and track memory usage
    flamegraph          Generate an HTML flame graph for peak memory usage.
    table               Generate an HTML table with all records in the peak memory usage.
    live                Remotely monitor allocations in a text-based interface.
    tree                Generate an tree view in the terminal for peak memory usage.
    parse               Debug a results file by parsing and printing each record in it.
    summary             Generate a terminal-based summary report of the functions that allocate most memory
    stats               Generate high level stats of the memory usage in the terminal

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Increase verbosity. Option is additive, can be specified up to 3 times.

Please submit feedback, ideas and bugs by filing a new issue at https://github.com/bloomberg/memray/issues
```

To use memray over a script or a single python file you can use

```shell
python3.x -m memray run my_script.py
```

(where 3.x is the version of Python you want to use). If your application is executed as a module (you execute your application wth `python3 -m my_module`), you can use the following command instead:

```shell
python3.x -m memray run -m my_module.py
```

You can also invoke Memray as a command line tool without having to invoke it as a module, with either of the previous forms:

```shell
memray3.x run my_script.py
memray3.x run -m my_module.py
```

The output will be a binary file (like `memray-my_script.2369.bin`) that you can analyze in different ways. One way is to use the `memray flamegraph` command to generate a flame graph:

```shell
memray3.x flamegraph my_script.2369.bin
```

This will produce an html file with a flame graph of the memory usage that you can inspect with your favorite browser. There are multiple other reporters that you can use to generate other types of reports, some of them generating a terminal-based output and some of them generate an html file. Here is an example of such flamegraph:

<img src="https://github.com/bloomberg/memray/blob/main/docs/_static/images/flamegraph_example.png?raw=true" align="center"/>

# Native mode

Memray supports tracking native C/C++ functions as well as Python functions. This can be especially useful when profiling applications that have C extensions (such as `numpy`, `pandas`, …) as this allows to have a holistic vision of how much memory is allocated by the extension and how much is allocated by Python itself.

To activate native tracking, you need to provide the `--native` argument when using the run subcommand:

```shell
python3.x -m memray run --native my_script.py
```

This will automatically add native information to the result file and it will be automatically detected by any reporter (such the flamegraph or table reporters) and the information will be displayed accordingly. This means that instead of seeing this in the flamegraphs:

<img src="https://github.com/bloomberg/memray/blob/main/docs/_static/images/mandelbrot_operation_non_native.png?raw=true" align="center"/>

You will now be able to see what's happening under the Python calls:

<img src="https://github.com/bloomberg/memray/blob/main/docs/_static/images/mandelbrot_operation_native.png?raw=true" align="center"/>

When the different reporters display native information they will normally use a different color for the Python frames and the native frames but this can also be distinguished by looking at the file location in every frame (Python frames will generally be generated from files with a .py extension while native frames will be generated from files with .c, .cpp or .h extensions).

# Live mode

Memray supports live mode, which will run a script or a module in a terminal-based interface that allows you to interactively inspect the memory usage of the script or module. This is useful for debugging scripts or modules that take a long time to run or that exhibit multiple complex memory patterns. You can use the `--live` option to run the script or module in live mode:

```shell
    python3.x -m memray run --live my_script.py
```

or if you want to execute a module:

```shell
    python3.x -m memray run --live -m my_module.py
```

This will show the following TUI interface in your terminal:

<img src="https://raw.githubusercontent.com/bloomberg/memray/main/docs/_static/images/live_running.png" align="center"/>

## Sorting results

The results are displayed in descending order of total memory allocated by a function and the subfunctions called by it. You can change the ordering with the following keyboard shortcuts:

- t (default): Sort by total memory

- o: Sort by own memory

- a: Sort by allocation count

The sorted column is highlighted with `< >` characters around the title.

## Viewing different threads

By default, the live command will present the main thread of the program. You can look at different threads of the program by pressing the left and right arrow keys.

<img src="https://github.com/bloomberg/memray/blob/main/docs/_static/images/live_different_thread.png?raw=true" align="center"/>

# License

Memray is Apache-2.0 licensed, as found in the LICENSE file.

# Code of Conduct

- [Code of Conduct](https://github.com/bloomberg/.github/blob/main/CODE_OF_CONDUCT.md)

This project has adopted a Code of Conduct. If you have any concerns about the Code, or behavior which you have experienced in the project, please contact us at opensource@bloomberg.net.

# Security Policy

- [Security Policy](https://github.com/bloomberg/memray/security/policy)

If you believe you have identified a security vulnerability in this project, please send email to the project team at opensource@bloomberg.net, detailing the suspected issue and any methods you've found to reproduce it.

Please do NOT open an issue in the GitHub repository, as we'd prefer to keep vulnerability reports private until we've had an opportunity to review and address them.

# Contributing

We welcome your contributions to help us improve and extend this project!

Below you will find some basic steps required to be able to contribute to the project. If you have any questions about this process or any other aspect of contributing to a Bloomberg open source project, feel free to send an email to opensource@bloomberg.net and we'll get your questions answered as quickly as we can.

## Contribution Licensing

Since this project is distributed under the terms of an [open source license](LICENSE), contributions that you make
are licensed under the same terms. In order for us to be able to accept your contributions,
we will need explicit confirmation from you that you are able and willing to provide them under
these terms, and the mechanism we use to do this is called a Developer's Certificate of Origin
[(DCO)](DCO.md). This is very similar to the process used by the Linux(R) kernel, Samba, and many
other major open source projects.

To participate under these terms, all that you must do is include a line like the following as the
last line of the commit message for each commit in your contribution:

    Signed-Off-By: Random J. Developer <random@developer.example.org>

The simplest way to accomplish this is to add `-s` or `--signoff` to your `git commit` command.

You must use your real name (sorry, no pseudonyms, and no anonymous contributions).

## Steps

- Create an Issue, selecting 'Feature Request', and explain the proposed change.
- Follow the guidelines in the issue template presented to you.
- Submit the Issue.
- Submit a Pull Request and link it to the Issue by including "#<issue number>" in the Pull Request summary.
