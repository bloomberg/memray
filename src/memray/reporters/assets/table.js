import { humanFileSize, initMemoryGraph, resizeMemoryGraph } from "./common";
window.resizeMemoryGraph = resizeMemoryGraph;

function main() {
  data = packed_data;

  initMemoryGraph(memory_records);

  const columns = [
    {
      title: "Thread ID",
      data: "tid",
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

  if (merge_threads) {
    // No TID column if we've merged allocations from different threads.
    columns.shift();
  }

  const sizeColumn = columns.findIndex((column) => column.data === "size");
  var table = $("#the_table").DataTable({
    data: data,
    columns: columns,
    order: [[sizeColumn, "desc"]],
    pageLength: 100,
    dom: "<t>ip",
  });
  const searchButton = $("#searchTerm");
  searchButton.on("input", () => {
    const searchTerm = $("#searchTerm").val();
    table.search(searchTerm).draw();
  });
  // Enable tooltips
  $('[data-toggle-second="tooltip"]').tooltip();
  $('[data-toggle="tooltip"]').tooltip();
}

document.addEventListener("DOMContentLoaded", main);
resizeMemoryGraph();
