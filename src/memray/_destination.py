import pathlib
import typing
from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    pass


@dataclass(frozen=True)
class FileDestination(Destination):
    path: typing.Union[pathlib.Path, str]
    exist_ok: bool = False


@dataclass(frozen=True)
class SocketDestination(Destination):
    port: int
    host: typing.Optional[str] = "127.0.0.1"
