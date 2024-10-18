import gc
import sys

import pytest

from memray import FileReader
from memray import Tracker

# Define a decorator for tests that require Python 3.13+
requires_at_least_py313 = pytest.mark.skipif(
    sys.version_info < (3, 13, 3),
    reason="Python object reference tracking requires Python 3.13 or later",
)

# Define a decorator for tests that verify version-check errors on older Python
requires_older_python_than_py313 = pytest.mark.skipif(
    sys.version_info >= (3, 13, 3),
    reason="This test verifies error handling on Python < 3.13",
)


class MyClass:
    def __init__(self, name):
        self.name = name
        self.data = list(range(10))  # Create some data


@requires_older_python_than_py313
def test_track_object_lifetimes_version_check(tmp_path):
    output = tmp_path / "test.bin"

    # On Python < 3.13, creating a Tracker with track_object_lifetimes=True
    # should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        with Tracker(output, track_object_lifetimes=True):
            pass
    assert "Python object reference tracking requires Python 3.13.3 or later" in str(
        exc_info.value
    )
    assert f"Current version: {sys.version_info.major}.{sys.version_info.minor}" in str(
        exc_info.value
    )


@requires_older_python_than_py313
def test_get_surviving_objects_version_check(tmp_path):
    output = tmp_path / "test.bin"

    # Create a tracker without reference tracking (should work on all versions)
    with Tracker(output) as tracker:
        MyClass("test_object")  # noqa

    with pytest.raises(RuntimeError) as exc_info:
        tracker.get_surviving_objects()
    assert (
        "track_object_lifetimes=True was not provided at Tracker construction"
        in str(exc_info.value)
    )


@requires_older_python_than_py313
def test_get_tracked_objects_version_check(tmp_path):
    output = tmp_path / "test.bin"

    # Create a tracker without reference tracking
    with Tracker(output):
        MyClass("test_object")

    # Create FileReader
    reader = FileReader(output)

    # Calling get_object_lifetime_events should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        list(reader.get_object_lifetime_events())
    assert "Object lifetime events are not available in this capture file" in str(
        exc_info.value
    )


@requires_at_least_py313
def test_track_object_lifetimes_disabled_by_default(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output) as tracker:
        MyClass("test_object")

    # THEN
    # Should raise RuntimeError because track_object_lifetimes was not enabled
    with pytest.raises(RuntimeError) as exc_info:
        tracker.get_surviving_objects()
    assert (
        "track_object_lifetimes=True was not provided at Tracker construction"
        in str(exc_info.value)
    )


@requires_at_least_py313
def test_track_object_lifetimes_simple_object(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, track_object_lifetimes=True) as tracker:
        obj = MyClass("test_object")
        obj_id = id(obj)

    # THEN
    # The object should be tracked and returned in surviving_objects
    surviving_objects = tracker.get_surviving_objects()

    # There should be at least one surviving object (our MyClass instance)
    assert len(surviving_objects) >= 1

    # Ensure our object is in the list
    test_obj = obj
    assert any(o is obj for o in surviving_objects)

    assert test_obj is not None, "Our test object was not found in surviving objects"
    assert id(test_obj) == obj_id, "Object IDs should match"
    assert test_obj.data == list(range(10)), "Object data should be preserved"

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events(included_objects=surviving_objects)
        if obj.is_created
    }

    # Verify our object is in the tracked objects
    assert obj_id in created_objects, "Object ID should be in tracked objects"
    tracked_obj = created_objects[obj_id]
    assert tracked_obj.is_created, "Object should be marked as created"


@requires_at_least_py313
def test_track_object_lifetimes_deallocated_object(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    # Create object and then delete it before the tracker exits
    obj_ids = []
    with Tracker(output, track_object_lifetimes=True) as tracker:
        obj1 = MyClass("test_object1")
        obj_ids.append(id(obj1))

        obj2 = MyClass("test_object2")
        obj_ids.append(id(obj2))

        # Delete obj1 and make sure it's garbage collected
        del obj1
        gc.collect()

    # THEN
    # Only obj2 should be in the surviving objects
    surviving_objects = tracker.get_surviving_objects()

    # Check that only one of our created objects survived
    test_objects = [obj for obj in surviving_objects if isinstance(obj, MyClass)]
    assert len(test_objects) == 1
    assert test_objects[0].name == "test_object2"

    # Verify the ID matches obj2
    assert test_objects[0] is obj2

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events()
        if obj.is_created
    }
    deleted_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events()
        if not obj.is_created
    }

    # Both objects should have creation records, even though one was deleted
    assert obj_ids[0] in created_objects, "Object 1 should have a creation record"
    assert obj_ids[1] in created_objects, "Object 2 should have a creation record"

    # One object should have a deallocation record
    assert obj_ids[0] in deleted_objects, "Object 1 should have a deallocation record"
    assert (
        obj_ids[1] not in deleted_objects
    ), "Object 2 should not have a deallocation record"


