"""Templates to render reports in HTML."""
from functools import lru_cache
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Union

import jinja2
from markupsafe import Markup

from memray import MemorySnapshot
from memray import Metadata


@lru_cache(maxsize=1)
def get_render_environment() -> jinja2.Environment:
    loader = jinja2.PackageLoader("memray.reporters")
    env = jinja2.Environment(loader=loader)

    def include_file(name: str) -> Markup:
        """Include a file from the templates directory without
        interpolating its contents"""
        source, *_ = loader.get_source(env, name)
        return Markup(source)

    env.globals["include_file"] = include_file
    env.policies["json.dumps_kwargs"] = {"sort_keys": True, "separators": (",", ":")}
    return env


def get_report_title(
    *, kind: str, show_memory_leaks: bool, inverted: bool = False
) -> str:
    parts = []
    if inverted:
        parts.append("inverted")
    parts.append(kind)
    parts.append("report")
    if show_memory_leaks:
        parts.append("(memory leaks)")
    return " ".join(parts)


def render_report(
    *,
    kind: str,
    data: Union[Dict[str, Any], Iterable[Dict[str, Any]]],
    metadata: Metadata,
    memory_records: Iterable[MemorySnapshot],
    show_memory_leaks: bool,
    merge_threads: bool,
    inverted: bool,
) -> str:
    env = get_render_environment()
    template = env.get_template(kind + ".html")

    pretty_kind = kind.replace("_", " ")
    title = get_report_title(
        kind=pretty_kind,
        show_memory_leaks=show_memory_leaks,
        inverted=inverted,
    )
    return template.render(
        kind=pretty_kind,
        title=title,
        data=data,
        metadata=metadata,
        memory_records=memory_records,
        show_memory_leaks=show_memory_leaks,
        merge_threads=merge_threads,
        inverted=inverted,
    )
