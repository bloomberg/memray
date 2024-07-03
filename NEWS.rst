.. note
    You should *NOT* add new change log entries to this file, this
    file is managed by towncrier. You *may* edit previous change logs to
    fix problems like typo corrections or such.

Changelog
=========

.. towncrier release notes start

memray 1.13.3 (2024-07-02)
--------------------------

Bug Fixes
~~~~~~~~~

- Fix a bug that could result in truncated reports for applications that fork without calling :c:func:`PyOS_BeforeFork`, including by using `multiprocessing` with the "spawn" start method (the default on macOS). (#644)


memray 1.13.2 (2024-06-27)
--------------------------

Bug Fixes
~~~~~~~~~

- Fix a bug that could in rare circumstances result in a stack overflow while processing native mode stacks. (#639)


Miscellaneous
~~~~~~~~~~~~~

- Upgrade our vendored copy of ``libbacktrace``, used for reporting native stacks, to the latest version. (#639)


memray 1.13.1 (2024-06-23)
--------------------------

Bug Fixes
~~~~~~~~~

- Fix a deadlock that could occur on some Linux systems when resolving debug information using debuginfod. (#634)


memray 1.13.0 (2024-06-18)
--------------------------

Features
~~~~~~~~

- Add :doc:`a tutorial <tutorials/index>` to the Memray documentation. (#590)
- Include the thread name in the live TUI. (#562)
- Capture the name attribute of Python `threading.Thread` objects. (#562)
- Allow using Ctrl+Z to suspend ``memray tree`` and the live mode TUI. (#581)
- Add a button in the live-mode TUI to show allocations from all threads at once. (#589)
- Vendor ``libdebuginfod`` into our Linux wheels, so that debuginfod integration can be used without any dependency on system-installed libraries. (#592)


Bug Fixes
~~~~~~~~~

- Fix dynamic toggling between descriptions like "Pause" vs "Unpause" or "Show" vs "Hide" in the footer of the live-mode TUI and tree reporter. This was broken by changes introduced in Textual 0.61 (and again by Textual 0.63). (#597)
- Correctly localize the start and end time in the "Stats" modal when an HTML report was generated on a different machine than the one it is being displayed on. (#611)
- Fix a crash in old macOS versions (<11.0) due to the inavailability of some linker cache APIs. (#615)
- Fix reporting of "Own Memory" in the ``live`` and ``summary`` reporters. A bug in our summation caused us to undercount functions' direct allocations. (#617)


Miscellaneous
~~~~~~~~~~~~~

- Builds from source now work for Python 3.13. Wheels are not yet published for 3.13 because it is not yet ABI stable. (#622)
- Link our Linux wheels against the latest version of ``elfutils``. (#592)


memray 1.12.0 (2024-03-07)
--------------------------

Features
~~~~~~~~

- Allow ``--temporal`` and ``--max-memory-records`` to be used with our :ref:`Jupyter magic <Jupyter integration>`. (#538)
- Automatically use aggregated capture files for the :ref:`Jupyter magic <Jupyter integration>` whenever possible, reducing the amount of disk space needed for temporary files. (#538)
- Expose the main thread id in the FileReader's metadata attribute. (#560)


Bug Fixes
~~~~~~~~~

- Fix a bug that was causing ``dlopen`` to not load shared libraries that have an RPATH/RUNPATH set. (#525)
- Fix a bug where the tree reporter would fail to populate the code pane with relevant lines if the line where the allocation occurred was too near the start of the file. (#544)
- Fix a bug causing the first entry of ``sys.path`` to be erroneously overwritten by ``memray run`` when the Python interpreter was launched with the ``-I`` or ``-P`` flag, or when the ``PYTHONSAFEPATH`` environment variable was set. (#552)


memray 1.11.0 (2023-12-04)
--------------------------

Features
~~~~~~~~

- Migrate the  :doc:`live TUI <live>` to Textual. This provides a greatly improved user experience, including the ability to scroll to view rows that don't fit on the screen. (#274)
- Add a new documentation page to serve as :ref:`an overview of memory concepts <memory overview>`, to help users better interpret the memory profiles provided by Memray. (#496)
- Where possible, leverage ``pkg-config`` when building the extension from source, picking up appropriate compiler and linker flags automatically. (#498)
- Port the tree reporter to be an interactive Textual App. (#499)


Bug Fixes
~~~~~~~~~

- Fixed a bug that caused ``memray attach`` to fail with newer LLDB versions, including on macOS Sonoma. (#490)
- Limit the number of memory records displayed in reporters by default. This will help displaying flamegraphs for long capture sessions. (#491)
- When generating a ``--leaks`` flamegraph, don't show a warning that the ``pymalloc`` allocator is in use if ``--trace-python-allocators`` was used when generating the capture file. (#492)
- Ensure that we update our terminal progress bars to 100% when processing finishes. (#494)


memray 1.10.0 (2023-10-05)
--------------------------

Features
~~~~~~~~

- Add support for :ref:`inverted flame graphs`. In an inverted flame graph, the
  roots are the functions that allocated memory, and the children of any given
  node represent the percentage of that node's allocations that can be attributed
  to a particular caller. The inverted flame graph is very helpful in analyzing
  where memory is being spent in aggregate. You can generate one by passing the
  ``--inverted`` flag to ``memray flamegraph``. (#439)
- ``memray attach`` now supports ``--aggregate`` to produce :ref:`aggregated capture files <aggregated capture files>`. (#455)
- ``memray attach`` has been enhanced to allow tracking for only a set period of
  time. (#458)
- A new ``memray detach`` command allows you to manually deactivate tracking that
  was started by a previous call to ``memray attach``. (#458)
- Python 3.12 is now supported. (#474)


Bug Fixes
~~~~~~~~~

- Update ``memray attach`` on Linux to prefer GDB over LLDB for injecting itself into the process being attached to. We've had several reports of problems with the Linux LLDB, and hope this change will help give Linux users a better experience by default. You can still explicitly use LLDB on Linux even when GDB is detected by running ``memray attach --method=lldb``. (#449)
- Fix a memory leak in Memray itself when many different capture files are opened by a single Memray process and native stacks are being reported. This issue primarily affected ``pytest-memray``. (#473)
- Fix a crash in MacOS Sonoma when using system Framework libraries, like when using the ``pyobjc`` library. (#477)


memray 1.9.1 (2023-08-01)
-------------------------

Bug Fixes
~~~~~~~~~

- Fix an issue that stopped Memray's experimental support for ``greenlet`` from working with versions of the ``greenlet`` module older than 1.0. (#432)
- Fix a bug leading to a deadlock when Memray is used to profile an application that uses the jemalloc implementation of ``malloc``. (#433)
- Fix a bug causing the ``summary`` reporter to generate empty reports. (#435)


memray 1.9.0 (2023-07-28)
-------------------------

Features
~~~~~~~~

- Allow to report the current version of Memray via a ``--version/-V`` command line parameter (#420)
- Add pause/unpause keybindings to the live reporter that allows the user to pause the live reporter to analyse the current results without pausing the running program (#418)


Bug Fixes
~~~~~~~~~

- Support building with Cython 3 (#425)


memray 1.8.1 (2023-06-20)
-------------------------

Features
~~~~~~~~

- When the high water mark being shown by a temporal flame graph is before the first memory snapshot or after the last one, tell the user so by highlighting a region beyond the end of the memory usage plot. (#399)


Bug Fixes
~~~~~~~~~

- Prevent a totally empty memory plot from being shown on flame graphs when the tracked process completes before any periodic memory snapshots are captured. (#399)
- Fix a bug that prevented the temporal high water mark flame graph from showing the flame graph of a high water mark that occurred after the final periodic memory snapshot was captured. (#399)
- Fix a bug that prevented Memray from intercepting functions in shared objects that are part of the dyld shared cache in macOS Ventura. (#401)


memray 1.8.0 (2023-06-09)
-------------------------

Features
~~~~~~~~

- Allow ``memray stats`` to output a JSON report via ``--json`` flag. (#377)
- We now publish x86-64 musllinux_1_1 wheels, compatible with Alpine Linux. (#379)
- We now support :ref:`temporal flame graphs`, which provide an exciting new way of analyzing your process's memory usage over time. (#391)


Bug Fixes
~~~~~~~~~

- Fix a bug where a non-import call on the same line as an ``import`` statement would be hidden by the "Hide Import System Frames" checkbox of a flame graph. (#329)
- Fixed a bug that was hitting an assert when constructing hybrid stack frames in Python 3.11 when no eval symbols are available. (#334)
- Change the font color used by the ``%%memray_flamegraph`` Jupyter magic's progress updates for better contrast on the JupyterLab dark theme. (#344)
- Fix a bug that could result in a deadlock when tracking a process linked against an old version of musl libc. (#379)


memray 1.7.0 (2023-02-21)
-------------------------

Features
~~~~~~~~

- ``memray run`` now supports ``--aggregate`` to produce :ref:`aggregated capture files <aggregated capture files>`, which can be much smaller but aren't able to be used for generating every type of report. (#277)
- Add integration with debuginfod to automatically download debug information for binaries if it is available. (#308)
- Flame graphs produced by ``memray flamegraph`` are now around 85% smaller. (#314)


Bug Fixes
~~~~~~~~~

- ``memray run --live`` and ``memray run --live-remote`` silently dropped the ``--trace-python-allocators`` flag. This has been fixed, and the flag is now properly propagated from the CLI to the tracker. (#283)
- Fix a bug that was causing Memray to crash when the Tracker is being destroyed and some other thread is still registering allocations or deallocations (#289)
- Work around `a bug in GDB versions before 10.1 <https://sourceware.org/git/?p=binutils-gdb.git;a=commit;h=da1df1db9ae43050c8de62e4842428ddda7eb509>`_ that could cause ``memray attach`` to fail. (#310)
- Work around `a bug in LLDB on Linux <https://github.com/llvm/llvm-project/issues/60408>`_ that could cause ``memray attach`` to hang. (#311)


memray 1.6.0 (2023-01-17)
-------------------------

Features
~~~~~~~~

- Speed up native allocation tracking by up to 45% (#294)


Bug Fixes
~~~~~~~~~

- ``memray run --live`` and ``memray run --live-remote`` silently dropped the ``--trace-python-allocators`` flag. This has been fixed, and the flag is now properly propagated from the CLI to the tracker. (#283)
- Fix a bug that was causing Memray to crash when the Tracker is being destroyed and some other thread is still registering allocations or deallocations (#289)


Memray 1.5.0 (2022-12-09)
-------------------------

Features
~~~~~~~~

- Memray is now fully supported on macOS, and the warnings that macOS support is experimental have been dropped. (#194)
- Add a checkbox to flamegraphs that allows hiding frames from the import system (#261)
- ``memray attach`` can be used to :doc:`attach to a running process <attach>` (#266)
- Consider frames from the import system as "irrelevant" in the generated flamegraphs. (#268)


memray 1.4.1 (2022-11-11)
-------------------------

Bug Fixes
~~~~~~~~~

- Fix a crash that can happen when two different threads try to register frames at the same time without the GIL held. (#251)


memray 1.4.0 (2022-10-31)
-------------------------

Features
~~~~~~~~

- Add a new ``transform`` subcomand that allows transforming Memray capture files into output files compatible with other tools. We're starting by supporting conversions to the *gprof2dot* format, which allows producing graph-like reports when combined with *graphviz*. (#200)
- Added a new ``--temporary-allocations`` option to the ``flamegraph``, ``table``, ``tree``, and ``summary`` reporters for showing the :doc:`temporary allocations </temporary_allocations>` instead of the high water mark ones. (#201)
- When the ``greenlet`` module is in use, also assign a distinct thread ID to each greenlet. Greenlets aren't threads, but they are distinct threads of execution within a single process, with distinct stacks, so assigning different thread IDs to each makes it easier to interpret reports where ``greenlet`` was used. (#209)
- Use a monotonic counter to generate thread IDs, rather than using the pthread ID. Those pthread IDs can be reused, making it difficult to tell what thread performed an allocation. (#209)
- Print a warning when we detect that the Python interpreter was built without debug information or without symbols, letting the user know in advance that these conditions may result in incorrect stack traces or missing filenames and line numbers. (#211)
- A new ``%%memray_flamegraph`` Jupyter cell magic is provided by ``%load_ext memray``, and can be used to memory profile code directly in a Jupyter notebook. (#237)
- Add ``csv`` as a possible target format for ``memray transform``, producing a report of all of the allocations that made up the process's high water mark of allocated memory. This CSV file can then be loaded and analyzed using libraries like ``pandas``. (#241)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Up until now, if the program being profiled included a Cython module built with profiling support enabled, those Cython functions would show up in our Python call stacks. This was rarely useful in practice, as most Cython libraries aren't distributed with profiling support enabled, and supporting this had a surprisingly high maintenance cost. We've removed this integration, so you'll need to use ``--native`` mode to see inside of Cython modules. We are not considering this a backwards-incompatible change, since it does not affect any of our public interfaces (though it could affect the contents of reports generated by Memray). (#206)


Bug Fixes
~~~~~~~~~

- Fix a bug that caused incorrect ``--native`` mode stacks on Python 3.11 for allocations performed directly by the interpreter's eval loop. (#209)
- Fix a crash when an extension module terminates the program using non-Python APIs under tracking. (#228)


memray 1.3.1 (2022-08-30)
-------------------------

Bug Fixes
~~~~~~~~~

- Prevent a crash that could occur when forked processes that have been under tracking without ``follow_fork=True`` remove the profiling function with pending frames needed to be flushed to the results file. (#196)


memray 1.3.0 (2022-08-18)
-------------------------

Features
~~~~~~~~

- We now capture Python stacks for allocations made by threads that existed before the Memray tracker was started. (#130)
- Add support for Python 3.11 (#138)
- Add support for MacOS. (#174)
- Add experimental support for Greenlet. (#185)


Bug Fixes
~~~~~~~~~

- Prevent a crash that could occur if the Memray API was used to stop and later restart tracking while another thread was running Python code. (#152)
- Prevent a use-after-free bug that could result in a crash if ``sys.setprofile()`` was called while Memray was tracking. Now if ``sys.setprofile()`` is called, all future allocations on that thread will report unknown Python stacks, instead of potentially incorrect stacks. (#176)


Memray 1.2.0 (2022-07-11)
-------------------------

Features
~~~~~~~~

- Add a progress bar indicator to the record processing phases in the different reporters so users can have an approximate idea of how much time processing the result files will take. (#111)
- The ``memray stats`` reporter is now up to 50% faster, and its output is easier to interpret because it now processes all allocations by default. (#136)
- Add a line showing the heap size over time to the memory plot in the html-based reporters (which already showed the resident size over time). (#142)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Remove the ``--include-all-allocations`` / ``-a`` argument to the ``memray stats`` reporter. Previously this was too slow to be used by default, but now that it has been sped up, it doesn't make sense to use anything else. The old default behavior of only processing allocations that made up the high water mark of the application's memory usage was confusing and misleading. (#136)


Bug Fixes
~~~~~~~~~

- Fix a crash with SIGBUS when the file system fills up while ``memray run`` is writing a capture file. (#117)
- Recognize when a capture file has been truncated (most likely because the tracked process was killed unexpectedly) and ignore any incomplete record at the end of the file. (#129)
- Fix the histogram used by the ``memray stats`` reporter to choose sane bin sizes when all captured allocations are the same size. (#133)
- Fix the aggregation by location at the bottom of the ``memray stats`` report when the ``--include-all-allocations`` option is used. (#134)
- Fix a bug causing deallocations with ``free`` and ``munmap`` to be included in the reported "Total allocations" count of ``memray stats --include-all-allocations``. (#136)
- Fix the two "largest allocating locations" sections in the ``memray stats`` report to actually aggregate by location. Previously they were aggregating by distinct stacks, so if two different paths hit the same line of code, it would be counted separately instead of together. (#136)
- Fix a bug causing memory freed by ``munmap`` to be incorrectly added into the reported "Total memory allocated" of ``memray stats --include-all-allocations``. (#136)
- Exclude ``PYMALLOC_FREE`` from the allocator type distribution (other deallocators were already being ignored, but this recently added one was missed). (#136)
- Fix the ``memray stats`` histogram to be based on the actual sizes of all allocations. Previously it only saw the sizes after a rollup by stack had already been performed, so it was binning allocation sizes that had already been summed. (#136)
- Fixed a bug where aggregating native call stacks could give misleading results on aarch64 under some circumstances. (#141)
- Fix a bug that made ``memray run --live -c`` fail if the command to run contained double quotes. (#147)
- Ensure our TUI isn't displaying stale data by periodically flushing the latest available data from the tracker (rather than only flushing when a buffer fills up). (#147)
- Fix the handling of the thread switch commands in the live mode TUI before the first allocation has been seen. (#147)


memray 1.1.0 (2022-05-16)
-------------------------

Features
~~~~~~~~

- Finalize and document the Memray :doc:`tracking API <api>`. (#42)
- Ensure that wheels built by ``make dist`` are reproducible (so that running the build twice produces identical artifacts). (#47)
- Reduce the size of the ``memray run`` capture file by around 20% by using a more efficient encoding for which allocator was used to perform a given allocation and whether we :ref:`captured a native stack <native tracking>` for that allocation. (#52)
- Support ``memray run -c "..."`` to profile an in-line script provided on the command line. (#61)
- The capture files produced by ``memray run`` are now around 90% smaller thanks to a more efficient encoding scheme for the binary files. (#67)
- Add support for Alpine Linux and musl libc. (#75)
- Capture allocations made through the C99 ``aligned_alloc`` function. (#79)
- By default the capture file will now be compressed using LZ4 after tracking completes. This temporarily requires extra disk space while the compression runs, but results in roughly 75% less disk space required in the end. Compression can be disabled with ``--no-compress``. (#82)
- Speed up tracking by around 5% by building with link-time optimization (LTO). (#91)
- Add a new ``--trace-python-allocators`` option to ``memray run`` that allows tracking all allocations made using the Python allocators. This will result in bigger output files and slower profiling but it allows getting insights about all of the interpreter's memory allocations. (#92)


Bug Fixes
~~~~~~~~~

- Previously we attempted to read all allocation records into memory when processing a capture file in our reporters. This could fail on large files, so now we process the file in a streaming fashion instead. (#62)
- Make ``memray run`` perform the same modifications to `sys.path` as the interpreter itself would when running a script. (#86)
- Fixed a bug in the :doc:`stats reporter <stats>` that could result in the largest allocations being omitted from the histogram. (#95)
- Fixed a bug that caused Memray reporters to display incorrect stacks when :ref:`native tracking` was enabled and native allocations from different locations occurred underneath the same Python stack. (#96)


Miscellaneous
~~~~~~~~~~~~~

- Support the latest versions of Rich (previously we pinned to an old version due to some formatting changes in more recent versions). (#98)


memray 1.0.3 (2022-04-21)
-------------------------

Features
~~~~~~~~

- Add ``memray`` as a command line entry point. (#20)

memray 1.0.2 (2022-04-12)
-------------------------

Features
~~~~~~~~

- Add publishing of ManyLinux2010 wheels for 64 and 32 bit systems. (#2)

Bug Fixes
~~~~~~~~~

- Fix 32 bit builds. (#2)


memray 1.0.0 (2022-04-09)
-------------------------

-  Initial release.
