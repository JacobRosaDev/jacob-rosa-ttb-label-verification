const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const FRONTEND_PATH = path.resolve(__dirname, "..", "frontend", "index.html");
const FIELD_VALUES = {
  brand_name: "Ketel One",
  class_type: "Vodka",
  producer: "Nolet Distillery",
  country_of_origin: "Netherlands",
  abv: "40",
  net_contents_amount: "750",
  net_contents_unit: "mL",
  government_warning: "GOVERNMENT WARNING: sample text",
};

const METADATA_VALUES = {
  brand_name: FIELD_VALUES.brand_name,
  class_type: FIELD_VALUES.class_type,
  producer: FIELD_VALUES.producer,
  country_of_origin: FIELD_VALUES.country_of_origin,
  abv: FIELD_VALUES.abv,
  net_contents: "750 mL",
  government_warning: FIELD_VALUES.government_warning,
};

class FakeClassList {
  constructor(element) {
    this.element = element;
  }

  add(name) {
    const names = new Set(this.element.className.split(/\s+/).filter(Boolean));
    names.add(name);
    this.element.className = Array.from(names).join(" ");
  }

  remove(name) {
    const names = this.element.className.split(/\s+/).filter((item) => item && item !== name);
    this.element.className = names.join(" ");
  }
}

class FakeElement {
  constructor({ id = "", name = "", value = "", dataset = {}, type = "" } = {}) {
    this.id = id;
    this.name = name;
    this.value = value;
    this.type = type;
    this.dataset = { ...dataset };
    this.files = [];
    this.listeners = {};
    this.style = {};
    this.children = [];
    this.parentElement = null;
    this.disabled = false;
    this.textContent = "";
    this.className = "";
    this.attributes = {};
    this.classList = new FakeClassList(this);
    this._innerHTML = "";
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }

  appendChild(node) {
    if (node instanceof FakeFragment) {
      for (const child of node.children) {
        child.parentElement = this;
        this.children.push(child);
      }
      node.children = [];
      return node;
    }

    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  click() {
    if (this.listeners.click) {
      this.listeners.click({ preventDefault() {} });
    }
  }

  remove() {
    if (!this.parentElement) {
      return;
    }
    this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    this.parentElement = null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "for") {
      this.htmlFor = String(value);
    }
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    if (this._innerHTML.includes("data-remove-image")) {
      this.appendChild(new FakeElement({ dataset: { removeImage: "" } }));
    }
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const matches = [];
    const walk = (element) => {
      if (matchesSelector(element, selector)) {
        matches.push(element);
      }
      for (const child of element.children) {
        walk(child);
      }
    };
    walk(this);
    return matches;
  }
}

class FakeFragment {
  constructor(children) {
    this.children = children;
    for (const child of children) {
      child.parentElement = this;
    }
  }

  cloneNode() {
    return createCardFragment();
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    return this.children.flatMap((child) => child.querySelectorAll(selector));
  }
}

class FakeTemplate extends FakeElement {
  constructor() {
    super({ id: "label-card-template" });
    this.content = createCardFragment();
  }
}

class FakeFormData {
  constructor() {
    this.entries = [];
  }

  append(name, value) {
    this.entries.push([name, value]);
  }

  get(name) {
    const entry = this.entries.find(([key]) => key === name);
    return entry ? entry[1] : undefined;
  }

  getAll(name) {
    return this.entries.filter(([key]) => key === name).map(([, value]) => value);
  }

  has(name) {
    return this.entries.some(([key]) => key === name);
  }
}

function matchesSelector(element, selector) {
  if (selector === "[data-card]") return Object.hasOwn(element.dataset, "card");
  if (selector === "[data-field]") return Object.hasOwn(element.dataset, "field");
  if (selector === "[data-card-title]") return Object.hasOwn(element.dataset, "cardTitle");
  if (selector === "[data-card-mode]") return Object.hasOwn(element.dataset, "cardMode");
  if (selector === "[data-remove-card]") return Object.hasOwn(element.dataset, "removeCard");
  if (selector === "[data-image-picker]") return Object.hasOwn(element.dataset, "imagePicker");
  if (selector === "[data-image-preview]") return Object.hasOwn(element.dataset, "imagePreview");
  if (selector === "[data-remove-image]") return Object.hasOwn(element.dataset, "removeImage");

  let match = selector.match(/^\[data-field="([^"]+)"\]$/);
  if (match) return element.dataset.field === match[1];

  match = selector.match(/^\[data-label-for="([^"]+)"\]$/);
  if (match) return element.dataset.labelFor === match[1];

  return false;
}

function createField(name, value = "") {
  const label = new FakeElement({ dataset: { labelFor: name } });
  const input = new FakeElement({ name, value, dataset: { field: name } });
  return [label, input];
}

