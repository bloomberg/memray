const path = require("path");
const TerserPlugin = require("terser-webpack-plugin");
const CopyWebpackPlugin = require("copy-webpack-plugin");

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
  plugins: [
    new CopyWebpackPlugin({
      patterns: [
        {
          from: "node_modules/bootstrap/dist/css/bootstrap.min.css",
          to: "vendor/bootstrap.min.css",
        },
        {
          from: "node_modules/jquery/dist/jquery.min.js",
          to: "vendor/jquery.min.js",
        },
        {
          from: "node_modules/popper.js/dist/umd/popper.min.js",
          to: "vendor/popper.min.js",
        },
        {
          from: "node_modules/bootstrap/dist/js/bootstrap.min.js",
          to: "vendor/bootstrap.min.js",
        },
        {
          from: "node_modules/lodash/lodash.min.js",
          to: "vendor/lodash.min.js",
        },
        {
          from: "node_modules/plotly.js-dist-min/plotly.min.js",
          to: "vendor/plotly.min.js",
        },
        {
          from: "node_modules/d3/dist/d3.min.js",
          to: "vendor/d3.v4.min.js",
        },
        {
          from: "node_modules/d3-scale-chromatic/dist/d3-scale-chromatic.min.js",
          to: "vendor/d3-scale-chromatic.v1.min.js",
        },
        {
          from: "node_modules/d3-tip/dist/index.js",
          to: "vendor/d3-tip.min.js",
        },
        {
          from: "node_modules/d3-flame-graph/dist/d3-flamegraph.min.js",
          to: "vendor/d3-flamegraph.min.js",
        },
        {
          from: "node_modules/datatables.net/js/jquery.dataTables.min.js",
          to: "vendor/jquery.dataTables.min.js",
        },
        {
          from: "node_modules/datatables.net-bs4/js/dataTables.bootstrap4.min.js",
          to: "vendor/dataTables.bootstrap4.min.js",
        },
      ],
    }),
  ],
};
