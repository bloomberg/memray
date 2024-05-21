import { debounced, initMemoryGraph, resizeMemoryGraph } from "./common";

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
  getFlamegraph,
} from "./flamegraph_common";

window.resizeMemoryGraph = resizeMemoryGraph;

function packedDataToTree(packedData) {
  const { strings, nodes, unique_threads } = packedData;

  const node_objects = nodes.name.map((_, i) => ({
    name: strings[nodes["name"][i]],
    location: [
      strings[nodes["function"][i]],
      strings[nodes["filename"][i]],
      nodes["lineno"][i],
    ],
    value: nodes["value"][i],
    children: nodes["children"][i],
    n_allocations: nodes["n_allocations"][i],
    thread_id: strings[nodes["thread_id"][i]],
    interesting: nodes["interesting"][i] !== 0,
    import_system: nodes["import_system"][i] !== 0,
  }));

  for (const node of node_objects) {
    node["children"] = node["children"].map((idx) => node_objects[idx]);
  }

  const root = node_objects[0];
  root["unique_threads"] = unique_threads.map((tid) => strings[tid]);
  return root;
}

function initTrees(packedData) {
  const { strings, nodes, inverted_no_imports_nodes, unique_threads } =
    packedData;
  flamegraphData = packedDataToTree({
    strings: strings,
    nodes: nodes,
    unique_threads: unique_threads,
  });

  invertedNoImportsData = inverted
    ? packedDataToTree({
        strings: strings,
        nodes: inverted_no_imports_nodes,
        unique_threads: unique_threads,
      })
    : null;

  data = flamegraphData;
}

// Main entrypoint
function main() {
  initTrees(packed_data);
  initMemoryGraph(memory_records);
  initThreadsDropdown(data, merge_threads);

  // Create the flamegraph renderer
  drawChart(data);

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

  let statsStartTime = document.getElementById("stats-start-time");
  let statsEndTime = document.getElementById("stats-end-time");
  statsStartTime.textContent = new Date(statsStartTime.innerText);
  statsEndTime.textContent = new Date(statsEndTime.innerText);
  // Enable tooltips
  $('[data-toggle-second="tooltip"]').tooltip();
  $('[data-toggle="tooltip"]').tooltip();
}

document.addEventListener("DOMContentLoaded", main);
