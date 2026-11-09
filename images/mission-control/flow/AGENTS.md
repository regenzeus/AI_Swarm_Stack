# images/mission-control/flow: the template editor (GEN-34)

Workflow Builder's editor SDK (synergycodes, Apache 2.0) with the stack's blocks, built by Vite into one ES module
(the app's /static/vendor/flow/flow.js), by a Node stage of the app's image from the locked package file.
- `src/blocks.js`: one palette item per block of the graph model, each with its JSON Schema form.
- `src/main.jsx`: mount(), and the lossless conversion between a template's YAML fields and the drawing; the check
  before a save (missing()); the zoom note is in app.css (.tb-flow).
- `package.json` / `package-lock.json`: exact versions, every package hash-locked. Update them together, then build in
  the builder (npm ci; npx vite build) and run tests/test_engine_templates.py.
