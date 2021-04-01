// For navigable #[integer] fragments
function getCurrentId() {
  if (location.hash) {
    return parseInt(location.hash.substring(1), 10);
  } else {
    return 0;
  }
}

function onClick(d) {
  if (d.id == getCurrentId()) {
    console.log(`Push to history skipped: ${d.id} (already current)`);
  } else {
    console.log(`Push to history: ${d.id}`);
    history.pushState({ id: d.id }, d.data.name, `#${d.id}`);
  }
}

function handleFragments() {
  const id = getCurrentId();
  const elem = chart.findById(id);
  if (!elem) return;

  console.log(`Zoom to: ${id}`);
  chart.zoomTo(elem);
}

// For the invert button
function onInvert() {
  console.log("Invert chart");
  chart.inverted(!chart.inverted());
  console.log("Reset zoom");
  chart.resetZoom();
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
  d3.select("#chart").datum(data).call(chart);

  // Set zoom to the root element.
  if (!location.hash) {
    console.log("hello!");
  } else {
    // zoom to correct element, if available
    handleFragments();
  }

  // Setup event handlers
  document.getElementById("invertButton").onclick = onInvert;
  document.getElementById("searchTerm").addEventListener("input", () => {
    const termElement = document.getElementById("searchTerm");
    chart.search(termElement.value);
  });

  window.addEventListener("popstate", handleFragments);
}

var chart = null;
document.addEventListener("DOMContentLoaded", main);
