from __future__ import annotations

import typing
from importlib import import_module

from memray._vendor.textual.case import camel_to_snake

# For any new built-in Widget we create, not only do we have to import them here and add them to `__all__`,
# but also to the `__init__.pyi` file in this same folder - otherwise text editors and type checkers won't
# be able to "see" them.
if typing.TYPE_CHECKING:
    from memray._vendor.textual.widget import Widget
    from memray._vendor.textual.widgets._button import Button
    from memray._vendor.textual.widgets._checkbox import Checkbox
    from memray._vendor.textual.widgets._collapsible import Collapsible
    from memray._vendor.textual.widgets._content_switcher import ContentSwitcher
    from memray._vendor.textual.widgets._data_table import DataTable
    from memray._vendor.textual.widgets._digits import Digits
    from memray._vendor.textual.widgets._directory_tree import DirectoryTree
    from memray._vendor.textual.widgets._footer import Footer
    from memray._vendor.textual.widgets._header import Header
    from memray._vendor.textual.widgets._help_panel import HelpPanel
    from memray._vendor.textual.widgets._input import Input
    from memray._vendor.textual.widgets._key_panel import KeyPanel
    from memray._vendor.textual.widgets._label import Label
    from memray._vendor.textual.widgets._link import Link
    from memray._vendor.textual.widgets._list_item import ListItem
    from memray._vendor.textual.widgets._list_view import ListView
    from memray._vendor.textual.widgets._loading_indicator import LoadingIndicator
    from memray._vendor.textual.widgets._log import Log
    from memray._vendor.textual.widgets._markdown import Markdown, MarkdownViewer
    from memray._vendor.textual.widgets._masked_input import MaskedInput
    from memray._vendor.textual.widgets._option_list import OptionList
    from memray._vendor.textual.widgets._placeholder import Placeholder
    from memray._vendor.textual.widgets._pretty import Pretty
    from memray._vendor.textual.widgets._progress_bar import ProgressBar
    from memray._vendor.textual.widgets._radio_button import RadioButton
    from memray._vendor.textual.widgets._radio_set import RadioSet
    from memray._vendor.textual.widgets._rich_log import RichLog
    from memray._vendor.textual.widgets._rule import Rule
    from memray._vendor.textual.widgets._select import Select
    from memray._vendor.textual.widgets._selection_list import SelectionList
    from memray._vendor.textual.widgets._sparkline import Sparkline
    from memray._vendor.textual.widgets._static import Static
    from memray._vendor.textual.widgets._switch import Switch
    from memray._vendor.textual.widgets._tabbed_content import TabbedContent, TabPane
    from memray._vendor.textual.widgets._tabs import Tab, Tabs
    from memray._vendor.textual.widgets._text_area import TextArea
    from memray._vendor.textual.widgets._tooltip import Tooltip
    from memray._vendor.textual.widgets._tree import Tree
    from memray._vendor.textual.widgets._welcome import Welcome

__all__ = [
    "Button",
    "Checkbox",
    "Collapsible",
    "ContentSwitcher",
    "DataTable",
    "Digits",
    "DirectoryTree",
    "Footer",
    "Header",
    "HelpPanel",
    "Input",
    "KeyPanel",
    "Label",
    "Link",
    "ListItem",
    "ListView",
    "LoadingIndicator",
    "Log",
    "Markdown",
    "MarkdownViewer",
    "MaskedInput",
    "OptionList",
    "Placeholder",
    "Pretty",
    "ProgressBar",
    "RadioButton",
    "RadioSet",
    "RichLog",
    "Rule",
    "Select",
    "SelectionList",
    "Sparkline",
    "Static",
    "Switch",
    "Tab",
    "TabbedContent",
    "TabPane",
    "Tabs",
    "TextArea",
    "Tooltip",
    "Tree",
    "Welcome",
]

_WIDGETS_LAZY_LOADING_CACHE: dict[str, type[Widget]] = {}


# Let's decrease startup time by lazy loading our Widgets:
def __getattr__(widget_class: str) -> type[Widget]:
    try:
        return _WIDGETS_LAZY_LOADING_CACHE[widget_class]
    except KeyError:
        pass

    if widget_class not in __all__:
        raise AttributeError(
            f"Package 'memray._vendor.textual.widgets' has no class '{widget_class}'"
        )

    widget_module_path = f"._{camel_to_snake(widget_class)}"
    module = import_module(
        widget_module_path, package="memray._vendor.textual.widgets"
    )
    class_ = getattr(module, widget_class)

    _WIDGETS_LAZY_LOADING_CACHE[widget_class] = class_
    return class_
