import asyncio
import datetime
from io import StringIO
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple
from typing import cast

import pytest
from rich import print as rprint
from textual.app import App
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import DataTable
from textual.widgets import Label

import memray.reporters.tui
from memray import AllocationRecord
from memray import AllocatorType
from memray.reporters.tui import Location
from memray.reporters.tui import MemoryGraph
from memray.reporters.tui import Snapshot
from memray.reporters.tui import SnapshotFetched
from memray.reporters.tui import TUIApp
from memray.reporters.tui import aggregate_allocations
from tests.utils import MockAllocationRecord
from tests.utils import async_run


class MockApp(TUIApp):
    CSS_PATH = None  # type: ignore

    def __init__(self, *args, disable_update_thread=True, **kwargs):
        super().__init__(*args, **kwargs)
        if disable_update_thread:
            # Make the update thread return immediately when started
            self._update_thread.cancel()

    def add_mock_snapshot(
        self,
        snapshot: List[MockAllocationRecord],
        disconnected: bool = False,
        native: bool = True,
    ) -> None:
        records = cast(List[AllocationRecord], snapshot)
        self.post_message(
            SnapshotFetched(
                Snapshot(
                    heap_size=sum(record.size for record in records),
                    records=records,
                    records_by_location=aggregate_allocations(
                        cast(List[AllocationRecord], records), native_traces=native
                    ),
                ),
                disconnected,
            )
        )

    def add_mock_snapshots(
        self,
        snapshots: List[List[MockAllocationRecord]],
        disconnect_after_last: bool = True,
        native: bool = True,
    ) -> None:
        for i, snapshot in enumerate(snapshots):
            disconnected = i == len(snapshots) - 1 and disconnect_after_last
            self.add_mock_snapshot(snapshot, disconnected=disconnected, native=native)


class MockReader:
    def __init__(
        self,
        snapshots: List[List[MockAllocationRecord]],
        has_native_traces: bool = True,
        pid: Optional[int] = None,
        command_line: Optional[str] = None,
    ):
        self._snapshots = cast(List[List[AllocationRecord]], snapshots)
        self._next_snapshot = 0
        self.is_active = True
        self.command_line = command_line
        self.pid = pid
        self.has_native_traces = has_native_traces

    def get_current_snapshot(
        self, *, merge_threads: bool
    ) -> Iterable[AllocationRecord]:
        assert isinstance(merge_threads, bool)  # ignore unused argument
        assert self.is_active
        snapshot = self._snapshots[self._next_snapshot]
        self._next_snapshot += 1
        self.is_active = self._next_snapshot < len(self._snapshots)
        return snapshot


@pytest.fixture
def compare(monkeypatch, tmp_path, snap_compare):
    monkeypatch.setattr(memray.reporters.tui, "datetime", FakeDatetime)

    def compare_impl(
        cmdline_override: Optional[str] = None,
        press: Iterable[str] = (),
        terminal_size: Tuple[int, int] = (80, 24),
        run_before: Optional[Callable[[Pilot], Optional[Awaitable[None]]]] = None,
        native: bool = True,
    ):
        async def run_before_wrapper(pilot) -> None:
            if run_before is not None:
                result = run_before(pilot)
                if result is not None:
                    await result

            await pilot.pause()
            header = pilot.app.query_one("Header")
            header.last_update = header.start + datetime.timedelta(seconds=42)

        app = MockApp(
            MockReader([], has_native_traces=native),
            cmdline_override=cmdline_override,
        )
        app_global = "_CURRENT_APP_"
        tmp_main = tmp_path / "main.py"
        with monkeypatch.context() as app_patch:
            app_patch.setitem(globals(), app_global, app)
            tmp_main.write_text(f"from {__name__} import {app_global} as app")
            return snap_compare(
                str(tmp_main),
                press=press,
                terminal_size=terminal_size,
                run_before=run_before_wrapper,
            )

    yield compare_impl


def render_widget(widget: Widget) -> str:
    output = StringIO()
    rprint(widget.renderable, file=output)  # type: ignore
    return output.getvalue()


