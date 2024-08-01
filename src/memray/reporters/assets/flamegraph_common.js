import {
  filterChildThreads,
  filterUninteresting,
  filterImportSystem,
  humanFileSize,
  makeTooltipString,
  sumAllocations,
} from "./common";

const FILTER_UNINTERESTING = "filter_uninteresting";
const FILTER_IMPORT_SYSTEM = "filter_import_system";
const FILTER_THREAD = "filter_thread";

class FilteredChart {
  constructor() {
    this.filters = {};
  }
  registerFilter(name, func) {
    this.filters[name] = func;
  }
  unRegisterFilter(name) {
    delete this.filters[name];
  }

  drawChart(data) {
    let filtered = data;
    _.forOwn(this.filters, (func) => {
      filtered = func(filtered);
    });
    drawChart(filtered);
    // Merge 0 additional elements, triggering a redraw
    chart.merge([]);
  }
}

var chart = null;
let filteredChart = new FilteredChart();

export function getFlamegraph() {
  return chart;
}

export function getFilteredChart() {
  return filteredChart;
}

// For navigable #[integer] fragments
function getCurrentId() {
  if (location.hash) {
    return parseInt(location.hash.substring(1), 10);
  } else {
    return 0;
  }
}

function updateZoomButtom() {
  document.getElementById("resetZoomButton").disabled = getCurrentId() == 0;
}

function onClick(d) {
  if (d.id == getCurrentId()) return;

  history.pushState({ id: d.id }, d.data.name, `#${d.id}`);
  updateZoomButtom();
}

export function handleFragments() {
  const id = getCurrentId();
  const elem = chart.findById(id);
  if (!elem) return;

  chart.zoomTo(elem);
  updateZoomButtom();
}

// For the invert button
export function onInvert() {
  chart.inverted(this === document.getElementById("icicles"));
  chart.resetZoom(); // calls onClick

  // Hide the tooltip for the radio button that was just clicked.
  $('[data-toggle="tooltip"]').tooltip("hide");
}

export function onResetZoom() {
  chart.resetZoom(); // calls onClick
}

// For window resizing
function getChartWidth() {
  // Return the display width of the div we're drawing into
  return document.getElementById("chart").clientWidth;
}

export function onResize() {
  filteredChart.drawChart(data);

  // Set zoom to correct element
  if (location.hash) {
    handleFragments();
  }
}

export function onFilterThread() {
  const thread_id = this.dataset.thread;
  if (thread_id === "-0x1") {
    // Reset
    filteredChart.unRegisterFilter(FILTER_THREAD);
  } else {
    filteredChart.registerFilter(FILTER_THREAD, (data) => {
      let filteredData = filterChildThreads(data, thread_id);
      const totalAllocations = sumAllocations(filteredData.children);
      _.defaults(totalAllocations, filteredData);
      filteredData.n_allocations = totalAllocations.n_allocations;
      filteredData.value = totalAllocations.value;
      return filteredData;
    });
  }
  filteredChart.drawChart(data);
}

export function onFilterUninteresting() {
  if (this.hideUninterestingFrames === undefined) {
    // Hide boring frames by default
    this.hideUninterestingFrames = true;
  }
  if (this.hideUninterestingFrames === true) {
    this.hideUninterestingFrames = true;

    filteredChart.registerFilter(FILTER_UNINTERESTING, (data) => {
      return filterUninteresting(data);
    });
  } else {
    filteredChart.unRegisterFilter(FILTER_UNINTERESTING);
  }
  this.hideUninterestingFrames = !this.hideUninterestingFrames;
  filteredChart.drawChart(data);
}

