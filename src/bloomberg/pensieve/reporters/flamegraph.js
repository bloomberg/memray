var chart = flamegraph()
  .width(1080)
  .cellHeight(18)
  .transitionDuration(750)
  .minFrameSize(5)
  .transitionEase(d3.easeCubic)
  .title("")
  .onClick(onClick)
  .selfValue(false)
  .setColorMapper((d, originalColor) =>
    d.highlight ? "#6aff8f" : originalColor
  );
chart.setDetailsElement(document.getElementById("details"));

// Setup the tooltip
var tooltip = flamegraph.tooltip
  .defaultFlamegraphTooltip()
  .html(function (node) {
    var d = node.data;
    return `${d.value} in ${d.function} at ${d.filename}:${d.lineno}`;
  });
chart.tooltip(tooltip);


function invokeFind() {
  var searchId = parseInt(location.hash.substring(1), 10);
  if (searchId) {
    find(searchId);
  }
}

var data = {{ flamegraph_data }};
d3.select("#chart").datum(data).call(chart).call(invokeFind);

document
  .getElementById("form")
  .addEventListener("submit", function (event) {
    event.preventDefault();
    search();
  });

function search() {
  var term = document.getElementById("term").value;
  chart.search(term);
}

function find(id) {
  var elem = chart.findById(id);
  if (elem) {
    console.log(elem);
    chart.zoomTo(elem);
  }
}

function clear() {
  document.getElementById("term").value = "";
  chart.clear();
}

function resetZoom() {
  chart.resetZoom();
}

function onClick(d) {
  console.info(`Clicked on ${d.data.name}, id: "${d.id}"`);
  history.pushState({ id: d.id }, d.data.name, `#${d.id}`);
}
