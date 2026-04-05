import csv
import json
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import TextIO
from typing import Tuple
from typing import Union

from memray import AllocationRecord
from memray import AllocatorType
from memray import MemorySnapshot
from memray import Metadata
from memray import __version__
from memray._memray import TemporalAllocationRecord
from memray.reporters.common import format_thread_name

Location = Tuple[str, str]
FrameLocation = Tuple[str, str, int]
FrameSample = Tuple[int, ...]


class TransformReporter:
    SUFFIX_MAP = {
        "gprof2dot": ".json",
        "csv": ".csv",
        "speedscope": ".speedscope.json",
    }

    def __init__(
        self,
        allocations: Iterable[AllocationRecord],
        *,
        format: str,
        native_traces: bool,
        memory_records: Iterable[MemorySnapshot],
        high_water_mark_by_snapshot: Optional[List[int]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.allocations = allocations
        self.format = format
        self.native_traces = native_traces
        self.memory_records = tuple(memory_records)
        self.high_water_mark_by_snapshot = high_water_mark_by_snapshot

    def render_as_gprof2dot(
        self,
        outfile: TextIO,
        **kwargs: Any,
    ) -> None:
        location_to_index: Dict[Location, int] = {}
        all_locations: List[Dict[str, str]] = []
        events = []
        for record in self.allocations:
            stack_trace = self._stack_trace_for_record(record)
            call_chain = []
            for func, mod, _ in stack_trace:
                location = (func, mod)
                index = location_to_index.get(location)
                if index is None:
                    index = len(all_locations)
                    all_locations.append({"name": func, "module": mod})
                    location_to_index[location] = index
                call_chain.append(index)

            if not call_chain:
                continue
            events.append({"callchain": call_chain, "cost": [record.size]})

        result = {
            "version": 0,
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": events,
            "functions": all_locations,
        }
        json.dump(result, outfile)

    def _stack_trace_for_record(
        self, record: Union[AllocationRecord, TemporalAllocationRecord]
    ) -> Tuple[Tuple[str, str, int], ...]:
        return (
            tuple(record.hybrid_stack_trace())
            if self.native_traces
            else tuple(record.stack_trace())
        )

    def _speedscope_sample_for_record(
        self,
        record: Union[AllocationRecord, TemporalAllocationRecord],
        *,
        location_to_index: Dict[FrameLocation, int],
        frames: List[Dict[str, Any]],
    ) -> FrameSample:
        stack_trace = self._stack_trace_for_record(record)
        if not stack_trace:
            return ()

        # Speedscope sampled stacks are root-to-leaf. Memray exposes leaf-to-root.
        sample = []
        for func, mod, line in reversed(stack_trace):
            location = (func, mod, line)
            index = location_to_index.get(location)
            if index is None:
                index = len(frames)
                frame: Dict[str, Any] = {"name": func}
                if mod:
                    frame["file"] = mod
                if line > 0:
                    frame["line"] = line
                frames.append(frame)
                location_to_index[location] = index
            sample.append(index)
        return tuple(sample)

    def _add_speedscope_sample(
        self,
        *,
        sample: FrameSample,
        size: int,
        n_allocations: int,
        order_key: int,
        sample_weights: Dict[FrameSample, List[int]],
        sample_order: Dict[FrameSample, int],
    ) -> None:
        if not sample:
            return

        aggregated = sample_weights.setdefault(sample, [0, 0])
        aggregated[0] += size
        aggregated[1] += n_allocations

        existing_order = sample_order.get(sample)
        if existing_order is None or order_key < existing_order:
            sample_order[sample] = order_key

    def _aggregate_snapshot_speedscope_samples(
        self,
        allocations: Iterable[AllocationRecord],
        *,
        metadata: Optional[Metadata],
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[FrameSample, List[int]]]]:
        location_to_index: Dict[FrameLocation, int] = {}
        frames: List[Dict[str, Any]] = []
        sample_weights: Dict[FrameSample, List[int]] = {}
        sample_order: Dict[FrameSample, int] = {}
        has_exact_timestamps = (
            metadata is not None and metadata.has_allocation_timestamps
        )

        for sequence, record in enumerate(allocations):
            sample = self._speedscope_sample_for_record(
                record,
                location_to_index=location_to_index,
                frames=frames,
            )
            order_key = record.timestamp_us if has_exact_timestamps else sequence
            self._add_speedscope_sample(
                sample=sample,
                size=record.size,
                n_allocations=record.n_allocations,
                order_key=order_key,
                sample_weights=sample_weights,
                sample_order=sample_order,
            )

        ordered_samples = sorted(
            sample_weights.items(),
            key=lambda item: (sample_order[item[0]], item[0]),
        )
        return frames, ordered_samples

    def _snapshot_order_key(self, snapshot_index: int) -> int:
        if 0 <= snapshot_index < len(self.memory_records):
            # Convert ms-since-epoch to µs for comparison with timestamp_us
            return self.memory_records[snapshot_index].time * 1000
        if self.memory_records:
            return self.memory_records[-1].time * 1000
        return snapshot_index

    def _peak_snapshot_index(self) -> int:
        high_water_mark_by_snapshot = self.high_water_mark_by_snapshot or [0]
        return max(
            range(len(high_water_mark_by_snapshot)),
            key=high_water_mark_by_snapshot.__getitem__,
        )

    def _contribution_for_temporal_record(
        self,
        record: TemporalAllocationRecord,
        *,
        show_memory_leaks: bool,
        peak_snapshot: Optional[int] = None,
    ) -> Tuple[int, int, Optional[int]]:
        size = 0
        n_allocations = 0
        first_snapshot = None

        if show_memory_leaks:
            for interval in record.intervals:
                if interval.deallocated_before_snapshot is not None:
                    continue
                size += interval.n_bytes
                n_allocations += interval.n_allocations
                snapshot = interval.allocated_before_snapshot
                if first_snapshot is None or snapshot < first_snapshot:
                    first_snapshot = snapshot
            return size, n_allocations, first_snapshot

        if peak_snapshot is None:
            peak_snapshot = self._peak_snapshot_index()
        for interval in record.intervals:
            if interval.allocated_before_snapshot > peak_snapshot:
                continue
            if (
                interval.deallocated_before_snapshot is not None
                and peak_snapshot >= interval.deallocated_before_snapshot
            ):
                continue
            size += interval.n_bytes
            n_allocations += interval.n_allocations
            snapshot = interval.allocated_before_snapshot
            if first_snapshot is None or snapshot < first_snapshot:
                first_snapshot = snapshot
        return size, n_allocations, first_snapshot

    def _aggregate_temporal_speedscope_samples(
        self,
        allocations: Iterable[TemporalAllocationRecord],
        *,
        show_memory_leaks: bool,
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[FrameSample, List[int]]]]:
        location_to_index: Dict[FrameLocation, int] = {}
        frames: List[Dict[str, Any]] = []
        sample_weights: Dict[FrameSample, List[int]] = {}
        sample_order: Dict[FrameSample, int] = {}

        peak_snapshot = None if show_memory_leaks else self._peak_snapshot_index()

        for sequence, record in enumerate(allocations):
            sample = self._speedscope_sample_for_record(
                record,
                location_to_index=location_to_index,
                frames=frames,
            )
            (
                size,
                n_allocations,
                first_snapshot,
            ) = self._contribution_for_temporal_record(
                record,
                show_memory_leaks=show_memory_leaks,
                peak_snapshot=peak_snapshot,
            )
            if size <= 0 and n_allocations <= 0:
                continue

            order_key = (
                self._snapshot_order_key(first_snapshot)
                if first_snapshot is not None
                else sequence
            )
            self._add_speedscope_sample(
                sample=sample,
                size=size,
                n_allocations=n_allocations,
                order_key=order_key,
                sample_weights=sample_weights,
                sample_order=sample_order,
            )

        ordered_samples = sorted(
            sample_weights.items(),
            key=lambda item: (sample_order[item[0]], item[0]),
        )
        return frames, ordered_samples

    def _create_speedscope_profile(
        self,
        *,
        name: str,
        unit: str,
        sample_weights: List[Tuple[FrameSample, List[int]]],
        weight_index: int,
    ) -> Dict[str, Any]:
        samples: List[List[int]] = []
        weights: List[int] = []

        for sample, aggregated in sample_weights:
            weight = aggregated[weight_index]
            if weight <= 0:
                continue
            samples.append(list(sample))
            weights.append(weight)

        return {
            "type": "sampled",
            "name": name,
            "unit": unit,
            "startValue": 0,
            "endValue": sum(weights),
            "samples": samples,
            "weights": weights,
        }

    def render_as_speedscope(
        self,
        outfile: TextIO,
        **kwargs: Any,
    ) -> None:
        metadata = kwargs.get("metadata")
        show_memory_leaks = kwargs.get("show_memory_leaks", False)
        allocations = list(self.allocations)

        if allocations and self._is_temporal_record(allocations[0]):
            frames, sample_weights = self._aggregate_temporal_speedscope_samples(
                allocations,
                show_memory_leaks=show_memory_leaks,
            )
        else:
            frames, sample_weights = self._aggregate_snapshot_speedscope_samples(
                allocations,
                metadata=metadata,
            )

        result = {
            "$schema": "https://www.speedscope.app/file-format-schema.json",
            "shared": {"frames": frames},
            "profiles": [
                self._create_speedscope_profile(
                    name="Memory",
                    unit="bytes",
                    sample_weights=sample_weights,
                    weight_index=0,
                ),
                self._create_speedscope_profile(
                    name="Allocations",
                    unit="none",
                    sample_weights=sample_weights,
                    weight_index=1,
                ),
            ],
            "name": metadata.command_line if metadata is not None else "memray",
            "activeProfileIndex": 0,
            "exporter": f"memray@{__version__}",
        }
        json.dump(result, outfile)

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
        inverted: bool,
        no_web: bool = False,
    ) -> None:
        if not merge_threads:
            raise NotImplementedError("TransformReporter only supports merged threads.")
        if inverted:
            raise NotImplementedError(
                "TransformReporter does not support inverted argument."
            )
        renderer = getattr(self, f"render_as_{self.format}")
        renderer(outfile, metadata=metadata, show_memory_leaks=show_memory_leaks)

    def render_as_csv(
        self,
        outfile: TextIO,
        **kwargs: Any,
    ) -> None:
        writer = csv.writer(outfile)
        writer.writerow(
            [
                "allocator",
                "num_allocations",
                "size",
                "tid",
                "thread_name",
                "stack_trace",
            ]
        )
        for record in self.allocations:
            stack_trace = self._stack_trace_for_record(record)
            writer.writerow(
                [
                    AllocatorType(record.allocator).name,
                    record.n_allocations,
                    record.size,
                    record.tid,
                    format_thread_name(record),
                    "|".join(f"{func};{mod};{line}" for func, mod, line in stack_trace),
                ]
            )

    @staticmethod
    def _is_temporal_record(
        record: Union[AllocationRecord, TemporalAllocationRecord]
    ) -> bool:
        return hasattr(record, "intervals")
