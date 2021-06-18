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
