// For navigable #[integer] fragments
function onClick(d) {
  history.pushState({ id: d.id }, d.data.name, `#${d.id}`);
}

function handleFragments() {
  var id = parseInt(location.hash.substring(1), 10);
  if (!id) return;

  var elem = chart.findById(id);
  if (!elem) return;

  chart.zoomTo(elem);
}

// For the invert button
function onInvert() {
  chart.inverted(!chart.inverted());
  chart.resetZoom();
}

// For search
function onSearchEvent(e) {
  if (e.submitter.innerText == "Clear") {
    e.target[0].value = "";
  }
  var term = e.target[0].value;
  chart.search(term);
}

// For determining values for the graph
function getChartWidth() {
  // Figure out the width from window size
  var rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return window.innerWidth - 2 * rem;
}
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

function getTooltip() {
  return flamegraph.tooltip.defaultFlamegraphTooltip().html((d) => {
    let totalSize = humanFileSize(d.data.value);
    return `${d.data.tooltip}<br>${totalSize} total`;
  });
}

// Our custom color mapping logic
function decimalHash(string) {
  let sum = 0;
  for (let i = 0; i < string.length; i++)
    sum += ((i + 1) * string.codePointAt(i)) / (1 << 8);
  return sum % 1;
}

function pensieveColorMapper(d, originalColor) {
  // Highlights are blue-ish
  if (d.highlight) return "orange";
  // Fallback to the "yellow-green" colors
  return d3.interpolateYlGn(0.1 + decimalHash(d.data.name) / 2);
}

// Main entrypoint
function main() {
  // Create the flamegraph renderer
  chart = flamegraph()
    .width(getChartWidth())
    // smooth transitions
    .transitionDuration(500)
    .transitionEase(d3.easeCubic)
    // make each row a little taller
    .cellHeight(20)
    // don't show elements that are less than 5px wide
    .minFrameSize(2)
    // set our custom handlers
    .setColorMapper(pensieveColorMapper)
    .onClick(onClick)
    .tooltip(getTooltip());

  // Render the chart
  d3.select("#chart").datum(flamegraph_data).call(chart);

  // zoom to correct element, if available
  handleFragments();

  // Setup event handlers
  document.getElementById("invertButton").onclick = onInvert;
  document.getElementById("searchForm").onsubmit = onSearchEvent;
}

var chart = null;
document.addEventListener("DOMContentLoaded", main);
