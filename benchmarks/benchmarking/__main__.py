import dataclasses
import json
import pathlib
import subprocess
import sys
import tempfile
from typing import List

from .plot import plot_diff

CASES_DIR = pathlib.Path(__file__).parent / "cases"
RESULTS_DIR = pathlib.Path(__file__).parent / "results"
DOCUTILS_DATA = pathlib.Path(__file__).parent / "cases" / "docutils_data" / "docs"
TELCO_DATA = pathlib.Path(__file__).parent / "cases" / "telco_data" / "telco-bench.b"


@dataclasses.dataclass
class Case:
    name: str
    file_name: str
    arguments: List[str] = dataclasses.field(default_factory=list)

    def run_case(
        self,
        run_name: str,
        template_file: pathlib.Path,
        tracker_options: str,
        results_file: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdirname:
            case_file = pathlib.Path(tmpdirname) / f"{self.file_name}.py"
            code = template_file.read_text()
            case_file.write_text(code)

            helper_file = pathlib.Path(tmpdirname) / "memray_helper.py"
            helper_code = (
                "import memray\nimport contextlib\n"
                f"def get_tracker():\n    return {tracker_options}"
            )
            helper_file.write_text(helper_code)

            results_file = RESULTS_DIR / results_file
            print(f"Running {self.name} with arguments {self.arguments} - {run_name}")
            subprocess.run(
                [sys.executable, case_file, "-o", results_file] + self.arguments,
                check=True,
            )

    def run(self) -> None:
        template_file = CASES_DIR / f"{self.file_name}_memray.py"
        if not template_file.exists():
            raise ValueError(f"Case {self.name} does not exist.")

        self.run_case(
            "", template_file, "contextlib.nullcontext()", f"{self.name}.json"
        )

        self.run_case(
            "memray base",
            template_file,
            "memray.Tracker('/dev/null')",
            f"{self.name}_memray.json",
        )

        self.run_case(
            "memray python allocators",
            template_file,
            "memray.Tracker('/dev/null', trace_python_allocators=True)",
            f"{self.name}_memray_python_allocators.json",
        )

        self.run_case(
            "memray python native",
            template_file,
            "memray.Tracker('/dev/null', native_traces=True)",
            f"{self.name}_memray_python_native.json",
        )

        self.run_case(
            "memray python all",
            template_file,
            "memray.Tracker('/dev/null', trace_python_allocators=True, native_traces=True)",
            f"{self.name}_memray_python_all.json",
        )


CASES = [
    Case("docutils", "docutils_html", [f"--doc_root={DOCUTILS_DATA}"]),
    Case("raytrace", "raytrace", []),
    Case("fannkuch", "fannkuch", []),
    Case("pprint", "pprint_format", []),
    Case("mdp", "mdp", []),
    Case("async_tree", "async_tree", ["none"]),
    Case("async_tree_io", "async_tree", ["io"]),
    Case("async_tree_mem", "async_tree", ["memoization"]),
    Case("async_tree_cpu_io", "async_tree", ["cpu_io_mixed"]),
    Case("deltablue", "deltablue", []),
    Case("nbody", "nbody", []),
    Case("nqueens", "nqueens", []),
    Case("regex_dna", "regex_dna", []),
    Case("go", "go", []),
    Case("hexion", "hexion", []),
    Case("meteor_context", "meteor_context", []),
    Case("json_dumps", "json_dumps", []),
    Case("json_loads", "json_loads", []),
    Case(
        "picke_pure_python",
        "pickles",
        [
            "pickle",
            "--pure-python",
        ],
    ),
    Case("picke", "pickles", ["pickle"]),
    Case(
        "unpicke_pure_python",
        "pickles",
        [
            "unpickle",
            "--pure-python",
        ],
    ),
    Case("unpicke", "pickles", ["unpickle"]),
    Case(
        "pickle_list_pure_python",
        "pickles",
        [
            "pickle_list",
            "--pure-python",
        ],
    ),
    Case("pickle_list", "pickles", ["pickle_list"]),
    Case(
        "unpickle_list_pure_python",
        "pickles",
        [
            "unpickle_list",
            "--pure-python",
        ],
    ),
    Case("unpickle_list", "pickles", ["unpickle_list"]),
    Case(
        "pickle_dict_pure_python",
        "pickles",
        [
            "pickle_dict",
            "--pure-python",
        ],
    ),
    Case("pickle_dict", "pickles", ["pickle_dict"]),
    Case("spectral_norm", "spectral_norm", []),
    Case("telco", "telco", [f"--doc_root={TELCO_DATA}"]),
    Case("sqlite_synth", "sqlite_synth", []),
    Case("regex_v8", "regex_v8", []),
    Case("regex_effbot", "regex_effbot", []),
    Case("regex_effbot_bytes", "regex_effbot", ["--force_bytes"]),
]


@dataclasses.dataclass
class BenchmarkResult:
    name: str
    data: List


def gather_benchmarks(cases):
    results = []
    names = ("", "Defaut", "Python allocators", "Native", "Python allocators + Native")
    extensions = (
        "",
        "_memray",
        "_memray_python_allocators",
        "_memray_python_native",
        "_memray_python_all",
    )
    for name, extension in zip(names, extensions):
        type_results = []
        for case in cases:
            memray_results_file = RESULTS_DIR / f"{case.name}{extension}.json"
            data = json.loads(memray_results_file.read_text())
            type_results.append(data)
        results.append(BenchmarkResult(name=name, data=type_results))
    return results


if __name__ == "__main__":
    # if RESULTS_DIR.exists():
    #     raise RuntimeError(f"Results directory {RESULTS_DIR} already exists")

    # RESULTS_DIR.mkdir()

    for case in CASES:
        case.run()

    base_results, *memray_results = gather_benchmarks(CASES)
    for memray_result in memray_results:
        plot_diff(
            memray_result,
            base_results,
            f"plot_{memray_result.name}.png".replace(" ", "_").lower(),
            f"Overhead of Memray with {memray_result.name}",
        )
