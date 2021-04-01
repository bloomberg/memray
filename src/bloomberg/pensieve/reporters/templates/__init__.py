"""Templates to render reports in HTML."""

from functools import lru_cache
from typing import Any
from typing import Dict

import jinja2


@lru_cache(maxsize=1)
def get_render_environment() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader("bloomberg.pensieve.reporters"),
    )


def render_report(*, kind: str, data: Dict[str, Any]) -> str:
    env = get_render_environment()
    template = env.get_template(kind + ".html")
    return template.render(kind=kind, data=data)
