const path = require("path");
const TerserPlugin = require("terser-webpack-plugin");

module.exports = {
  mode: "production",
  entry: {
    flamegraph_common: "./src/memray/reporters/assets/flamegraph_common.js",
    flamegraph: "./src/memray/reporters/assets/flamegraph.js",
    temporal_flamegraph: "./src/memray/reporters/assets/temporal_flamegraph.js",
    table: "./src/memray/reporters/assets/table.js",
  },
  output: {
    path: path.resolve("src/memray/reporters/templates/assets"),
    filename: "[name].js",
  },
  externals: {
    _: "lodash",
  },
  optimization: {
    minimize: true,
    minimizer: [
      new TerserPlugin({
        extractComments: false,
      }),
    ],
  },
};
