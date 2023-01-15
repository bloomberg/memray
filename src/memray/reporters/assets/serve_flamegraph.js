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

var active_plots = [];
var current_dimensions = null;

function initMemoryGraph(memory_records) {
  const time = memory_records.map((a) => new Date(a[0]));
  const resident_size = memory_records.map((a) => a[1]);
  const heap_size = memory_records.map((a) => a[2]);

  var resident_size_plot = {
    x: time,
    y: resident_size,
    mode: "lines",
    name: "Resident size",
  };

  var heap_size_plot = {
    x: time,
    y: heap_size,
    mode: "lines",
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
    console.assert(active_plots.length == 0);
    active_plots.push(plot);
  });
}

function showLoadingAnimation() {
  document.getElementById("loading").style.display = "block";
  document.getElementById("overlay").style.display = "block";
}

function hideLoadingAnimation() {
  document.getElementById("loading").style.display = "none";
  document.getElementById("overlay").style.display = "none";
}

function refreshFlamegraph(event) {
  let request_data = getRangeData(event);

  if (
    current_dimensions != null &&
    JSON.stringify(request_data) === JSON.stringify(current_dimensions)
  ) {
    return;
  }

  showLoadingAnimation();

  current_dimensions = request_data;

  fetch(update_url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request_data),
  })
    .then((response) => response.json())
    .then((the_data) => {
      data = the_data["data"];
      getFilteredChart().drawChart(data);
      hideLoadingAnimation();
    })
    .catch((error) => {
      console.error(error);
      hideLoadingAnimation();
    });
}

function getRangeData(event) {
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
  } else if (active_plots.length == 1) {
    let the_range = active_plots[0].layout.xaxis.range;
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
  if (debounce) {
    clearTimeout(debounce);
  }
  debounce = setTimeout(function () {
    refreshFlamegraph(event);
  }, 500);
}

// Main entrypoint
function main() {
  initThreadsDropdown(data, merge_threads);

  initMemoryGraph(memory_records);

  // Create the flamegraph renderer
  drawChart(data);

  // Set zoom to correct element
  if (location.hash) {
    handleFragments();
  }

  // Setup event handlers
  document.getElementById("invertButton").onclick = onInvert;
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
  document
    .getElementById("plot")
    .on("plotly_relayout", refreshFlamegraphDebounced);

  // Set up initial data
  refreshFlamegraphDebounced({});

  // Enable toasts
  var toastElList = [].slice.call(document.querySelectorAll(".toast"));
  var toastList = toastElList.map(function (toastEl) {
    return new bootstrap.Toast(toastEl, { delay: 10000 });
  });
  toastList.forEach((toast) => toast.show()); // This show them
}

document.addEventListener("DOMContentLoaded", main);
