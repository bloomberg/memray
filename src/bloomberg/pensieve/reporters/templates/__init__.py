"""Templates to render reports in HTML."""
from functools import lru_cache
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Union

import jinja2

from bloomberg.pensieve import Metadata


@lru_cache(maxsize=1)
def get_render_environment() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader("bloomberg.pensieve.reporters"),
    )


def render_report(
    *,
    kind: str,
    data: Union[Dict[str, Any], Iterable[Dict[str, Any]]],
    metadata: Metadata,
    show_memory_leaks: bool,
    merge_threads: bool,
) -> str:
    env = get_render_environment()
    template = env.get_template(kind + ".html")
    return template.render(
        kind=kind,
        title=f"{kind} report",
        data=data,
        metadata=metadata,
        show_memory_leaks=show_memory_leaks,
        merge_threads=merge_threads,
    )
