.. note
    You should *NOT* add new change log entries to this file, this
    file is managed by towncrier. You *may* edit previous change logs to
    fix problems like typo corrections or such.

Changelog
=========

.. towncrier release notes start

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
