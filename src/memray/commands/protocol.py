try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore
import argparse


class Command(Protocol):
    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        ...

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        ...
