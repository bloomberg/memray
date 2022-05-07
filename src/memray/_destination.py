import pathlib
import typing
from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    pass


@dataclass(frozen=True)
class FileDestination(Destination):
    """Specify an output file to write captured allocations into.

    Args:
        path: The path to the output file.
        overwrite: By default, if a file already exists at that path an
            exception will be raised. If you provide ``overwrite=True``, then
            the existing file will be overwritten instead.
    """

    path: typing.Union[pathlib.Path, str]
    overwrite: bool = False
    compress_on_exit: bool = True


@dataclass(frozen=True)
class SocketDestination(Destination):
    """Specify a port to serve captured allocations on.

    When a ``SocketDestination`` is passed to the `Tracker` constructor, the
    process will immediately create a server socket on the given port and wait
    for a reader to connect (see :ref:`Live Tracking`). The `Tracker`
    constructor will not return until a client has connected. Any records the
    tracker goes on to capture will be written over the socket to the attached
    client.

    Args:
        server_port: The port to accept a client connection on.
        address: The address to bind the server socket to. This should
            generally be left alone, but you might want to use ``"0.0.0.0"`` to
            accept connections from clients on other machines. Note that
            sending records to clients on other machines is generally a bad
            idea, though. In particular, this won't play nicely with
            :ref:`Native Tracking`, because the client on the remote machine
            won't have access to the shared libraries used by the tracked
            process.
    """

    server_port: int
    address: str = "127.0.0.1"
