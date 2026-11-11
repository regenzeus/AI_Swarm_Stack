// APP-70 (tests/test_app_words.py): every string literal and template text of the app's scripts, as JSON lines
// {file, line, text}. ESLint's own parser (espree, in /opt/eslint of the builder and CI images) reads the code, so a
// regular expression, a comment or the code inside ${} is never taken for text. Usage: node app_strings.cjs dir f1 f2 ...
const fs = require("fs"), path = require("path");
const espree = require(path.join(process.env.ESLINT_HOME || "/opt/eslint", "node_modules/espree"));
const [dir, ...files] = process.argv.slice(2);
for (const f of files) {
  const tokens = espree.tokenize(fs.readFileSync(path.join(dir, f), "utf8"), { ecmaVersion: "latest", loc: true });
  for (const t of tokens) {
    if (t.type === "String") process.stdout.write(JSON.stringify({ file: f, line: t.loc.start.line, text: t.value.slice(1, -1) }) + "\n");
    else if (t.type === "Template") process.stdout.write(JSON.stringify({ file: f, line: t.loc.start.line, text: t.value.replace(/^[`}]/, "").replace(/(`|\$\{)$/, "") }) + "\n");
  }
}