def extract_label_text(app: App) -> Dict[str, str]:
    return {
        label.id: render_widget(label)
        for label in app.query(Label)
        if label.id is not None
    }


def mock_allocation(
    stack: Optional[List[Tuple[str, str, int]]] = None,
    tid: int = 1,
    address: int = 0,
    size: int = 1024,
    allocator: AllocatorType = AllocatorType.MALLOC,
    stack_id: int = 0,
    n_allocations: int = 1,
    thread_name: str = "",
):
    hybrid_stack = stack

    if hybrid_stack is not None:
        stack = [
            (func, filename, lineno)
            for func, filename, lineno in hybrid_stack
            if filename.endswith(".py")
        ]

    return MockAllocationRecord(
        tid=tid,
        address=address,
        size=size,
        allocator=allocator,
        stack_id=stack_id,
        n_allocations=n_allocations,
        thread_name=thread_name,
        _stack=stack,
        _hybrid_stack=hybrid_stack,
    )


SHORT_SNAPSHOTS = [
    [
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f1", "f.py", 16),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
    ],
    [
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f1", "f.py", 16),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f2", "f.py", 32),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f2", "f.py", 32),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
    ],
]


LONG_SNAPSHOTS = [
    [
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f1", "f.py", 16),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
    ],
    [
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f1", "f.py", 16),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
        mock_allocation(
            stack=[
                ("malloc", "malloc.c", 1234),
                ("f2", "f.py", 32),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
        mock_allocation(
            size=333,
            stack=[
                ("malloc", "malloc.c", 1234),
                *[(f"something{i}", "something.py", i) for i in range(20)],
                ("f2", "f.py", 32),
                ("parent", "fun.py", 8),
                ("grandparent", "fun.py", 4),
            ],
        ),
    ],
]


class FakeDatetime(datetime.datetime):
    @classmethod
    def now(cls):
        return cls(2023, 10, 13, 12)


class TestGraph:
    def test_empty(self):
        # GIVEN

        plot = MemoryGraph(max_data_points=50)

        # WHEN

        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert plot._maxval == 1.0
        assert plot._minval == 0.0
        assert graph == (" " * 50, " " * 50, " " * 50, " " * 50)

    def test_size_of_graph(self):
        # GIVEN
        size = 36
        rows = 10

        plot = MemoryGraph(max_data_points=size, height=rows)

        # WHEN

        for point in range(50):
            plot.add_value(point)
        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert len(graph) == rows
        assert all(len(line) == size for line in graph)

    def test_one_point_lower_than_max(self):
        # GIVEN

        plot = MemoryGraph(max_data_points=50)

        # WHEN

        plot.add_value(0.5)
        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert plot._maxval == 1.0
        assert plot._minval == 0.0
        assert graph == (
            "                                                  ",
            "                                                  ",
            "                                                 ▐",
            "                                                 ▐",
        )

    def test_one_point_bigger_than_max(self):
        # GIVEN

        plot = MemoryGraph(max_data_points=50)

        # WHEN

        plot.add_value(500.0)
        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert plot._maxval == 500.0
        assert plot._minval == 0
        assert graph == (
            "                                                 ▐",
            "                                                 ▐",
            "                                                 ▐",
            "                                                 ▐",
        )

    def test_one_point_bigger_than_max_after_resize(self):
        # GIVEN

        plot = MemoryGraph(max_data_points=50)

        # WHEN
        plot.add_value(1000)
        for _ in range(50 * 2):
            plot.add_value(0)
        plot.add_value(500.0)

        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert plot._maxval == 1000.0
        assert plot._minval == 0
        assert graph == (
            "                                                  ",
            "                                                  ",
            "                                                 ▐",
            "                                                 ▐",
        )

    def test_multiple_points(self):
        # GIVEN

        plot = MemoryGraph(max_data_points=50)
        plot.add_value(100.0)
        for _ in range(50 * 2):
            plot.add_value(0)

        # WHEN

        for point in range(50):
            plot.add_value(point)

        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert plot._maxval == 100.0
        assert plot._minval == 0
        assert graph == (
            "                                                  ",
            "                                                  ",
            "                                      ▄▄▄▄▄▄██████",
            "                         ▗▄▄▄▄▄▟██████████████████",
        )

    def test_multiple_points_scattered(self):
        # GIVEN

        plot = MemoryGraph(max_data_points=50)
        plot.add_value(100.0)
        for _ in range(50 * 2):
            plot.add_value(0)

        # WHEN
        plot.add_value(100)
        plot.add_value(15)
        plot.add_value(30)
        plot.add_value(75)

        graph = tuple(plot.render_line(i).text for i in range(plot._height))

        # THEN

        assert plot._maxval == 100.0
        assert plot._minval == 0

        assert graph == (
            "                                                ▌ ",
            "                                                ▌▐",
            "                                                ▌▟",
            "                                                ██",
        )


@pytest.mark.parametrize("native_traces", [False, True])
def test_update_thread(native_traces):
    """Test that our update thread posts the expected messages to our app."""
    # GIVEN
    snapshots = SHORT_SNAPSHOTS
    reader = MockReader(snapshots, native_traces)
    messages = []
    all_messages_received = asyncio.Event()

    class MessageInterceptingApp(MockApp):
        def __init__(self, reader):
            super().__init__(reader, poll_interval=0.01, disable_update_thread=False)

        def on_snapshot_fetched(self, message):
            messages.append(message)
            if message.disconnected:
                all_messages_received.set()

    app = MessageInterceptingApp(reader)

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            await all_messages_received.wait()
            await pilot.pause()

    async_run(run_test())

    # THEN
    assert len(messages) == len(snapshots)
    for i, message in enumerate(messages):
        last_message = i == len(messages) - 1
        assert message.disconnected is last_message
        assert message.snapshot.heap_size == sum(a.size for a in snapshots[i])
        assert message.snapshot.records == snapshots[i]
        assert message.snapshot.records_by_location == aggregate_allocations(
            message.snapshot.records,
            native_traces=native_traces,
        )


@pytest.mark.parametrize(
    "pid, display_val",
    [
        pytest.param(999, "PID: 999", id="Known PID"),
        pytest.param(None, "PID: ???", id="Unknown PID"),
    ],
)
def test_pid_display(pid, display_val):
    # GIVEN
    reader = MockReader([], pid=pid)
    app = MockApp(reader)
    labels = {}

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            await pilot.pause()
            labels.update(extract_label_text(pilot.app))

    async_run(run_test())

    # THEN
    assert labels["pid"].rstrip() == display_val


@pytest.mark.parametrize(
    "command_line, display_val",
    [
        pytest.param("foo bar baz", "CMD: foo bar baz", id="Known command"),
        pytest.param(
            "/path/to/foo bar baz",
            "CMD: /path/to/foo bar baz",
            id="Known command with path",
        ),
        pytest.param(
            "/path/to/memray bar baz",
            "CMD: memray bar baz",
            id="Memray script with path",
        ),
        pytest.param(
            "/path/to/memray/__main__.py bar baz",
            "CMD: memray bar baz",
            id="Memray module with path",
        ),
        pytest.param(None, "CMD: ???", id="Unknown command"),
    ],
)
def test_command_line_display(command_line, display_val):
    # GIVEN
    reader = MockReader([], command_line=command_line)
    app = MockApp(reader)
    labels = {}

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            await pilot.pause()
            labels.update(extract_label_text(pilot.app))

    async_run(run_test())

    # THEN
    assert labels["cmd"].rstrip() == display_val


def test_header_with_no_snapshots():
    # GIVEN
    reader = MockReader([])
    app = MockApp(reader)
    labels = {}

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            await pilot.pause()
            labels.update(extract_label_text(pilot.app))

    async_run(run_test())

    # THEN
    assert labels["tid"].split() == "TID: *".split()
    assert labels["thread"].split() == "All threads".split()
    assert labels["samples"].split() == "Samples: 0".split()


def test_header_with_empty_snapshot():
    # GIVEN
    reader = MockReader([])
    app = MockApp(reader)
    labels = {}

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            app.add_mock_snapshot([])
            await pilot.pause()
            labels.update(extract_label_text(pilot.app))

    async_run(run_test())

    # THEN
    assert labels["tid"].split() == "TID: *".split()
    assert labels["thread"].split() == "All threads".split()
    assert labels["samples"].split() == "Samples: 1".split()


def test_sorting():
    """Test that our sort keys correctly sort the data table"""
    # GIVEN
    snapshot = [
        mock_allocation(
            size=10,
            n_allocations=5,
            stack=[("a", "a.py", 1)],
        ),
        mock_allocation(
            size=50,
            n_allocations=1,
            stack=[("b", "b.py", 1)],
        ),
        mock_allocation(
            size=100,
            n_allocations=2,
            stack=[("c", "c.py", 1), ("b", "b.py", 1)],
        ),
        mock_allocation(
            size=25,
            n_allocations=4,
            stack=[("d", "d.py", 1)],
        ),
    ]

    own_order = "cbda"
    total_order = "bcda"
    allocations_order = "adbc"

    reader = MockReader([])
    app = MockApp(reader)
    order_by_key = {}

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            app.add_mock_snapshot(snapshot)
            await pilot.pause()

            datatable = pilot.app.query_one(DataTable)
            function_col_key = datatable.ordered_columns[0].key

            for key in ("", "o", "a", "t"):
                await pilot.press(key)
                order_by_key[key] = "".join(
                    datatable.get_cell(row.key, function_col_key).plain
                    for row in datatable.ordered_rows
                )

    async_run(run_test())

    # THEN
    assert order_by_key[""] == total_order
    assert order_by_key["o"] == own_order
    assert order_by_key["a"] == allocations_order
    assert order_by_key["t"] == total_order


def test_switching_threads():
    """Test that we can switch which thread is displayed"""
    # GIVEN
    thread_names = ["Thread A", "", "Thread C"]
    thread_labels = [
        "Thread 1 of 3 (Thread A)",
        "Thread 2 of 3",
        "Thread 3 of 3 (Thread C)",
    ]
    snapshot = [
        mock_allocation(
            tid=1,
            stack=[("a", "a.py", 1)],
            thread_name=thread_names[0],
        ),
        mock_allocation(
            tid=2,
            stack=[("b", "b.py", 1)],
            thread_name=thread_names[1],
        ),
        mock_allocation(
            tid=3,
            stack=[("c", "c.py", 1)],
            thread_name=thread_names[2],
        ),
    ]

    reader = MockReader([])
    app = MockApp(reader)
    functions = []
    tids = []
    threads = []

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            app.add_mock_snapshot(snapshot)
            await pilot.pause()

            datatable = pilot.app.query_one(DataTable)

            for key in ("m", ">", ">", ">", "<", "<", "<"):
                await pilot.press(key)
                functions.append(datatable.get_cell_at(Coordinate(0, 0)).plain)
                labels = extract_label_text(app)
                tids.append(" ".join(labels["tid"].split()))
                threads.append(" ".join(labels["thread"].split()))

    async_run(run_test())

    # THEN
    order = [0, 1, 2, 0, 2, 1, 0]
    assert functions == ["abc"[i] for i in order]
    assert tids == [f"TID: {hex(i+1)}" for i in order]
    assert threads == [thread_labels[i] for i in order]


def test_merge_mode_new_threads():
    """Test that the 'All threads' is still displayed when a new thread is created."""
    # GIVEN
    snapshot = [
        mock_allocation(
            tid=1,
            stack=[("a", "a.py", 1)],
        ),
        mock_allocation(
            tid=2,
            stack=[("b", "b.py", 1)],
        ),
        mock_allocation(
            tid=3,
            stack=[("c", "c.py", 1)],
        ),
    ]
    new_thread = mock_allocation(tid=4, stack=[("d", "d.py", 1)])

    reader = MockReader([])
    app = MockApp(reader)
    label = []

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            await pilot.press("m")
            app.add_mock_snapshot(snapshot)
            await pilot.pause()

            await pilot.press("m")
            app.add_mock_snapshot(snapshot + [new_thread])
            await pilot.pause()
            label.append(extract_label_text(app)["thread"])

    async_run(run_test())

    # THEN
    assert label == ["All threads\n"]


def test_merging_allocations_from_all_threads():
    """Test that we can display allocations from all threads"""
    # GIVEN
    snapshot = [
        mock_allocation(
            tid=1,
            size=1024,
            stack=[("a", "a.py", 1)],
        ),
        mock_allocation(
            tid=2,
            size=2 * 1024,
            stack=[("b", "b.py", 1)],
        ),
        mock_allocation(
            tid=3,
            size=3 * 1024,
            stack=[("c", "c.py", 1)],
        ),
    ]

    reader = MockReader([])
    app = MockApp(reader)
    functions = []
    tids = []
    threads = []

    # WHEN
    async def run_test():
        async with app.run_test() as pilot:
            app.add_mock_snapshot(snapshot)
            await pilot.pause()

            datatable = pilot.app.query_one(DataTable)

            for key in ("m", ">", "m", "<", "m", "<"):
                await pilot.press(key)
                functions.append(datatable.get_cell_at(Coordinate(0, 0)).plain)
                labels = extract_label_text(app)
                tids.append(" ".join(labels["tid"].split()))
                threads.append(" ".join(labels["thread"].split()))

    async_run(run_test())

    # THEN
    order = [0, 1, 2, 2, 1, 0]
    merged = [False, False, True, True, False, False]
    assert functions == ["abc"[i] for i in order]
    assert tids == [
        "TID: *" if all else f"TID: {hex(i+1)}" for i, all in zip(order, merged)
    ]
    assert threads == [
        "All threads" if all else f"Thread {i+1} of 3" for i, all in zip(order, merged)
    ]


@pytest.mark.parametrize(
    "terminal_size, press, snapshots",
    [
        pytest.param(
            (80, 24), [], SHORT_SNAPSHOTS, id="narrow-terminal-short-snapshots"
        ),
        pytest.param(
            (80, 24),
            ["tab"],
            LONG_SNAPSHOTS,
            id="narrow-terminal-focus-header-long-snapshots",
        ),
        pytest.param((120, 24), [], LONG_SNAPSHOTS, id="wide-terminal-long-snapshots"),
        pytest.param(
            (200, 24), [], SHORT_SNAPSHOTS, id="very-wide-terminal-short-snapshots"
        ),
    ],
)
def test_tui_basic(terminal_size, press, snapshots, compare):
    async def run_before(pilot) -> None:
        pilot.app.add_mock_snapshots(snapshots)

    assert compare(
        press=press,
        run_before=run_before,
        terminal_size=terminal_size,
    )


@pytest.mark.parametrize(
    "terminal_size, disconnected",
    [
        pytest.param((50, 24), False, id="narrow-terminal-connected"),
        pytest.param((50, 24), True, id="narrow-terminal-disconnected"),
        pytest.param((81, 24), True, id="wider-terminal"),
    ],
)
def test_tui_pause(terminal_size, disconnected, compare):
    async def run_before(pilot: Pilot) -> None:
        app = cast(MockApp, pilot.app)
        app.add_mock_snapshot(SHORT_SNAPSHOTS[0])
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("tab")
        await pilot.pause()
        app.add_mock_snapshot(SHORT_SNAPSHOTS[1], disconnected=disconnected)

    assert compare(
        run_before=run_before,
        terminal_size=terminal_size,
    )


def test_tui_gradient(compare):
    snapshot = [
        mock_allocation(
            stack=[(f"function{j}", f"/abc/lel_{j}.py", i) for j in range(i, -1, -1)],
            size=1024 + 10 * i,
            n_allocations=1,
        )
        for i in range(0, 30)
    ]

    async def run_before(pilot) -> None:
        pilot.app.add_mock_snapshots([snapshot], native=False)

    assert compare(run_before=run_before, terminal_size=(125, 40), native=False)


class TestAggregateResults:
    def test_simple_allocations(self):
        # GIVEN
        mock_allocation_records = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("sibling", "fun.py", 16),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]
        allocation_records = cast(List[AllocationRecord], mock_allocation_records)

        # WHEN
        result = aggregate_allocations(allocation_records)

        # THEN
        grandparent = result[Location(function="grandparent", file="fun.py")]
        assert grandparent.own_memory == 0
        assert grandparent.total_memory == 30
        assert grandparent.n_allocations == 3

        me = result[Location(function="me", file="fun.py")]
        assert me.own_memory == 10
        assert me.total_memory == 10
        assert me.n_allocations == 2

        parent = result[Location(function="parent", file="fun.py")]
        assert parent.own_memory == 0
        assert parent.total_memory == 30
        assert parent.n_allocations == 3

    def test_missing_frames(self):
        # GIVEN
        mock_allocation_records = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _stack=[],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("sibling", "fun.py", 16),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=30,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=1,
                _stack=[],
            ),
        ]
        allocation_records = cast(List[AllocationRecord], mock_allocation_records)

        # WHEN
        result = aggregate_allocations(allocation_records)

        # THEN
        grandparent = result[Location(function="grandparent", file="fun.py")]
        assert grandparent.own_memory == 0
        assert grandparent.total_memory == 20
        assert grandparent.n_allocations == 1

        me = result[Location(function="???", file="???")]
        assert me.own_memory == 40
        assert me.total_memory == 40
        assert me.n_allocations == 3

    def test_native_frames(self):
        # GIVEN
        mock_allocation_records = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _stack=[],
                _hybrid_stack=[],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("sibling", "fun.c", 16),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=30,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=1,
                _hybrid_stack=[],
            ),
        ]
        allocation_records = cast(List[AllocationRecord], mock_allocation_records)

        # WHEN
        result = aggregate_allocations(allocation_records, native_traces=True)

        # THEN
        grandparent = result[Location(function="grandparent", file="fun.py")]
        assert grandparent.own_memory == 0
        assert grandparent.total_memory == 20
        assert grandparent.n_allocations == 1

        me = result[Location(function="???", file="???")]
        assert me.own_memory == 40
        assert me.total_memory == 40
        assert me.n_allocations == 3


