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
def test_reference_tracking_version_check(tmp_path):
    output = tmp_path / "test.bin"

    # On Python < 3.13, creating a Tracker with reference_tracking=True
    # should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        with Tracker(output, reference_tracking=True):
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
    assert "Python object reference tracking requires Python 3.13.3 or later" in str(
        exc_info.value
    )


@requires_older_python_than_py313
def test_get_tracked_objects_version_check(tmp_path):
    output = tmp_path / "test.bin"

    # Create a tracker without reference tracking
    with Tracker(output):
        MyClass("test_object")

    # Create FileReader
    reader = FileReader(output)

    # Calling get_tracked_objects should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        list(reader.get_tracked_objects())
    assert "Python object reference tracking requires Python 3.13.3 or later" in str(
        exc_info.value
    )


@requires_at_least_py313
def test_reference_tracking_disabled_by_default(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output) as tracker:
        obj = MyClass("test_object")
        del obj
        gc.collect()

    # THEN
    # No surviving objects should be recorded when reference_tracking is disabled
    assert len(tracker.get_surviving_objects()) == 0


@requires_at_least_py313
def test_reference_tracking_simple_object(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, reference_tracking=True) as tracker:
        obj = MyClass("test_object")
        obj_id = id(obj)

    # THEN
    # The object should be tracked and returned in surviving_objects
    surviving_objects = tracker.get_surviving_objects()

    # There should be at least one surviving object (our MyClass instance)
    assert len(surviving_objects) >= 1

    # Find our object in the list
    test_obj = None
    for obj in surviving_objects:
        if isinstance(obj, MyClass) and obj.name == "test_object":
            test_obj = obj
            break

    assert test_obj is not None, "Our test object was not found in surviving objects"
    assert id(test_obj) == obj_id, "Object IDs should match"
    assert test_obj.data == list(range(10)), "Object data should be preserved"

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_tracked_objects(filter_objs=surviving_objects)
        if obj.is_created
    }

    # Verify our object is in the tracked objects
    assert obj_id in created_objects, "Object ID should be in tracked objects"
    tracked_obj = created_objects[obj_id]
    assert tracked_obj.is_created, "Object should be marked as created"