export function onFilterImportSystem() {
  if (this.hideImportSystemFrames === undefined) {
    this.hideImportSystemFrames = true;
  }
  if (this.hideImportSystemFrames === true) {
    this.hideImportSystemFrames = true;
    if (!inverted) {
      filteredChart.registerFilter(FILTER_IMPORT_SYSTEM, (data) => {
        return filterImportSystem(data);
      });
    } else {
      data = invertedNoImportsData;
      if (temporal) {
        hideImports = true;
        intervals = invertedNoImportsIntervals;
      }
    }
  } else {
    filteredChart.unRegisterFilter(FILTER_IMPORT_SYSTEM);
    data = flamegraphData;
    if (temporal) {
      hideImports = false;
      intervals = flamegraphIntervals;
    }
  }
  this.hideImportSystemFrames = !this.hideImportSystemFrames;
  filteredChart.drawChart(data);
}

// For determining values for the graph
function getTooltip() {
  let tip = d3
    .tip()
    .attr("class", "d3-flame-graph-tip")
    .html((d) => {
      const totalSize = humanFileSize(d.data.value);
      return makeTooltipString(d.data, totalSize, merge_threads);
    })
    .direction((d) => {
      const midpoint = (d.x1 + d.x0) / 2;
      // If the midpoint is in a reasonable location, put it below the element.
      if (0.25 < midpoint && midpoint < 0.75) {
        return "s";
      }
      // We're far from the right
      if (d.x1 < 0.75) {
        return "e";
      }
      // We're far from the left
      if (d.x0 > 0.25) {
        return "w";
      }
      // This shouldn't happen reasonably? If it does, just put it above and
      // we'll deal with it later. :)
      return "n";
    });
  return tip;
}

// Our custom color mapping logic
export function decimalHash(string) {
  let sum = 0;
  for (let i = 0; i < string.length; i++)
    sum += ((i + 1) * string.codePointAt(i)) / (1 << 8);
  return sum % 1;
}

function fileExtension(filename) {
  if (filename === undefined) return filename;
  return (
    filename.substring(filename.lastIndexOf(".") + 1, filename.length) ||
    filename
  );
}

function colorByExtension(extension) {
  if (extension == "py") {
    return d3.schemePastel1[2];
  } else if (extension == "c" || extension == "cpp" || extension == "h") {
    return d3.schemePastel1[5];
  } else {
    return d3.schemePastel1[8];
  }
}

function memrayColorMapper(d, originalColor) {
  // Highlighted nodes
  if (d.highlight) {
    return "orange";
  }
  // "builtin" / nodes that we don't want to highlight
  if (!d.data.name || !d.data.location) {
    return "#EEE";
  }

  return colorByExtension(fileExtension(d.data.location[1]));
}

// Show the 'Threads' dropdown if we have thread data, and populate it
export function initThreadsDropdown(data, merge_threads) {
  if (merge_threads === true) {
    return;
  }
  const threads = data.unique_threads;
  if (!threads || threads.length <= 1) {
    return;
  }

  document.getElementById("threadsDropdown").removeAttribute("hidden");
  const threadsDropdownList = document.getElementById("threadsDropdownList");
  for (const thread of threads) {
    let elem = document.createElement("a");
    elem.className = "dropdown-item";
    elem.dataset.thread = thread;
    elem.text = thread;
    elem.onclick = onFilterThread;
    threadsDropdownList.appendChild(elem);
  }
}

export function drawChart(chart_data) {
  // Retain the "invertedness" if there's an existing graph.
  let invert = chart ? chart.inverted() : true;

  // Clear any existing chart
  if (chart) {
    chart.destroy();
    d3.selectAll(".d3-flame-graph-tip").remove();
  }

  // Create the chart
  chart = flamegraph()
    .width(getChartWidth())
    // smooth transitions
    .transitionDuration(250)
    .transitionEase(d3.easeCubic)
    .inverted(invert)
    // make each row a little taller
    .cellHeight(20)
    // don't show elements that are less than 5px wide
    .minFrameSize(2)
    // set our custom handlers
    .setColorMapper(memrayColorMapper)
    .onClick(onClick)
    .tooltip(getTooltip());

  // Render the chart
  d3.select("#chart").datum(chart_data).call(chart);

  // Rendering the chart can add a scroll bar, so the width may have changed.
  chart.width(getChartWidth());
}
