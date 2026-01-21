Attaching to a running process
==============================

Memray allows you to attach to a running process and to observe the allocations
it performs once you've attached. This **doesn't allow you to see where memory
was allocated before you attached to the process**, but it does allow you to
observe or record future allocations. This can be useful if an application is
continuing to request more memory than you think it should need, and you want
to figure out why. It can also be useful for observing the allocation patterns
of a long running process once the process has already completed any initial
warm up steps that it needs to do.

Basic Usage
-----------

The general form of the ``attach`` subcommand is:

.. code:: shell

    memray attach [options] <pid>

The only required argument for ``memray attach`` is a process ID to attempt to
attach to. You must be :ref:`able to attach a debugger <ptrace privs>` to that
process, and that process **must be a Python process**, and the Memray package
**must be installed in the environment that the process is running in**. That
is, ``memray attach`` will execute the Python statement ``import memray`` in
the process being attached to, and that import must succeed for attaching to
work.

By default this will open a :doc:`live mode TUI <live>` showing the allocations
that the process performs after you've attached, but you can instead provide
the name of a capture file to write to with the ``-o`` option, allowing you to
analyze the captured allocations with any Memray reporter you'd like. You can
also provide most of the options that ``memray run`` accepts. See :ref:`the
CLI reference <memray attach CLI reference>` for details.

If you use the ``-o`` option, the process will continue recording allocations
to the capture file even after ``memray attach`` has returned. Otherwise,
allocations are tracked only for as long as the :doc:`live mode TUI <live>`
continues running. Once you quit the TUI, the attached process will stop
tracking allocations. If you later reattach to the same process, it will start
from a clean slate, and will not be aware of any allocations seen during your
first TUI session.

.. _ptrace privs:

Debugger Privileges
-------------------

Memray leverages a debugger for attaching to the process. It is compatible with
both gdb and lldb, but one or the other must be installed in order for ``memray
attach`` to work. Only a super user (either root, or a user with the
``CAP_SYS_PTRACE`` capability) can attach to processes run by another user.
Further, security settings on modern Linux systems typically prevent a regular
user from attaching even to their own processes. You can loosen that
restriction by writing ``0`` to ``/proc/sys/kernel/yama/ptrace_scope`` as root,
allowing any user to attach to their own processes. When running a Docker
container, you can use ``--cap-add=SYS_PTRACE`` to allow attaching to processes
within the container.

.. warning::

   Allowing arbitrary processes to be traced `is insecure
   <https://www.kernel.org/doc/html/latest/admin-guide/LSM/Yama.html>`_, as it
   provides an easy vector for privilege escalation within a remote code
   execution attack. Be sure to consider the security implications before you
   choose to grant regular users the ability to attach to processes.

In some cases (like MacOS), the debugger may require you to authenticate with
your username and password in order to attach to a process. In that case it is
possible that a window will pop up asking for your password or for biometric
authentication.

Caveats
-------

``memray attach`` works by injecting executable code into a running process.
We've tried to do this in the safest way possible, but we can't guarantee that
there aren't edge cases where this might crash or deadlock the process that
you're attempting to attach to, depending on what it's doing at the point when
we attach. We advise only using this as a debugging tool on development
machines.

If you attach to a Python 3.7 or Python 3.8 process that has never imported the
``threading`` module, the attached process will show an error when the
interpreter finishes running the main script. This is due to `a known bug
<https://github.com/python/cpython/issues/81597>`_ that was not fixed until
Python 3.9. From Python 3.9 onwards there will be no error on exit, but the
interpreter will assign the wrong name to the main thread if ``threading`` is
later imported by the script. That should not have any major effect on the
behavior of the program.

If you do find some case where ``memray attach`` either doesn't work or causes
a crash or deadlock, we want to hear about it! Please `file a bug report`_
explaining what went wrong. If the issue is reproducible, please try running
``memray attach`` with the ``--verbose`` flag, which outputs a lot of extra
debugging information, including the output of the debugger session that was
used to inject our code into the remote process. If the process crashed and
left a core file, please include a stack trace of all of the threads in the
process, so that we can understand what state it was in when we tried to
attach. You can show all threads' stacks using ``thread apply all bt`` in gdb
or ``thread backtrace all`` in lldb.

.. _file a bug report: https://github.com/bloomberg/memray/issues/new?assignees=&labels=bug&template=---bug-report.yaml

CLI Reference
-------------

.. _memray attach cli reference:

memray attach
^^^^^^^^^^^^^

.. argparse::
    :ref: memray.commands.get_argument_parser
    :path: attach
    :prog: memray
    :nodefaultconst:
    :noepilog:

memray detach
^^^^^^^^^^^^^

.. argparse::
    :ref: memray.commands.get_argument_parser
    :path: detach
    :prog: memray
    :nodefaultconst:
