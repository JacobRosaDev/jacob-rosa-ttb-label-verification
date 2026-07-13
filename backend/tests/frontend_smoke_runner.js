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
  net_contents: "750 mL",
  government_warning: "GOVERNMENT WARNING: sample text",
};

class FakeElement {
  constructor({ id = "", name = "", value = "" } = {}) {
    this.id = id;
    this.name = name;
    this.value = value;
    this.files = [];
    this.elements = [];
    this.listeners = {};
    this.style = {};
    this.disabled = false;
    this.textContent = "";
    this._innerHTML = "";
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
  }
}

class FakeFormData {
  constructor(form) {
    this.entries = new Map();
    for (const element of form.elements) {
      if (!element.name) {
        continue;
      }
      if (element.files && element.files.length > 0) {
        this.entries.set(element.name, element.files[0]);
      } else {
        this.entries.set(element.name, element.value);
      }
    }
  }

  set(name, value) {
    this.entries.set(name, value);
  }

  get(name) {
    return this.entries.get(name);
  }

  has(name) {
    return this.entries.has(name);
  }
}

function extractInlineScript(html) {
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert(match, "Expected index.html to contain an inline script.");
  return match[1];
}

async function runSmoke() {
  const html = fs.readFileSync(FRONTEND_PATH, "utf8");
  const script = extractInlineScript(html);

  const fakeImage = {
    name: "label.png",
    size: 1024,
    type: "image/png",
  };

  const elements = {
    "verification-form": new FakeElement({ id: "verification-form" }),
    "image-upload": new FakeElement({ id: "image-upload", name: "image" }),
    "image-picker": new FakeElement({ id: "image-picker" }),
    "image-preview": new FakeElement({ id: "image-preview" }),
    error: new FakeElement({ id: "error" }),
    results: new FakeElement({ id: "results" }),
    status: new FakeElement({ id: "status" }),
    "clear-image": new FakeElement({ id: "clear-image" }),
  };

  const submitButton = new FakeElement();
  const fieldElements = Object.entries(FIELD_VALUES).map(
    ([name, value]) => new FakeElement({ name, value })
  );
  const imageUpload = elements["image-upload"];
  const form = elements["verification-form"];
  form.elements = [imageUpload, ...fieldElements, submitButton];

  const returnedFields = Object.keys(FIELD_VALUES).map((field) => ({
    field,
    match_type: field === "country_of_origin" ? "synonym" : "exact",
    expected: FIELD_VALUES[field],
    found: FIELD_VALUES[field],
    status: "PASS",
    reason: "match",
  }));

  let fetchCalled = false;
  const context = {
    console,
    FormData: FakeFormData,
    URL: {
      createObjectURL(file) {
        assert.strictEqual(file, fakeImage);
        return "blob:label-preview";
      },
    },
    document: {
      getElementById(id) {
        assert(elements[id], `Unexpected getElementById(${id})`);
        return elements[id];
      },
      querySelector(selector) {
        assert.strictEqual(selector, "button.submit");
        return submitButton;
      },
    },
    fetch: async (url, options) => {
      fetchCalled = true;
      assert.strictEqual(url, "/verify");
      assert.strictEqual(options.method, "POST");
      assert(options.body instanceof FakeFormData, "fetch body must be FormData");

      assert.strictEqual(options.body.get("image"), fakeImage);
      for (const [field, value] of Object.entries(FIELD_VALUES)) {
        assert(options.body.has(field), `Missing FormData field: ${field}`);
        assert.strictEqual(options.body.get(field), value);
      }

      return {
        ok: true,
        json: async () => ({
          overall_verdict: "APPROVED",
          field_results: returnedFields,
        }),
      };
    },
  };

  vm.runInNewContext(script, context, { filename: FRONTEND_PATH });

  imageUpload.files = [fakeImage];
  assert.strictEqual(typeof imageUpload.listeners.change, "function");
  imageUpload.listeners.change();

  assert.strictEqual(typeof form.listeners.submit, "function");
  await form.listeners.submit({ preventDefault() {} });

  assert(fetchCalled, "Expected submit handler to call fetch.");
  assert.strictEqual(elements.error.style.display, "none");
  assert.strictEqual(elements.results.style.display, "block");

  const rowCount = (elements.results.innerHTML.match(/class="field-result /g) || []).length;
  assert.strictEqual(rowCount, 7);
  for (const field of Object.keys(FIELD_VALUES)) {
    assert(
      elements.results.innerHTML.includes(field.replace(/_/g, " ")),
      `Rendered output did not include field row for ${field}`
    );
  }
}

runSmoke().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