function createCardFragment() {
  const card = new FakeElement({ dataset: { card: "" } });
  const title = new FakeElement({ dataset: { cardTitle: "" } });
  const mode = new FakeElement({ dataset: { cardMode: "" } });
  const remove = new FakeElement({ dataset: { removeCard: "" } });
  const imageLabel = new FakeElement({ dataset: { labelFor: "image" } });
  const picker = new FakeElement({ dataset: { imagePicker: "" } });
  const imageInput = new FakeElement({ name: "image", dataset: { field: "image" }, type: "file" });
  const preview = new FakeElement({ dataset: { imagePreview: "" } });

  card.appendChild(title);
  card.appendChild(mode);
  card.appendChild(remove);
  card.appendChild(imageLabel);
  card.appendChild(picker);
  card.appendChild(imageInput);
  card.appendChild(preview);

  for (const name of [
    "brand_name",
    "class_type",
    "producer",
    "country_of_origin",
    "abv",
    "net_contents_amount",
    "net_contents_unit",
    "government_warning",
  ]) {
    const [label, input] = createField(name, FIELD_VALUES[name] || "");
    card.appendChild(label);
    card.appendChild(input);
  }

  return new FakeFragment([card]);
}

function extractInlineScript(html) {
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert(match, "Expected index.html to contain an inline script.");
  return match[1];
}

function returnedFields() {
  return Object.keys(METADATA_VALUES).map((field) => ({
    field,
    match_type: field === "country_of_origin" ? "synonym" : "exact",
    expected: METADATA_VALUES[field],
    found: METADATA_VALUES[field],
    status: "PASS",
    reason: "match",
  }));
}

function createRuntime(fetchHandler) {
  const html = fs.readFileSync(FRONTEND_PATH, "utf8");
  const script = extractInlineScript(html);
  const elements = {
    "verification-form": new FakeElement({ id: "verification-form" }),
    cards: new FakeElement({ id: "cards" }),
    "label-card-template": new FakeTemplate(),
    "add-card": new FakeElement({ id: "add-card" }),
    "submit-button": new FakeElement({ id: "submit-button" }),
    error: new FakeElement({ id: "error" }),
    results: new FakeElement({ id: "results" }),
    status: new FakeElement({ id: "status" }),
    "cold-start-note": new FakeElement({ id: "cold-start-note" }),
  };

  elements["verification-form"].reportValidity = () => true;
  Object.defineProperty(elements["verification-form"], "elements", {
    get() {
      return [
        ...elements.cards.querySelectorAll("[data-field]"),
        elements["add-card"],
        elements["submit-button"],
      ];
    },
  });

  const timers = [];
  const context = {
    console,
    FormData: FakeFormData,
    URL: {
      createObjectURL(file) {
        return `blob:${file.name}`;
      },
    },
    document: {
      getElementById(id) {
        assert(elements[id], `Unexpected getElementById(${id})`);
        return elements[id];
      },
    },
    fetch: fetchHandler,
    setTimeout(fn, delay) {
      timers.push({ fn, delay });
      return timers.length;
    },
    clearTimeout(id) {
      timers[id - 1].cleared = true;
    },
  };

  vm.runInNewContext(script, context, { filename: FRONTEND_PATH });
  return { elements, timers };
}

function fillCard(card, image) {
  card.querySelector('[data-field="image"]').files = [image];
  for (const [name, value] of Object.entries(FIELD_VALUES)) {
    card.querySelector(`[data-field="${name}"]`).value = value;
  }
}

async function submit(form) {
  assert.strictEqual(typeof form.listeners.submit, "function");
  await form.listeners.submit({ preventDefault() {} });
}

function assertStaticHtml(html) {
  const staleBatchPage = ["batch", "html"].join(".");
  assert(html.includes('accept="image/*"'), "File input should accept any image type.");
  assert(!html.includes('type="file" accept="image/*" required'), "Hidden image input should not be browser-required.");
  assert(html.includes("Choose an image file. Under 8 MB."), "Picker help text should use neutral image wording.");
  assert(html.includes('type="number" min="0" max="100" step="0.1"'), "ABV must be numeric and constrained.");
  assert(html.includes('name="net_contents_amount" type="number"'), "Net contents amount must be numeric.");
  assert(html.includes('name="net_contents_unit"'), "Net contents must include a unit selector.");
  assert(html.includes("COLD_START_DELAY_MS = 3000"), "Cold-start delay should be approximately 3 seconds.");
  assert(!html.includes(staleBatchPage), "Unified page should not link to the stale batch page.");
}

