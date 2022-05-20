.. note
    You should *NOT* add new change log entries to this file, this
    file is managed by towncrier. You *may* edit previous change logs to
    fix problems like typo corrections or such.

Changelog
=========

.. towncrier release notes start

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
