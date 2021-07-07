import {
  debounced,
  filterChildThreads,
  humanFileSize,
  makeTooltipString,
  sumAllocations,
} from "./common";

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

function handleFragments() {
  const id = getCurrentId();
  const elem = chart.findById(id);
  if (!elem) return;

  chart.zoomTo(elem);
  updateZoomButtom();
}

// For the invert button
function onInvert() {
  chart.inverted(!chart.inverted());
  chart.resetZoom(); // calls onClick
}

function onResetZoom() {
  chart.resetZoom(); // calls onClick
}

// For window resizing
function getChartWidth() {
  // Figure out the width from window size
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return window.innerWidth - 2 * rem;
}

function onResize() {
  const width = getChartWidth();
  // Update element widths
  const svg = document.getElementById("chart").children[0];
  svg.setAttribute("width", width);
  chart.width(width);
  // Merge 0 additional elements, triggering a redraw
  chart.merge([]);
}

// Handle
function onFilterThread() {
  const thread_id = parseInt(this.dataset.thread, 10);
  if (thread_id === -1) {
    // Reset
    drawChart(data);
  } else {
    let filteredData = filterChildThreads(data, thread_id);
    console.log(JSON.stringify(filteredData));
    const totalAllocations = sumAllocations(filteredData.children);
    console.log(JSON.stringify(filteredData));
    // _.defaults(totalAllocations, filteredData);
    filteredData.n_allocations = totalAllocations.n_allocations;
    filteredData.value = totalAllocations.value;
    console.log(JSON.stringify(filteredData));
    drawChart(filteredData);
  }
  chart.merge([]);
}

// For determining values for the graph
function getTooltip() {
  let tip = d3
    .tip()
    .attr("class", "d3-flame-graph-tip")
    .html((d) => {
      console.log(`Generating tooltip for node: ${JSON.stringify(d.data)}`);
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
function decimalHash(string) {
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
  if (extension == "py" || extension == "pyx") {
    return d3.schemePastel1[2];
  } else if (extension == "c" || extension == "cpp" || extension == "h") {
    return d3.schemePastel1[5];
  } else {
    return d3.schemePastel1[8];
  }
}

function pensieveColorMapper(d, originalColor) {
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
function initThreadsDropdown(data, merge_threads) {
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

function drawChart(chart_data) {
  chart = flamegraph()
    .width(getChartWidth())
    // smooth transitions
    .transitionDuration(250)
    .transitionEase(d3.easeCubic)
    // invert the graph by default
    .inverted(true)
    // make each row a little taller
    .cellHeight(20)
    // don't show elements that are less than 5px wide
    .minFrameSize(2)
    // set our custom handlers
    .setColorMapper(pensieveColorMapper)
    .onClick(onClick)
    .tooltip(getTooltip());

  // Render the chart
  d3.select("#chart").datum(chart_data).call(chart);
}

// Main entrypoint
function main() {
  initThreadsDropdown(data, merge_threads);

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

  document.onkeyup = (event) => {
    if (event.code == "Escape") {
      onResetZoom();
    }
  };
  document.getElementById("searchTerm").addEventListener("input", () => {
    const termElement = document.getElementById("searchTerm");
    chart.search(termElement.value);
  });

  window.addEventListener("popstate", handleFragments);
  window.addEventListener("resize", debounced(onResize));

  // Enable tooltips
  $('[data-toggle-second="tooltip"]').tooltip();
}

var chart = null;
document.addEventListener("DOMContentLoaded", main);
