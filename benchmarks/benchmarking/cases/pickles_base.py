"""Script for testing the performance of pickling/unpickling.

This will pickle/unpickle several real world-representative objects a few
thousand times. The methodology below was chosen for was chosen to be similar
to real-world scenarios which operate on single objects at a time. Note that if
we did something like

    pickle.dumps([dict(some_dict) for _ in range(10000)])

this isn't equivalent to dumping the dict 10000 times: pickle uses a
highly-efficient encoding for the n-1 following copies.
"""

import sys
import datetime
import random
import sys


__author__ = "collinwinter@google.com (Collin Winter)"


DICT = {
    "ads_flags": 0,
    "age": 18,
    "birthday": datetime.date(1980, 5, 7),
    "bulletin_count": 0,
    "comment_count": 0,
    "country": "BR",
    "encrypted_id": "G9urXXAJwjE",
    "favorite_count": 9,
    "first_name": "",
    "flags": 412317970704,
    "friend_count": 0,
    "gender": "m",
    "gender_for_display": "Male",
    "id": 302935349,
    "is_custom_profile_icon": 0,
    "last_name": "",
    "locale_preference": "pt_BR",
    "member": 0,
    "tags": ["a", "b", "c", "d", "e", "f", "g"],
    "profile_foo_id": 827119638,
    "secure_encrypted_id": "Z_xxx2dYx3t4YAdnmfgyKw",
    "session_number": 2,
    "signup_id": "201-19225-223",
    "status": "A",
    "theme": 1,
    "time_created": 1225237014,
    "time_updated": 1233134493,
    "unread_message_count": 0,
    "user_group": "0",
    "username": "collinwinter",
    "play_count": 9,
    "view_count": 7,
    "zip": "",
}

TUPLE = (
    [
        265867233,
        265868503,
        265252341,
        265243910,
        265879514,
        266219766,
        266021701,
        265843726,
        265592821,
        265246784,
        265853180,
        45526486,
        265463699,
        265848143,
        265863062,
        265392591,
        265877490,
        265823665,
        265828884,
        265753032,
    ],
    60,
)


def mutate_dict(orig_dict, random_source):
    new_dict = dict(orig_dict)
    for key, value in new_dict.items():
        rand_val = random_source.random() * sys.maxsize
        if isinstance(key, (int, bytes, str)):
            new_dict[key] = type(key)(rand_val)
    return new_dict


random_source = random.Random(5)  # Fixed seed.
DICT_GROUP = [mutate_dict(DICT, random_source) for _ in range(3)]


def bench_pickle(loops, pickle, protocol):
    range_it = range(loops)

    # micro-optimization: use fast local variables
    dumps = pickle.dumps
    objs = (DICT, TUPLE, DICT_GROUP)
    for _ in range_it:
        for obj in objs:
            # 20 dumps
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)
            dumps(obj, protocol)


def bench_unpickle(loops, pickle, protocol):
    pickled_dict = pickle.dumps(DICT, protocol)
    pickled_tuple = pickle.dumps(TUPLE, protocol)
    pickled_dict_group = pickle.dumps(DICT_GROUP, protocol)
    range_it = range(loops)

    # micro-optimization: use fast local variables
    loads = pickle.loads
    objs = (pickled_dict, pickled_tuple, pickled_dict_group)

    for _ in range_it:
        for obj in objs:
            # 20 loads dict
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)
            loads(obj)


LIST = [[list(range(10)), list(range(10))] for _ in range(10)]


def bench_pickle_list(loops, pickle, protocol):
    range_it = range(loops)
    # micro-optimization: use fast local variables
    dumps = pickle.dumps
    obj = LIST
    protocol = protocol

    for _ in range_it:
        # 10 dumps list
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)
        dumps(obj, protocol)


def bench_unpickle_list(loops, pickle, protocol):
    pickled_list = pickle.dumps(LIST, protocol)
    range_it = range(loops)

    # micro-optimization: use fast local variables
    loads = pickle.loads

    for _ in range_it:
        # 10 loads list
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)
        loads(pickled_list)


MICRO_DICT = dict((key, dict.fromkeys(range(10))) for key in range(100))


def bench_pickle_dict(loops, pickle, protocol):
    range_it = range(loops)
    # micro-optimization: use fast local variables
    protocol = protocol
    obj = MICRO_DICT

    for _ in range_it:
        # 5 dumps dict
        pickle.dumps(obj, protocol)
        pickle.dumps(obj, protocol)
        pickle.dumps(obj, protocol)
        pickle.dumps(obj, protocol)
        pickle.dumps(obj, protocol)


BENCHMARKS = {
    # 20 inner-loops: don't count the 3 pickled objects
    "pickle": (bench_pickle, 20),
    # 20 inner-loops: don't count the 3 unpickled objects
    "unpickle": (bench_unpickle, 20),
    "pickle_list": (bench_pickle_list, 10),
    "unpickle_list": (bench_unpickle_list, 10),
    "pickle_dict": (bench_pickle_dict, 5),
}


def is_accelerated_module(module):
    return getattr(module.Pickler, "__module__", "<jython>") != "pickle"


def add_cmdline_args(cmd, args):
    if args.pure_python:
        cmd.append("--pure-python")
    cmd.extend(("--protocol", str(args.protocol)))
    cmd.append(args.benchmark)


def run_benchmark_pure_python(benchmark):
    benchmarks = sorted(BENCHMARKS)
    benchmark, inner_loops = BENCHMARKS[benchmark]
    sys.modules["_pickle"] = None
    import pickle

    if is_accelerated_module(pickle):
        raise RuntimeError("Unexpected C accelerators for pickle")
    benchmark(1, pickle, pickle.HIGHEST_PROTOCOL)


def run_benchmark_c(benchmark):
    benchmarks = sorted(BENCHMARKS)
    benchmark, inner_loops = BENCHMARKS[benchmark]
    import pickle

    if not is_accelerated_module(pickle):
        raise RuntimeError("Missing C accelerators for pickle")
    benchmark(1, pickle, pickle.HIGHEST_PROTOCOL)


if __name__ == "__main__":
    bench = sys.argv[1]
    if sys.argv[2] == "--pure-python":
        run_benchmark_pure_python(bench)
    else:
        run_benchmark_c(bench)
