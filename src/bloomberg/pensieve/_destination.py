import pathlib
import typing
from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    pass


@dataclass(frozen=True)
class FileDestination(Destination):
    path: typing.Union[pathlib.Path, str]


@dataclass(frozen=True)
class SocketDestination(Destination):
    port: int
    host: typing.Optional[str] = "127.0.0.1"
