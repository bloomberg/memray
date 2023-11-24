import { debounced } from "./common";

import {
  initThreadsDropdown,
  drawChart,
  handleFragments,
  onFilterUninteresting,
  onFilterImportSystem,
  onFilterThread,
  onResetZoom,
  onResize,
  onInvert,
  getFilteredChart,
  getFlamegraph,
} from "./flamegraph_common";

var active_plot = null;
var current_dimensions = null;

var parent_index_by_child_index = generateParentIndexes(packed_data.nodes);
var inverted_no_imports_parent_index_by_child_index = inverted
  ? generateParentIndexes(packed_data.inverted_no_imports_nodes)
  : null;

function generateParentIndexes(nodes) {
  let ret = new Array(nodes.children.length);
  console.log("finding parent index for each node");
  for (const [parentIndex, children] of nodes.children.entries()) {
    children.forEach((idx) => (ret[idx] = parentIndex));
  }
  console.assert(ret[0] === undefined, "root node has a parent");
  return ret;
}

function generateNodeObjects(strings, nodes) {
  console.log("constructing nodes");
  const node_objects = nodes.name.map((_, i) => ({
    name: strings[nodes["name"][i]],
    location: [
      strings[nodes["function"][i]],
      strings[nodes["filename"][i]],
      nodes["lineno"][i],
    ],
    value: 0,
    children: nodes["children"][i],
    n_allocations: 0,
    thread_id: strings[nodes["thread_id"][i]],
    interesting: nodes["interesting"][i] !== 0,
    import_system: nodes["import_system"][i] !== 0,
  }));

  console.log("mapping child indices to child nodes");
  for (const [parentIndex, node] of node_objects.entries()) {
    node["children"] = node["children"].map((idx) => node_objects[idx]);
  }

  return node_objects;
}

function initTrees(packedData) {
  const {
    strings,
    nodes,
    inverted_no_imports_nodes,
    unique_threads,
    intervals,
    no_imports_interval_list,
  } = packedData;

  const flamegraphNodeObjects = generateNodeObjects(strings, nodes);
  const invertedNoImportsNodeObjects = inverted
    ? generateNodeObjects(strings, inverted_no_imports_nodes)
    : null;

  flamegraphIntervals = intervals;
  invertedNoImportsIntervals = no_imports_interval_list;

  return {
    flamegraphNodeObjects: flamegraphNodeObjects,
    invertedNoImportsNodeObjects: invertedNoImportsNodeObjects,
  };
}

function findHWMAllocations(
  intervals,
  node_objects,
  hwmSnapshot,
  parent_index_by_child_index,
) {
  intervals.forEach((interval) => {
    let [allocBefore, deallocBefore, nodeIndex, count, bytes] = interval;

    if (
      allocBefore <= hwmSnapshot &&
      (deallocBefore === null || deallocBefore > hwmSnapshot)
    ) {
      while (nodeIndex !== undefined) {
        node_objects[nodeIndex].n_allocations += count;
        node_objects[nodeIndex].value += bytes;
        nodeIndex = parent_index_by_child_index[nodeIndex];
      }
    }
  });
}

function findLeakedAllocations(
  intervals,
  node_objects,
  rangeStart,
  rangeEnd,
  parent_index_by_child_index,
) {
  intervals.forEach((interval) => {
    let [allocBefore, deallocBefore, nodeIndex, count, bytes] = interval;

    if (
      allocBefore >= rangeStart &&
      allocBefore <= rangeEnd &&
      (deallocBefore === null || deallocBefore > rangeEnd)
    ) {
      while (nodeIndex !== undefined) {
        node_objects[nodeIndex].n_allocations += count;
        node_objects[nodeIndex].value += bytes;
        nodeIndex = parent_index_by_child_index[nodeIndex];
      }
    }
  });
}

