// Minimal test suite so fix proposals have a baseline to run (node --test, no dependencies needed).
const test = require("node:test");
const assert = require("node:assert");
const { hashPassword } = require("../src/server.js");

test("hashPassword is deterministic", () => {
  assert.strictEqual(hashPassword("a"), hashPassword("a"));
});

test("lodash is installed and usable", () => {
  const _ = require("lodash");
  assert.deepStrictEqual(_.uniq([1, 1, 2]), [1, 2]);
});