@requires_at_least_py313
def test_track_object_lifetimes_with_stack_trace(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, track_object_lifetimes=True) as tracker:
        obj = MyClass("test_object")
        obj_id = id(obj)

    # THEN
    # Check we can get stack traces for the tracked object
    reader = FileReader(output)

    # Find our object in the surviving objects
    surviving_objects = tracker.get_surviving_objects()
    assert any(
        o is obj for o in surviving_objects
    ), "Test object not found in surviving objects"

    # Get tracked objects from the file and create address -> object mapping
    created_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events(included_objects=surviving_objects)
        if obj.is_created
    }

    # Should have our test object in the tracked objects
    assert obj_id in created_objects, "Object ID should be in tracked objects"
    tracked_obj = created_objects[obj_id]

    # Get stack trace for the object
    stack_trace = tracked_obj.hybrid_stack_trace()
    assert stack_trace is not None, "Stack trace should be available for the object"
    assert len(stack_trace) > 0, "Stack trace should have at least one frame"
    assert stack_trace[0] == (
        "test_track_object_lifetimes_with_stack_trace",
        __file__,
        200,
    )

    # Check that we can get native stack trace too
    native_stack_trace = tracked_obj.native_stack_trace()
    assert native_stack_trace == []

    # Check Python stack trace
    python_stack_trace = tracked_obj.stack_trace()
    assert python_stack_trace is not None, "Python stack trace should be available"
    assert python_stack_trace == [
        ("test_track_object_lifetimes_with_stack_trace", __file__, 200)
    ]


@requires_at_least_py313
def test_multiple_surviving_objects(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    objects = []
    with Tracker(output, track_object_lifetimes=True) as tracker:
        # Create multiple objects of different types
        objects.append(MyClass("object1"))
        objects.append(MyClass("object2"))
        string_object = MyClass.__name__ * 2
        objects.append(string_object)
        objects.append({"dict": "object"})
        objects.append([1, 2, 3])

    # THEN
    surviving_objects = tracker.get_surviving_objects()

    # We should have at least our 5 objects
    assert len(surviving_objects) >= 5

    # Check for our custom objects
    for obj in objects:
        assert any(o is obj for o in surviving_objects)

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events(included_objects=surviving_objects)
        if obj.is_created
    }

    # All objects should have creation records
    for obj in objects:
        assert (
            id(obj) in created_objects
        ), f"Object with ID {id(obj)} should have a creation record"