async function testMissingImageShowsFriendlyError() {
  let fetchCalled = false;
  const { elements } = createRuntime(async () => {
    fetchCalled = true;
    throw new Error("fetch should not be called without an image");
  });

  const cards = elements.cards.querySelectorAll("[data-card]");
  assert.strictEqual(cards.length, 1, "Expected the page to start with one card.");
  for (const [name, value] of Object.entries(FIELD_VALUES)) {
    cards[0].querySelector(`[data-field="${name}"]`).value = value;
  }

  await submit(elements["verification-form"]);

  assert.strictEqual(fetchCalled, false, "Missing image should not call fetch.");
  assert.strictEqual(elements.error.style.display, "block");
  assert.strictEqual(elements.error.textContent, "Please select an image for Label 1.");
}

async function testSingleSubmit() {
  const fakeImage = { name: "label.png", size: 1024, type: "image/png" };
  let fetchCalled = false;
  const { elements, timers } = createRuntime(async (url, options) => {
    fetchCalled = true;
    assert.strictEqual(url, "/verify");
    assert.strictEqual(options.method, "POST");
    assert(options.body instanceof FakeFormData, "fetch body must be FormData");
    assert.strictEqual(options.body.get("image"), fakeImage);

    for (const [field, value] of Object.entries(METADATA_VALUES)) {
      assert(options.body.has(field), `Missing FormData field: ${field}`);
      assert.strictEqual(options.body.get(field), value);
    }

    return {
      ok: true,
      json: async () => ({
        overall_verdict: "APPROVED",
        field_results: returnedFields(),
      }),
    };
  });

  const cards = elements.cards.querySelectorAll("[data-card]");
  assert.strictEqual(cards.length, 1, "Expected the page to start with one card.");
  fillCard(cards[0], fakeImage);
  await submit(elements["verification-form"]);

  assert(fetchCalled, "Expected submit handler to call fetch.");
  assert.strictEqual(timers[0].delay, 3000);
  assert.strictEqual(elements.error.style.display, "none");
  assert.strictEqual(elements.results.style.display, "block");

  const rowCount = (elements.results.innerHTML.match(/class="field-result /g) || []).length;
  assert.strictEqual(rowCount, 7);
  for (const field of Object.keys(METADATA_VALUES)) {
    assert(
      elements.results.innerHTML.includes(field.replace(/_/g, " ")),
      `Rendered output did not include field row for ${field}`
    );
  }
}

async function testBatchSubmitAndRemove() {
  const images = [
    { name: "label-1.png", size: 1024, type: "image/png" },
    { name: "label-2.png", size: 2048, type: "image/png" },
  ];
  let fetchCalled = false;
  const { elements } = createRuntime(async (url, options) => {
    fetchCalled = true;
    assert.strictEqual(url, "/verify/batch");
    assert.strictEqual(options.method, "POST");
    assert(options.body instanceof FakeFormData, "fetch body must be FormData");
    assert.deepStrictEqual(options.body.getAll("images"), images);

    const metadata = JSON.parse(options.body.get("metadata"));
    assert.strictEqual(metadata.length, 2);
    assert.deepStrictEqual(metadata[0], METADATA_VALUES);
    assert.deepStrictEqual(metadata[1], METADATA_VALUES);

    return {
      ok: true,
      json: async () => ({
        items: [
          { overall_verdict: "APPROVED", field_results: returnedFields() },
          { overall_verdict: "NEEDS_REVIEW", field_results: returnedFields() },
        ],
        summary: { total: 2, passed: 1, needs_review: 1 },
      }),
    };
  });

  elements["add-card"].listeners.click();
  let cards = elements.cards.querySelectorAll("[data-card]");
  assert.strictEqual(cards.length, 2, "Add another label should create a second card.");
  assert.strictEqual(cards[0].querySelector("[data-remove-card]").disabled, false);

  cards[1].querySelector("[data-remove-card]").listeners.click();
  cards = elements.cards.querySelectorAll("[data-card]");
  assert.strictEqual(cards.length, 1, "Removing an additional card should leave one card.");
  assert.strictEqual(cards[0].querySelector("[data-remove-card]").disabled, true);

  elements["add-card"].listeners.click();
  cards = elements.cards.querySelectorAll("[data-card]");
  fillCard(cards[0], images[0]);
  fillCard(cards[1], images[1]);
  await submit(elements["verification-form"]);

  assert(fetchCalled, "Expected batch submit handler to call fetch.");
  assert.strictEqual(elements.results.style.display, "block");
  assert(elements.results.innerHTML.includes("Total: 2 - Passed: 1 - Needs review: 1"));
  const rowCount = (elements.results.innerHTML.match(/class="field-result /g) || []).length;
  assert.strictEqual(rowCount, 14);
}

async function runSmoke() {
  const html = fs.readFileSync(FRONTEND_PATH, "utf8");
  assertStaticHtml(html);
  await testMissingImageShowsFriendlyError();
  await testSingleSubmit();
  await testBatchSubmitAndRemove();
}

runSmoke().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
