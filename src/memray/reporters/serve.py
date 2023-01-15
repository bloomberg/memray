import datetime
import json
import re
from functools import partial
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from urllib.parse import urlparse

from memray import FileReader
from memray._memray import compute_statistics
from memray._memray import size_fmt
from memray.commands.common import warn_if_not_enough_symbols
from memray.reporters.flamegraph import FlameGraphReporter
from memray.reporters.templates import get_render_environment


class MemraySever:
    def __init__(self, file_path):
        self.file_path = file_path
        self.reader = FileReader(file_path, report_progress=True)

    def run(self, port=8000):
        server_address = ("", port)
        request_handler = partial(
            RequestHandler, reader=self.reader, file_path=self.file_path
        )
        httpd = HTTPServer(server_address, request_handler)
        print(f"Starting server on port {port}")
        httpd.serve_forever()


class RequestHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, reader, file_path, **kwargs):
        self.reader = reader
        self.file_path = file_path
        super().__init__(*args, **kwargs)

    def _send_response(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(bytes(content, "utf8"))

    def do_GET(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/":
            self._send_response(self._get_index())
        elif parsed_url.path == "/flamegraph":
            self._send_response(self._get_flame_graph())
        else:
            self._send_response("Invalid path", status=404)

    def do_POST(self):
        parsed_url = urlparse(self.path)
        content_length = int(self.headers["Content-Length"])
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.decoder.JSONDecodeError:
            self._send_response("Invalid JSON", status=400)
            return
        if parsed_url.path == "/time":
            self._get_time(data)
        else:
            self._send_response("Invalid path", status=404)

    def _get_index(self):

        stats = compute_statistics(
            str(self.file_path), num_largest=6, report_progress=True
        )
        env = get_render_environment()
        template = env.get_template("stats.html")

        def fmt_collection(collection):
            return [
                {"function": fn, "size": size_fmt(size), "file": f"{file}:{number}"}
                for (fn, file, number), size in collection
            ]

        data = {
            "top_locations_by_count": fmt_collection(stats.top_locations_by_count),
            "top_locations_by_size": fmt_collection(stats.top_locations_by_size),
            "peak": size_fmt(stats.peak_memory_allocated),
            "total": size_fmt(stats.total_memory_allocated),
            "num_allocations": stats.total_num_allocations,
            "num_frames": stats.metadata.total_frames,
            "allocation_count_by_allocator": stats.allocation_count_by_allocator,
        }

        return template.render(
            title="Stats",
            stats=data,
            data=[],
            memory_records=[],
            metadata=self.reader.metadata,
            merge_threads=True,
        )

    def _get_flame_graph(self):
        try:
            if self.reader.metadata.has_native_traces:
                warn_if_not_enough_symbols()
            memory_records = tuple(self.reader.get_memory_snapshots())
        except OSError:
            return "oh no"

        reporter = FlameGraphReporter.from_snapshot(
            allocations=[],
            memory_records=memory_records,
            native_traces=False,
        )
        return reporter.get_html(
            kind="flamegraph_server",
            metadata=self.reader.metadata,
            show_memory_leaks=False,
            merge_threads=True,
            update_url="http://127.0.0.1:8000/time",
        )

    def _get_time(self, data):
        # Get the strings from the request's JSON data
        string1 = data["string1"]
        string2 = data["string2"]

        # Transform the strings to datetime objects
        # Check if the string is 2023-01-16T16:30:19.221Z (some times plotly sends this format)
        if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z", string1):
            string1 = string1.replace("T", " ").replace("Z", "")
        if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z", string2):
            string2 = string2.replace("T", " ").replace("Z", "")

        try:
            time1 = datetime.datetime.strptime(string1, "%Y-%m-%d %H:%M:%S.%f")
            time2 = datetime.datetime.strptime(string2, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            print("Invalid date format. Use 'YYYY-MM-DD HH:MM:SS.sss'")
            return

        # Transform the datetime objects to milliseconds since the epoch
        time1_ms = int(time1.timestamp() * 1000)
        time2_ms = int(time2.timestamp() * 1000)

        records = self.reader.get_range_allocation_records(time1_ms, time2_ms)

        reporter = FlameGraphReporter.from_snapshot(
            allocations=records,
            memory_records=[],
            native_traces=False,
        )
        content = json.dumps({"data": reporter.data})
        self._send_response(content)