function packedDataToTree(packedData, rangeStart, rangeEnd) {
  const { flamegraphNodeObjects, invertedNoImportsNodeObjects } =
    initTrees(packedData);

  const hwms = packedData.high_water_mark_by_snapshot;
  if (hwms) {
    console.log("finding highest high water mark in range");
    let hwmSnapshot = rangeStart;
    let hwmBytes = hwms[rangeStart];
    for (let i = rangeStart; i <= rangeEnd; ++i) {
      if (hwms[i] > hwmBytes) {
        hwmBytes = hwms[i];
        hwmSnapshot = i;
      }
    }
    console.log(
      "highest water mark between " +
        rangeStart +
        " and " +
        rangeEnd +
        " is " +
        hwmBytes +
        " at " +
        hwmSnapshot,
    );

    let plotUpdate = { shapes: [] };
    let startTime, endTime;
    if (hwmSnapshot == memory_records.length) {
      // HWM was after the last snapshot. Highlight 10ms past it.
      // Widen the x-axis range so the highlight is shown.
      plotUpdate["xaxis.range[1]"] = new Date(memory_records.at(-1)[0] + 10);
      startTime = new Date(memory_records.at(-1)[0]);
      endTime = new Date(memory_records.at(-1)[0] + 10);
    } else if (hwmSnapshot == 0) {
      // HWM was before the first snapshot. Highlight 10ms before it.
      // Widen the x-axis range so the highlight is shown.
      plotUpdate["xaxis.range[0]"] = new Date(memory_records[0][0] - 10);
      startTime = new Date(memory_records[0][0] - 10);
      endTime = new Date(memory_records[0][0]);
    } else {
      // HWM was between two snapshots. Highlight from one to the other.
      startTime = new Date(memory_records[hwmSnapshot - 1][0]);
      endTime = new Date(memory_records[hwmSnapshot][0]);
    }

    plotUpdate["shapes"] = [
      {
        type: "rect",
        xref: "x",
        yref: "paper",
        x0: startTime,
        y0: 0,
        x1: endTime,
        y1: 1,
        fillcolor: "#fbff00",
        opacity: 0.2,
        line: {
          width: 0,
        },
      },
    ];
    Plotly.relayout("plot", plotUpdate);

    // We could binary search rather than using a linear scan...
    console.log("finding hwm allocations");
    findHWMAllocations(
      flamegraphIntervals,
      flamegraphNodeObjects,
      hwmSnapshot,
      parent_index_by_child_index,
    );
    if (inverted) {
      findHWMAllocations(
        invertedNoImportsIntervals,
        invertedNoImportsNodeObjects,
        hwmSnapshot,
        inverted_no_imports_parent_index_by_child_index,
      );
    }
  } else {
    // We could binary search rather than using a linear scan...
    console.log("finding leaked allocations");
    findLeakedAllocations(
      flamegraphIntervals,
      flamegraphNodeObjects,
      rangeStart,
      rangeEnd,
      parent_index_by_child_index,
    );
    if (inverted) {
      findLeakedAllocations(
        invertedNoImportsIntervals,
        invertedNoImportsNodeObjects,
        rangeStart,
        rangeEnd,
        inverted_no_imports_parent_index_by_child_index,
      );
    }
  }

  flamegraphNodeObjects.forEach((node) => {
    node.children = node.children.filter((node) => node.n_allocations > 0);
  });

  if (inverted) {
    invertedNoImportsNodeObjects.forEach((node) => {
      node.children = node.children.filter((node) => node.n_allocations > 0);
    });
  }

  flamegraphData = flamegraphNodeObjects[0];
  invertedNoImportsData = inverted ? invertedNoImportsNodeObjects[0] : null;
}

function initMemoryGraph(memory_records) {
  console.log("init memory graph");
  const time = memory_records.map((a) => new Date(a[0]));
  const resident_size = memory_records.map((a) => a[1]);
  const heap_size = memory_records.map((a) => a[2]);
  const mode = memory_records.length > 1 ? "lines" : "markers";

  var resident_size_plot = {
    x: time,
    y: resident_size,
    mode: mode,
    name: "Resident size",
  };

  var heap_size_plot = {
    x: time,
    y: heap_size,
    mode: mode,
    name: "Heap size",
  };

  var plot_data = [resident_size_plot, heap_size_plot];
  var config = {
    responsive: true,
    displayModeBar: false,
  };
  var layout = {
    xaxis: {
      title: {
        text: "Time",
      },
      rangeslider: {
        visible: true,
      },
    },
    yaxis: {
      title: {
        text: "Memory Size",
      },
      tickformat: ".4~s",
      exponentformat: "B",
      ticksuffix: "B",
    },
  };

  Plotly.newPlot("plot", plot_data, layout, config).then((plot) => {
    console.assert(active_plot === null);
    active_plot = plot;
  });
}

function showLoadingAnimation() {
  console.log("showLoadingAnimation");
  document.getElementById("loading").style.display = "block";
  document.getElementById("overlay").style.display = "block";
}

function hideLoadingAnimation() {
  console.log("hideLoadingAnimation");
  document.getElementById("loading").style.display = "none";
  document.getElementById("overlay").style.display = "none";
}