def test_merge_threads(compare):
    async def run_before(pilot: Pilot) -> None:
        snapshot = [
            mock_allocation(
                tid=1,
                stack=[("a", "a.py", 1)],
            ),
            mock_allocation(
                tid=2,
                stack=[("b", "b.py", 1)],
            ),
            mock_allocation(
                tid=3,
                stack=[("c", "c.py", 1)],
            ),
        ]
        app = cast(MockApp, pilot.app)
        await pilot.press("m")
        app.add_mock_snapshot(snapshot)
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        app.add_mock_snapshot(snapshot)

    assert compare(
        run_before=run_before,
        terminal_size=(150, 24),
    )


def test_unmerge_threads(compare):
    async def run_before(pilot: Pilot) -> None:
        snapshot = [
            mock_allocation(
                tid=1,
                stack=[("a", "a.py", 1)],
            ),
            mock_allocation(
                tid=2,
                stack=[("b", "b.py", 1)],
            ),
            mock_allocation(
                tid=3,
                stack=[("c", "c.py", 1)],
            ),
        ]
        app = cast(MockApp, pilot.app)
        app.add_mock_snapshot(snapshot)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press(">")
        await pilot.press("m")
        await pilot.press(">")
        await pilot.press("m")
        await pilot.pause()
        app.add_mock_snapshot(snapshot)

    assert compare(
        run_before=run_before,
        terminal_size=(150, 24),
    )
