import dataclasses
from typing import Any
from typing import Dict
from typing import Tuple
from typing import Union

from textual import binding
from textual.app import App
from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import Footer

# In Textual 0.61, `App.namespace_bindings` was removed in favor of
# `Screen.active_bindings`. The two have a slightly different interface:
# a 2 item `tuple` was updated to a 3 item `namedtuple`.
# The `Bindings` type alias shows the two possible structures.
# The `update_key_description` implementation works for both,
# since we still support Textual versions below 0.61.

Bindings = Union[Dict[str, "binding.ActiveBinding"], Dict[str, Tuple[DOMNode, Binding]]]


def update_key_description(bindings: Bindings, key: str, description: str) -> None:
    val = bindings[key]
    binding = dataclasses.replace(val[1], description=description)
    if type(val) is tuple:
        bindings[key] = val[:1] + (binding,) + val[2:]  # type: ignore
    else:
        bindings[key] = val._replace(binding=binding)  # type: ignore


def redraw_footer(app: App[Any]) -> None:
    footer = app.query_one(Footer)
    if hasattr(footer, "recompose"):
        # Added in Textual v0.53
        footer.refresh(recompose=True)
    else:  # pragma: no cover
        # Hack: trick the Footer into redrawing itself
        footer.highlight_key = "q"  # type: ignore[attr-defined]
        footer.highlight_key = None  # type: ignore[attr-defined]
