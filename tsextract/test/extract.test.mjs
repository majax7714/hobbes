// Tests for the facts extractor (ADR-021). Zero dev dependencies: run
// with `npm test` (node --test). Fixtures are built in temp dirs so the
// suite exercises real discovery and real checker resolution.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  discoverFiles,
  externalName,
  extractRepo,
  isTestFile,
  resolveRelative,
} from "../extract.mjs";

function makeRepo(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tsextract-"));
  for (const [rel, content] of Object.entries(files)) {
    const full = path.join(root, rel);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, content);
  }
  return root;
}

function byPath(facts, rel) {
  const found = facts.files.find((f) => f.path === rel);
  assert.ok(found, `${rel} missing from facts (${facts.files.map((f) => f.path)})`);
  return found;
}

test("discoverFiles finds TS/JS extensions and prunes junk dirs", () => {
  const root = makeRepo({
    "src/a.ts": "",
    "src/b.jsx": "",
    "c.mjs": "",
    "node_modules/x/d.js": "",
    "dist/e.js": "",
    ".hidden/f.ts": "",
    "readme.md": "",
  });
  assert.deepEqual(discoverFiles(root), ["c.mjs", "src/a.ts", "src/b.jsx"]);
});

test("externalName: builtins dropped, packages kept, relatives null", () => {
  assert.equal(externalName("node:test"), null);
  assert.equal(externalName("fs/promises"), null);
  assert.equal(externalName("./local.js"), null);
  assert.equal(externalName("express"), "express");
  assert.equal(externalName("@nestjs/common"), "@nestjs/common");
  assert.equal(externalName("lodash/get"), "lodash");
});

test("resolveRelative tries extensions and index files", () => {
  const files = new Set(["src/a.js", "src/lib/index.ts", "src/plain.mjs"]);
  assert.equal(resolveRelative("src/main.js", "./a", files), "src/a.js");
  assert.equal(resolveRelative("src/main.js", "./a.js", files), "src/a.js");
  assert.equal(resolveRelative("src/main.js", "./lib", files), "src/lib/index.ts");
  assert.equal(resolveRelative("src/main.js", "./gone", files), null);
  assert.equal(resolveRelative("src/main.js", "express", files), null);
});

test("isTestFile conventions", () => {
  assert.ok(isTestFile("tests/flow.test.mjs"));
  assert.ok(isTestFile("src/x.spec.ts"));
  assert.ok(isTestFile("src/__tests__/y.js"));
  assert.ok(!isTestFile("src/latest.js"));
});

test("imports: named/default/namespace, re-exports, require, dynamic", () => {
  const root = makeRepo({
    "src/util.js": "export function helper() { return 1; }\nexport default helper;\n",
    "src/extra.js": "export const extra = 1;\n",
    "src/main.js": [
      'import def, { helper } from "./util.js";',
      'import * as util from "./util.js";',
      'import express from "express";',
      'import fs from "node:fs";',
      'export { extra } from "./extra.js";',
      'const lazy = () => import("./extra.js");',
      "def(); helper(); util.helper(); lazy();",
    ].join("\n"),
    "src/legacy.cjs": 'const util = require("./util.js");\nconst lodash = require("lodash");\n',
  });
  const facts = extractRepo(root);
  const main = byPath(facts, "src/main.js");
  const resolved = main.imports.filter((i) => i.resolved);
  assert.deepEqual(
    resolved.map((i) => [i.specifier, i.resolved]),
    [
      ["./util.js", "src/util.js"],
      ["./util.js", "src/util.js"],
      ["./extra.js", "src/extra.js"],
      ["./extra.js", "src/extra.js"],
    ]
  );
  assert.deepEqual(resolved[0].names, ["def", "helper"]);
  assert.deepEqual(
    main.imports.filter((i) => i.external).map((i) => i.external),
    ["express"]
  ); // node:fs dropped as a builtin
  const legacy = byPath(facts, "src/legacy.cjs");
  assert.deepEqual(
    legacy.imports.map((i) => [i.specifier, i.resolved ?? i.external]),
    [
      ["./util.js", "src/util.js"],
      ["lodash", "lodash"],
    ]
  );
});

test("symbols: functions, classes, methods, arrow consts", () => {
  const root = makeRepo({
    "src/shapes.ts": [
      "export function area(r: number) { return r * r; }",
      "export class Circle {",
      "  radius = 1;",
      "  grow(by: number) { return this.radius + by; }",
      "}",
      "export const shrink = (by: number) => by - 1;",
      "const NAME = 'x';", // plain const: not a symbol
    ].join("\n"),
  });
  const facts = extractRepo(root);
  const symbols = byPath(facts, "src/shapes.ts").symbols;
  assert.deepEqual(
    symbols.map((s) => [s.qualname, s.kind, s.line]),
    [
      ["area", "function", 1],
      ["Circle", "class", 2],
      ["Circle.grow", "method", 4],
      ["shrink", "function", 6],
    ]
  );
});

