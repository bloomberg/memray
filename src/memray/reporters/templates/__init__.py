"""Templates to render reports in HTML."""
from functools import lru_cache
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Union

import jinja2

from memray import MemorySnapshot
from memray import Metadata


@lru_cache(maxsize=1)
def get_render_environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("memray.reporters"),
    )
    env.policies["json.dumps_kwargs"] = {"sort_keys": True, "separators": (",", ":")}
    return env


def get_report_title(*, kind: str, show_memory_leaks: bool) -> str:
    if show_memory_leaks:
        return f"{kind} report (memory leaks)"
    return f"{kind} report"


def render_report(
    *,
    kind: str,
    data: Union[Dict[str, Any], Iterable[Dict[str, Any]]],
    metadata: Metadata,
    memory_records: Iterable[MemorySnapshot],
    show_memory_leaks: bool,
    merge_threads: bool,
) -> str:
    env = get_render_environment()
    template = env.get_template(kind + ".html")

    pretty_kind = kind.replace("_", " ")
    title = get_report_title(kind=pretty_kind, show_memory_leaks=show_memory_leaks)
    return template.render(
        kind=pretty_kind,
        title=title,
        data=data,
        metadata=metadata,
        memory_records=memory_records,
        show_memory_leaks=show_memory_leaks,
        merge_threads=merge_threads,
    )
