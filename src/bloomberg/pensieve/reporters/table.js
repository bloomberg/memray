function humanFileSize(bytes, dp = 1) {
  if (Math.abs(bytes) < 1024) {
    return bytes + " B";
  }

  const units = ["KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"];
  let u = -1;
  const r = 10 ** dp;

  do {
    bytes /= 1024;
    ++u;
  } while (Math.round(Math.abs(bytes) * r) / r >= 1024 && u < units.length - 1);

  return bytes.toFixed(dp) + " " + units[u];
}

function main() {
  const columns = [
    {
      title: "Thread ID",
      data: "tid",
    },
    {
      title: "Address",
      data: "address",
      render: function (data, type, row, meta) {
        return "0x" + data.toString(16);
      },
    },
    {
      title: "Size",
      data: "size",
      render: function (data, type, row, meta) {
        if (type === "sort" || type === "type") {
          return data;
        }

        return humanFileSize(data);
      },
    },
    {
      title: "Allocator",
      data: "allocator",
    },
    {
      title: "Allocations",
      data: "n_allocations",
    },
    {
      title: "Location",
      data: "stack_trace",
    },
  ];

  var table = $("#the_table").DataTable({
    data: table_data,
    columns: columns,
    order: [[2, "desc"]],
    pageLength: 100,
    dom: "<t>ip",
  });
  const searchButton = $("#searchTerm");
  searchButton.on("input", () => {
    const searchTerm = $("#searchTerm").val();
    table.search(searchTerm).draw();
  });
}

document.addEventListener("DOMContentLoaded", main);