@requires_at_least_py313
def test_reference_tracking_deallocated_object(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    # Create object and then delete it before the tracker exits
    obj_ids = []
    with Tracker(output, reference_tracking=True) as tracker:
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
    assert id(test_objects[0]) == obj_ids[1]

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj for obj in reader.get_tracked_objects() if obj.is_created
    }
    deleted_objects = {
        obj.address: obj for obj in reader.get_tracked_objects() if not obj.is_created
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
def test_reference_tracking_with_stack_trace(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, reference_tracking=True) as tracker:
        obj = MyClass("test_object")
        obj_id = id(obj)

    # THEN
    # Check we can get stack traces for the tracked object
    reader = FileReader(output)

    # Find our object in the surviving objects
    surviving_objects = tracker.get_surviving_objects()
    test_obj = None
    for obj in surviving_objects:
        if isinstance(obj, MyClass) and obj.name == "test_object":
            test_obj = obj
            break

    assert test_obj is not None, "Test object not found in surviving objects"

    # Get tracked objects from the file and create address -> object mapping
    created_objects = {
        obj.address: obj
        for obj in reader.get_tracked_objects(filter_objs=surviving_objects)
        if obj.is_created
    }

    # Should have our test object in the tracked objects
    assert obj_id in created_objects, "Object ID should be in tracked objects"
    tracked_obj = created_objects[obj_id]

    # Get stack trace for the object
    stack_trace = tracked_obj.hybrid_stack_trace()
    assert stack_trace is not None, "Stack trace should be available for the object"
    assert len(stack_trace) > 0, "Stack trace should have at least one frame"
    assert stack_trace[0] == ("test_reference_tracking_with_stack_trace", __file__, 195)

    # Check that we can get native stack trace too
    native_stack_trace = tracked_obj.native_stack_trace()
    assert native_stack_trace is not None, "Native stack trace should be available"
    assert native_stack_trace == []

    # Check Python stack trace
    python_stack_trace = tracked_obj.stack_trace()
    assert python_stack_trace is not None, "Python stack trace should be available"
    assert python_stack_trace == [
        ("test_reference_tracking_with_stack_trace", __file__, 195)
    ]


@requires_at_least_py313
def test_multiple_surviving_objects(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    objects = []
    with Tracker(output, reference_tracking=True) as tracker:
        # Create multiple objects of different types
        objects.append(MyClass("object1"))
        objects.append(MyClass("object2"))
        string_object = MyClass.__name__ * 2
        objects.append(string_object)
        objects.append({"dict": "object"})
        objects.append([1, 2, 3])

        # Keep references to their IDs
        object_ids = [id(obj) for obj in objects]

    # THEN
    surviving_objects = tracker.get_surviving_objects()

    # We should have at least our 5 objects
    assert len(surviving_objects) >= 5

    # Check for our custom objects
    my_class_objects = [obj for obj in surviving_objects if isinstance(obj, MyClass)]
    assert len(my_class_objects) == 2
    assert sorted([obj.name for obj in my_class_objects]) == ["object1", "object2"]

    # Find the other objects by type
    found_string = any(
        isinstance(obj, str) and obj == string_object for obj in surviving_objects
    )
    found_dict = any(
        isinstance(obj, dict) and obj == {"dict": "object"} for obj in surviving_objects
    )
    found_list = any(
        isinstance(obj, list) and obj == [1, 2, 3] for obj in surviving_objects
    )

    assert found_string, "String object not found in surviving objects"
    assert found_dict, "Dict object not found in surviving objects"
    assert found_list, "List object not found in surviving objects"

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_tracked_objects(filter_objs=surviving_objects)
        if obj.is_created
    }

    # All objects should have creation records
    for obj_id in object_ids:
        assert (
            obj_id in created_objects
        ), f"Object with ID {obj_id} should have a creation record"


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

    with Tracker(output, reference_tracking=True) as tracker:
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
        found = False
        for surviving_obj in surviving_objects:
            if (
                isinstance(surviving_obj, MyClass)
                and surviving_obj.name == obj.name
                and id(surviving_obj) == id(obj)
            ):
                found = True
                break

        assert found, f"Object created in {name} not found in surviving objects"

    # Get tracked objects from the file and create address -> object mapping
    reader = FileReader(output)
    created_objects = {
        obj.address: obj
        for obj in reader.get_tracked_objects(filter_objs=surviving_objects)
        if obj.is_created
    }

    # Verify each thread object has a creation record
    for name, obj in thread_objects.items():
        obj_id = id(obj)
        assert (
            obj_id in created_objects
        ), f"Object for thread {name} should have a creation record"
        tracked_obj = created_objects[obj_id]
        assert (
            tracked_obj.is_created
        ), f"Object for thread {name} should be marked as created"


@requires_at_least_py313
def test_object_stack_trace_with_native_traces(tmp_path):
    # GIVEN
    output = tmp_path / "test.bin"

    # WHEN
    with Tracker(output, native_traces=True, reference_tracking=True) as tracker:
        obj = MyClass("test_object")
        obj_id = id(obj)

    # THEN
    # Get a handle to the file reader
    reader = FileReader(output)
    surviving_objects = tracker.get_surviving_objects()

    # Find our test object
    test_obj = None
    for obj in surviving_objects:
        if isinstance(obj, MyClass) and obj.name == "test_object":
            test_obj = obj
            break

    assert test_obj is not None, "Our test object was not found"

    # Get tracked objects from the file and create address -> object mapping
    created_objects = {
        obj.address: obj
        for obj in reader.get_tracked_objects(filter_objs=surviving_objects)
        if obj.is_created
    }

    # Our object should be in the tracked objects
    assert obj_id in created_objects, "Object ID should be in tracked objects"
    tracked_obj = created_objects[obj_id]

    # Get stack trace for the object
    expected_stack_trace = ("test_object_stack_trace_with_native_traces", __file__, 378)

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
    with Tracker(output, reference_tracking=True):
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
    all_tracked_objects = list(reader.get_tracked_objects())

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
