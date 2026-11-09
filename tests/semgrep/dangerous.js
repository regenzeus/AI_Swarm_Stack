// Semgrep rule fixture (ops/semgrep_selftest.py)
// ruleid: js-eval
eval(userCode);
// ruleid: js-eval
const f = new Function("return " + userCode);
// ok: js-eval
JSON.parse(userCode);
