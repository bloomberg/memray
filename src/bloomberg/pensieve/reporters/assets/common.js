import _ from "lodash";

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
  let displayString = `${data.location}<br>${totalSize} total<br>${data.allocations_label}`;
  if (merge_threads === false) {
    displayString = displayString.concat(`<br>Thread ID: ${data.thread_id}`);
  }
  return displayString;
}

/**
 * Recursively filter out the specified thread IDs from the node's `children` attribute.
 * @param data Root node.
 * @param threadId Thread ID to filter.
 * @returns {NonNullable<any>} A copy of the input object with the filtering applied.
 */
export function filterChildThreads(data, threadId) {
  function _filter(obj) {
    if (obj.children && obj.children.length > 0) {
      obj.children = _.filter(obj.children, _filter);
    }
    return obj.thread_id === threadId;
  }

  // Avoid mutating the input
  let children = _.cloneDeep(data.children);
  const filtered_children = _.filter(children, _filter);
  return _.defaults({ children: filtered_children }, data);
}