@requires_at_least_py313
def test_object_tracking_in_threads(tmp_path):
    # GIVEN
    import threading

    output = tmp_path / "test.bin"

    # WHEN
    thread_objects = {}

    def thread_function(name):
        # Create an object in this thread
        obj = MyClass(f"thread_{name}")
        thread_objects[name] = obj

    with Tracker(output, track_object_lifetimes=True) as tracker:
        # Create and run threads
        threads = []
        for i in range(3):
            thread_name = f"thread_{i}"
            thread = threading.Thread(target=thread_function, args=(thread_name,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

    # THEN
    surviving_objects = tracker.get_surviving_objects()

    # Check that objects created in threads are tracked
    for name, obj in thread_objects.items():
        # Find the object in surviving_objects
        assert any(o is obj for o in surviving_objects)

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events(included_objects=surviving_objects)
        if obj.is_created
    }

    # Verify each thread object has a creation record
    for name, obj in thread_objects.items():
        obj_id = id(obj)
        assert (
            obj_id in created_objects
        ), f"Object for thread {name} should have a creation record"


@requires_at_least_py313
def test_object_stack_trace_with_native_traces(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, native_traces=True, track_object_lifetimes=True) as tracker:
        obj = MyClass("test_object")
        obj_id = id(obj)

    # THEN
    # Get a handle to the file reader
    reader = FileReader(output)
    surviving_objects = tracker.get_surviving_objects()

    # Find our test object
    assert any(o is obj for o in surviving_objects)

    # Get tracked objects from the file and create address -> object mapping
    created_objects = {
        obj.address: obj
        for obj in reader.get_object_lifetime_events(included_objects=surviving_objects)
        if obj.is_created
    }

    # Our object should be in the tracked objects
    assert obj_id in created_objects, "Object ID should be in tracked objects"
    tracked_obj = created_objects[obj_id]

    # Get stack trace for the object
    expected_stack_trace = ("test_object_stack_trace_with_native_traces", __file__, 346)

    stack_trace = tracked_obj.hybrid_stack_trace()
    assert stack_trace is not None, "Stack trace should be available for the object"
    assert len(stack_trace) > 0, "Stack trace should have at least one frame"
    assert expected_stack_trace in stack_trace

    # Check that we can get native stack trace too
    native_stack_trace = tracked_obj.native_stack_trace()
    assert native_stack_trace is not None, "Native stack trace should be available"
    assert len(native_stack_trace) > 0

    # Check Python stack trace
    python_stack_trace = tracked_obj.stack_trace()
    assert python_stack_trace is not None, "Python stack trace should be available"
    assert python_stack_trace != stack_trace
    assert expected_stack_trace in python_stack_trace


@requires_at_least_py313
def test_get_tracked_objects_without_filter(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, track_object_lifetimes=True):
        obj1 = MyClass("object1")
        obj2 = MyClass("object2")

        # Delete obj1 to create a deallocation record
        obj1_id = id(obj1)
        obj2_id = id(obj2)
        del obj1
        gc.collect()

    # THEN
    reader = FileReader(output)

    # Get all tracked objects (without filter)
    all_tracked_objects = list(reader.get_object_lifetime_events())

    # Should have at least 3 records: 2 creation records and 1 deallocation record
    assert (
        len(all_tracked_objects) >= 3
    ), "Should have at least 3 tracked object records"

    # Create separate dictionaries for created and deallocated objects
    created_objects = {
        obj.address: obj for obj in all_tracked_objects if obj.is_created
    }
    deallocated_objects = {
        obj.address: obj for obj in all_tracked_objects if not obj.is_created
    }

    # Both objects should have creation records
    assert obj1_id in created_objects, "obj1 should have a creation record"
    assert obj2_id in created_objects, "obj2 should have a creation record"

    # Only obj1 should have a deallocation record
    assert obj1_id in deallocated_objects, "obj1 should have a deallocation record"
    assert (
        obj2_id not in deallocated_objects
    ), "obj2 should not have a deallocation record"

    # Check we can get stack traces from the created objects
    for address, obj in created_objects.items():
        stack_trace = obj.stack_trace()
        assert (
            stack_trace is not None
        ), f"Stack trace should be available for object at {address}"
        assert (
            len(stack_trace) > 0
        ), f"Stack trace should have at least one frame for object at {address}"


@requires_at_least_py313
def test_track_object_lifetimes_aggregating_writer(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN - Use aggregating writer (FileFormat.AGGREGATED_ALLOCATIONS)
    from memray import FileFormat

    objects = []
    with Tracker(
        output,
        track_object_lifetimes=True,
        file_format=FileFormat.AGGREGATED_ALLOCATIONS,
    ) as tracker:
        # Create multiple objects
        obj1 = MyClass("aggregated_object1")
        obj2 = MyClass("aggregated_object2")
        objects.extend([obj1, obj2])

        # Create and delete an object to test that only surviving ones are recorded
        temp_obj = MyClass("temp_object")
        temp_obj_id = id(temp_obj)
        del temp_obj
        gc.collect()

    # THEN
    # Get surviving objects from tracker
    surviving_objects = tracker.get_surviving_objects()

    # Both obj1 and obj2 should be in surviving objects
    assert len([o for o in surviving_objects if isinstance(o, MyClass)]) >= 2
    assert any(
        o is obj1 for o in surviving_objects
    ), "obj1 should be in surviving objects"
    assert any(
        o is obj2 for o in surviving_objects
    ), "obj2 should be in surviving objects"

    # The temporary object should not be in surviving objects (it was deleted)
    assert not any(
        id(o) == temp_obj_id for o in surviving_objects
    ), "temp_obj should not be in surviving objects"

    # Read from the aggregated file to verify surviving objects are written correctly
    reader = FileReader(output)

    # Get object lifetime events - should only return surviving objects for aggregated files
    tracked_objects = list(
        reader.get_object_lifetime_events(included_objects=surviving_objects)
    )

    # All tracked objects in aggregated format should be marked as created (surviving)
    for obj in tracked_objects:
        assert (
            obj.is_created
        ), "All objects in aggregated format should be marked as created/surviving"

    # Should include our test objects
    tracked_addresses = {obj.address for obj in tracked_objects}
    assert id(obj1) in tracked_addresses, "obj1 should be in tracked objects"
    assert id(obj2) in tracked_addresses, "obj2 should be in tracked objects"
    assert (
        temp_obj_id not in tracked_addresses
    ), "temp_obj should not be in tracked objects"