function refreshFlamegraph(event) {
  console.log("refreshing flame graph!");

  let request_data = getRangeData(event);
  console.log("range data: " + JSON.stringify(request_data));

  if (
    current_dimensions != null &&
    JSON.stringify(request_data) === JSON.stringify(current_dimensions)
  ) {
    return;
  }

  console.log("showing loading animation");
  showLoadingAnimation();

  current_dimensions = request_data;

  console.log("finding range of relevant snapshot");

  let idx0 = 0;
  let idx1 = memory_records.length;

  if (request_data) {
    const t0 = new Date(request_data.string1).getTime();
    const t0_idx = memory_records.findIndex((rec) => rec[0] >= t0);
    if (t0_idx != -1) idx0 = t0_idx;

    const t1 = new Date(request_data.string2).getTime();
    const t1_idx = memory_records.findIndex((rec) => rec[0] > t1);
    if (t1_idx != -1) idx1 = t1_idx;
  }

  console.log("start index is " + idx0);
  console.log("end index is " + idx1);
  console.log("first possible index is 0");
  console.log("last possible index is " + memory_records.length);

  console.log("constructing tree");
  packedDataToTree(packed_data, idx0, idx1);

  data = inverted && hideImports ? invertedNoImportsData : flamegraphData;
  intervals =
    inverted && hideImports ? invertedNoImportsIntervals : flamegraphIntervals;

  console.log("total allocations in range: " + data.n_allocations);
  console.log("total bytes in range: " + data.value);

  console.log("drawing chart");
  getFilteredChart().drawChart(data);
  console.log("hiding loading animation");
  hideLoadingAnimation();
}

function getRangeData(event) {
  console.log("getRangeData");
  let request_data = {};
  if (event.hasOwnProperty("xaxis.range[0]")) {
    request_data = {
      string1: event["xaxis.range[0]"],
      string2: event["xaxis.range[1]"],
    };
  } else if (event.hasOwnProperty("xaxis.range")) {
    request_data = {
      string1: event["xaxis.range"][0],
      string2: event["xaxis.range"][1],
    };
  } else if (active_plot !== null) {
    let the_range = active_plot.layout.xaxis.range;
    request_data = {
      string1: the_range[0],
      string2: the_range[1],
    };
  } else {
    return;
  }
  return request_data;
}

var debounce = null;
function refreshFlamegraphDebounced(event) {
  console.log("refreshFlamegraphDebounced");
  if (debounce) {
    clearTimeout(debounce);
  }
  debounce = setTimeout(function () {
    refreshFlamegraph(event);
  }, 500);
}

// Main entrypoint
function main() {
  console.log("main");

  const unique_threads = packed_data.unique_threads.map(
    (tid) => packed_data.strings[tid],
  );
  initThreadsDropdown({ unique_threads: unique_threads }, merge_threads);

  initMemoryGraph(memory_records);

  // Draw the initial flame graph
  refreshFlamegraph({});

  // Set zoom to correct element
  if (location.hash) {
    handleFragments();
  }

  // Setup event handlers
  document.getElementById("icicles").onchange = onInvert;
  document.getElementById("flames").onchange = onInvert;
  document.getElementById("resetZoomButton").onclick = onResetZoom;
  document.getElementById("resetThreadFilterItem").onclick = onFilterThread;
  let hideUninterestingCheckBox = document.getElementById("hideUninteresting");
  hideUninterestingCheckBox.onclick = onFilterUninteresting.bind(this);
  let hideImportSystemCheckBox = document.getElementById("hideImportSystem");
  hideImportSystemCheckBox.onclick = onFilterImportSystem.bind(this);
  // Enable filtering by default
  onFilterUninteresting.bind(this)();

  document.onkeyup = (event) => {
    if (event.code == "Escape") {
      onResetZoom();
    }
  };
  document.getElementById("searchTerm").addEventListener("input", () => {
    const termElement = document.getElementById("searchTerm");
    getFlamegraph().search(termElement.value);
  });

  window.addEventListener("popstate", handleFragments);
  window.addEventListener("resize", debounced(onResize));

  // Enable tooltips
  $('[data-toggle-second="tooltip"]').tooltip();
  $('[data-toggle="tooltip"]').tooltip();

  // Set up the reload handler
  console.log("setup reload handler");
  document
    .getElementById("plot")
    .on("plotly_relayout", refreshFlamegraphDebounced);

  // Enable toasts
  var toastElList = [].slice.call(document.querySelectorAll(".toast"));
  var toastList = toastElList.map(function (toastEl) {
    return new bootstrap.Toast(toastEl, { delay: 10000 });
  });
  toastList.forEach((toast) => toast.show());
}

document.addEventListener("DOMContentLoaded", main);
