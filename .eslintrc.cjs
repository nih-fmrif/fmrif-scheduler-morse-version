module.exports = {
  root: true,
  env: {
    browser: true,
    es2021: true,
  },
  parserOptions: {
    ecmaVersion: 2021,
    sourceType: "module",
  },
  extends: ["eslint:recommended"],
  ignorePatterns: [
    "node_modules/",
    "scheduler/static/a11y-dialog/*",
    "scheduler/static/scroll-lock/*",
    "scheduler/templates/**/*",
  ],
};
