Supported environments
======================

Supported Python interpreters
-----------------------------

Only CPython is supported.

Supported Python versions
-------------------------

Every Python version that hasn't reached end of life is supported.

Currently that's Python 3.7 through 3.12.

Supported operating systems
---------------------------

You will have the best Memray experience on Linux.

We also support macOS 11 or newer. We cannot support older
macOS versions, as they don't provide a C++17 compatible runtime. Although all
features work on macOS, the way that macOS applications and Python libraries
are typically distributed often results in subpar native stacks on Mac. See
:ref:`the native mode documentation <mac symbolification>` for details on these
shortcomings.

We are unlikely to ever support Windows. While the basic technique that Memray
uses to detect memory allocations is possible on Windows, much of the library
would need to be rewritten to support non-POSIX platforms, and none of the
current maintainers have the expertise to do so. We do test in WSL, however.

Supported CPU architectures
---------------------------

For Linux, we test on ``i686``, ``x86-64``, and ``aarch64``. Pre-built wheels
are only available on PyPI for ``i686`` and ``x86-64``, though. That is
unlikely to change until cibuildwheel_ provides `non-emulated aarch64 support`_.

For macOS, we test on ``x86-64`` and ``arm64`` - so, both Intel and Apple
Silicon Macs. Pre-built wheels are available for both architectures, though
only for Python 3.8 and newer.

Supported runtime environments
------------------------------

We require a C++17 runtime. As noted above, macOS 11 or higher is required for
a C++17 runtime on Mac.

On Linux we support glibc and musl libc. Other libc's have not been tested, and
issues are likely. For Python 3.10 and earlier we support platforms compatible
with the ``manylinux2010`` specification, and for Python 3.11 onward we require
``manylinux2014`` compatibility.

Known issues and limitations
----------------------------

* Native stack traces on macOS are often difficult to read, and may be missing
  function calls. See :ref:`the native mode documentation <mac
  symbolification>`.
* We support :ref:`tracking across forks <tracking across forks>`, but can't
  track across an ``exec``, so if the tracked child process calls `an os.exec
  function`_, even to start a new Python interpreter, we will not be able to
  report the allocations performed in the new process. Notably, the default
  `multiprocessing start method`_ on macOS is "spawn", which leverages
  ``exec``.
* Cython_ functions will not be included in the Python stacks we report, even
  if the Cython module is built with profiling_ support. You'll need to use
  :ref:`native tracking` to see what's happening inside Cython modules.
* We have experimental support for the ``greenlet`` library, which may lead to
  incorrect stacks being reported if :doc:`the Memray API <api>` is used to
  start tracking in one thread while another thread is already making use of
  the Greenlet library.

.. _cibuildwheel: https://github.com/pypa/cibuildwheel
.. _non-emulated aarch64 support: https://cibuildwheel.readthedocs.io/en/stable/faq/#emulation
.. _an os.exec function: https://docs.python.org/3/library/os.html#os.execl
.. _multiprocessing start method: https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
.. _Cython: http://docs.cython.org/en/latest/
.. _profiling: http://docs.cython.org/en/latest/src/tutorial/profiling_tutorial.html