test("calls resolve locally, through imports, and to methods; externals omitted", () => {
  const root = makeRepo({
    "src/util.js": "export function helper() { return 1; }\n",
    "src/main.js": [
      'import { helper } from "./util.js";',
      'import express from "express";',
      "function local() { return helper(); }",
      "function run() { local(); express(); }",
      "run();",
    ].join("\n"),
  });
  const facts = extractRepo(root);
  const calls = byPath(facts, "src/main.js").calls;
  assert.deepEqual(
    calls.map((c) => [c.scope, c.callee_path, c.callee]),
    [
      ["local", "src/util.js", "helper"],
      ["run", "src/main.js", "local"],
      [null, "src/main.js", "run"],
    ]
  ); // express() resolves outside the repo: omitted
});

test("env reads: process.env and import.meta.env, both access styles", () => {
  const root = makeRepo({
    "src/config.js": [
      "const a = process.env.API_URL;",
      'const b = process.env["DB_HOST"];',
      "const c = import.meta.env.VITE_KEY;",
      "const d = other.env.NOPE;",
    ].join("\n"),
  });
  const reads = byPath(extractRepo(root), "src/config.js").env_reads;
  assert.deepEqual(
    reads.map((r) => [r.var, r.line]),
    [["API_URL", 1], ["DB_HOST", 2], ["VITE_KEY", 3]]
  );
});

test("express routes: verb + slash literal + express-ish receiver", () => {
  const root = makeRepo({
    "src/server.js": [
      'import express from "express";',
      "const app = express();",
      "function listItems(req, res) { res.send([]); }",
      'app.get("/items", listItems);',
      'app.post("/items", (req, res) => res.send({}));',
      "const map = new Map();",
      'map.get("/not-a-route");',
      'app.get("key", listItems);', // no leading slash: not a route
    ].join("\n"),
  });
  const routes = byPath(extractRepo(root), "src/server.js").routes;
  assert.deepEqual(
    routes.map((r) => [r.method, r.path, r.handler]),
    [
      ["GET", "/items", "listItems"],
      ["POST", "/items", "<inline>"],
    ]
  );
});

test("nest routes: controller prefix joins method paths", () => {
  const root = makeRepo({
    "src/items.controller.ts": [
      'import { Controller, Get, Post } from "@nestjs/common";',
      '@Controller("items")',
      "export class ItemsController {",
      '  @Get(":id")',
      "  findOne() { return {}; }",
      "  @Post()",
      "  create() { return {}; }",
      "}",
    ].join("\n"),
  });
  const routes = byPath(extractRepo(root), "src/items.controller.ts").routes;
  assert.deepEqual(
    routes.map((r) => [r.framework, r.method, r.path, r.handler]),
    [
      ["nest", "GET", "/items/:id", "ItemsController.findOne"],
      ["nest", "POST", "/items", "ItemsController.create"],
    ]
  );
});

test("tests: node:test with describe nesting", () => {
  const root = makeRepo({
    "src/flow.js": "export const ok = () => true;\n",
    "tests/flow.test.mjs": [
      'import test from "node:test";',
      'import { ok } from "../src/flow.js";',
      'test("stays ok", () => { ok(); });',
      'test.skip("skipped still inventoried", () => {});',
    ].join("\n"),
  });
  const file = byPath(extractRepo(root), "tests/flow.test.mjs");
  assert.equal(file.test_framework, "node:test");
  assert.deepEqual(
    file.tests.map((t) => [t.qualname, t.line]),
    [["stays ok", 3], ["skipped still inventoried", 4]]
  );
});

test("tests: vitest import and nested describes", () => {
  const root = makeRepo({
    "src/math.spec.ts": [
      'import { describe, it } from "vitest";',
      'describe("math", () => {',
      '  describe("add", () => {',
      '    it("adds", () => {});',
      "  });",
      '  it("subtracts", () => {});',
      "});",
    ].join("\n"),
  });
  const file = byPath(extractRepo(root), "src/math.spec.ts");
  assert.equal(file.test_framework, "vitest");
  assert.deepEqual(
    file.tests.map((t) => t.qualname),
    ["math > add > adds", "math > subtracts"]
  );
});

test("tests: bare globals in a test-named file are honest-unknown", () => {
  const root = makeRepo({
    "src/x.test.js": 'describe("x", () => { it("works", () => {}); });\n',
    "src/notatest.js": 'describe("x", () => { it("nope", () => {}); });\n',
  });
  const facts = extractRepo(root);
  assert.equal(byPath(facts, "src/x.test.js").test_framework, "unknown");
  assert.equal(byPath(facts, "src/x.test.js").tests.length, 1);
  assert.equal(byPath(facts, "src/notatest.js").test_framework, null);
});

test("output is deterministic across runs", () => {
  const files = {
    "src/util.js": "export function helper() { return 1; }\n",
    "src/main.js": 'import { helper } from "./util.js";\nhelper();\n',
  };
  const a = JSON.stringify(extractRepo(makeRepo(files)));
  const b = JSON.stringify(extractRepo(makeRepo(files)));
  assert.equal(a, b);
});
