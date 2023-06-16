import _ from "lodash";

export function initMemoryGraph(memory_records) {
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

  var data = [resident_size_plot, heap_size_plot];

  var layout = {
    xaxis: {
      title: {
        text: "Time",
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

  var layout_small = {
    height: 40,
    margin: {
      l: 0,
      r: 0,
      b: 0,
      t: 0,
      pad: 4,
    },
    plot_bgcolor: "#343a40", // this matches the color of bg-dark in our navbar
    yaxis: {
      tickformat: ".4~s",
      exponentformat: "B",
      ticksuffix: "B",
    },
    showlegend: false,
  };
  var config = {
    responsive: true,
  };
  var config_small = {
    responsive: true,
    displayModeBar: false,
  };

  Plotly.newPlot("memoryGraph", data, layout, config);
  Plotly.newPlot("smallMemoryGraph", data, layout_small, config_small);

  document.getElementById("smallMemoryGraph").onclick(() => {
    resizeMemoryGraph();
  });
}

export function resizeMemoryGraph() {
  setTimeout(() => {
    Plotly.Plots.resize("memoryGraph");
    Plotly.Plots.resize("smallMemoryGraph");
  }, 100);
}

export function humanFileSize(bytes, dp = 1) {
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

export function debounced(fn) {
  var requestID;

  // Return a debouncing wrapper function
  return function () {
    if (requestID) {
      window.cancelAnimationFrame(requestID);
    }

    const context = this;
    const args = arguments;
    requestID = window.requestAnimationFrame(function () {
      fn.apply(context, args);
    });
  };
}

export function makeTooltipString(data, totalSize, merge_threads) {
  let location = "unknown location";
  if (data.location !== undefined) {
    location = `File ${data.location[1]}, line ${data.location[2]} in ${data.location[0]}`;
  }

  const plural = data.n_allocations > 1 ? "s" : "";
  const allocations_label = `${data.n_allocations} allocation${plural}`;
  let displayString = `${location}<br>${totalSize} total<br>${allocations_label}`;
  if (merge_threads === false) {
    displayString = displayString.concat(`<br>Thread ID: ${data.thread_id}`);
  }
  return displayString;
}

/**
 * Recursively apply a filter to every frame in .children.
 *
 * @param root Root node.
 * @param compFunction Called with the node being traversed. Expected to return true or false.
 * @returns {NonNullable<any>} A copy of the input object with the filtering applied.
 */
export function filterFrames(root, compFunction) {
  function _filter(obj) {
    if (obj.children && obj.children.length > 0) {
      obj.children = _.filter(obj.children, _filter);
    }
    return compFunction(obj);
  }

  // Avoid mutating the input
  let children = _.cloneDeep(root.children);
  const filtered_children = _.filter(children, _filter);
  return _.defaults({ children: filtered_children }, root);
}

/**
 * Recursively filter out the specified thread IDs from the node's `children` attribute.
 *
 * @param root Root node.
 * @param threadId Thread ID to filter.
 * @returns {NonNullable<any>} A copy of the input object with the filtering applied.
 */
export function filterChildThreads(root, threadId) {
  return filterFrames(root, (obj) => obj.thread_id === threadId);
}

/**
 * Recursively filter out nodes where the given filter function return `false`.
 *
 * @param root Root node.
 * @param func The filter function.
 * @returns {NonNullable<any>} A copy of the input object with the filtering applied.
 */
function filterFramesByFunc(root, func) {
  function filterChildren(node) {
    let result = [];
    if (!func(node)) {
      for (const child of node.children) {
        result.push(...filterChildren(child));
      }
    } else {
      result = [];
      for (const child of node.children) {
        result.push(...filterChildren(child));
      }
      let new_node = _.clone(node);
      new_node.children = result;
      result = [new_node];
    }
    return result;
  }

  let children = [];
  for (let child of root.children) {
    children.push(...filterChildren(child));
  }
  return _.defaults({ children: children }, root);
}

export function filterUninteresting(root) {
  return filterFramesByFunc(root, (node) => {
    return node.interesting;
  });
}

export function filterImportSystem(root) {
  return filterFramesByFunc(root, (node) => {
    return !node.import_system;
  });
}

/**
 * Walk the children of the specified node and sum up the total allocations and memory use.
 *
 * @param data Root node.
 * @returns {{n_allocations: number, value: number}}
 */

export function sumAllocations(data) {
  let initial = {
    n_allocations: 0,
    value: 0,
  };

  let sum = (result, node) => {
    result.n_allocations += node.n_allocations;
    result.value += node.value;
    return result;
  };

  return _.reduce(data, sum, initial);
}
