// For navigable #[integer] fragments
function onClick(d) {
  history.pushState({ id: d.id }, d.data.name, `#${d.id}`);
}

function handleFragments() {
  const id = parseInt(location.hash.substring(1), 10);
  if (!id) return;

  const elem = chart.findById(id);
  if (!elem) return;

  chart.zoomTo(elem);
}

// For the invert button
function onInvert() {
  chart.inverted(!chart.inverted());
  chart.resetZoom();
}

// For search
function onSearch() {
  const termElement = document.getElementById("searchTerm");
  chart.search(termElement.value);
}
// For clear
function onClear() {
  const termElement = document.getElementById("searchTerm");
  // Clear the values
  termElement.value = "";
  chart.search("");
}

// For determining values for the graph
function getChartWidth() {
  // Figure out the width from window size
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return window.innerWidth - 2 * rem;
}

function getTooltip() {
  let tip = d3
    .tip()
    .attr("class", "d3-flame-graph-tip")
    .html((d) => {
      const totalSize = humanFileSize(d.data.value);
      return `${d.data.location}<br>${totalSize} total<br>${d.data.allocations_label}`;
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

function pensieveColorMapper(d, originalColor) {
  // Root node
  if (d.data.name == "<root>") return d3.interpolateYlGn(0.6);
  // Highlighted nodes
  if (d.highlight) return "orange";
  // "builtin" / nodes where we don't have information to present
  if (!d.data.name || d.data.name[0] == "<") return "#EEE";
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
  document.getElementById("searchButton").onclick = onSearch;
  document.getElementById("clearButton").onclick = onClear;
  document.getElementById("searchTerm").addEventListener("keyup", (event) => {
    if (event.key === "Enter") onSearch();
  });
}

var chart = null;
document.addEventListener("DOMContentLoaded", main);
