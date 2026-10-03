// Executes the real `MarketingContent` wrapper from PlatformAdmin.jsx.
//
// The point is to catch a name that is not defined where the function is
// evaluated. That is a runtime ReferenceError, not a syntax error, so neither
// the Vite build nor `npm run lint` reports it: the module loads, the
// component renders, and the tab is simply blank. It happened once here -
// the wrapper called `notify`, which is declared in PlatformAdmin's scope, not
// the module's - and the error boundary reported it as a failed control
// centre with a reassuring "your data is safe" banner.
//
// So: lift the function out of the file, compile the JSX, call it with a
// plausible props object, and record what it hands to the editor. A missing
// prop or an undefined identifier shows up as a throw or as a forwarded prop
// that is `undefined`.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

// esbuild resolves relative to *this file*, and this harness is written to the
// system temp directory. Resolving it through the frontend's own package root
// keeps the harness runnable from anywhere and keeps node_modules out of the
// backend.
const require = createRequire(resolve(process.argv[3], 'index.js'));
const { transformSync } = require('esbuild');

const source = readFileSync(process.argv[2], 'utf8');

// Lift `function MarketingContent(...) { ... }` verbatim. Brace counting starts
// at the body, not at the parameter list, because the destructured params are
// themselves brace-wrapped.
const declaration = source.indexOf('function MarketingContent(');
if (declaration < 0) {
  console.error('MarketingContent is not in PlatformAdmin.jsx');
  process.exit(2);
}
// Skip past the parameter list to find the function body. The parameter list is
// `({ a, b })`, so the first `)` after the signature's `(` is the end of it -
// destructuring cannot nest parens in a parameter list.
const params = source.indexOf('(', declaration);
const body = source.indexOf('{', source.indexOf(')', params));
let depth = 0;
let end = -1;
for (let i = body; i < source.length; i += 1) {
  if (source[i] === '{') depth += 1;
  else if (source[i] === '}') {
    depth -= 1;
    if (depth === 0) { end = i + 1; break; }
  }
}
if (end < 0) {
  console.error('could not find the end of MarketingContent');
  process.exit(2);
}
const lifted = source.slice(declaration, end);

const compiled = transformSync(lifted, {
  loader: 'jsx',
  jsxFactory: 'h',
  jsxFragment: 'Fragment',
}).code;

// `MarketingEditor` stands in for the real component. The wrapper's only job is
// to forward props, so recording them is the whole contract.
const received = [];
function MarketingEditorStub(props) {
  received.push(props);
  return { type: 'MarketingEditorStub', props };
}

const sandbox = {
  h: (type, props) => ({ type, props }),
  Fragment: 'Fragment',
  MarketingEditor: MarketingEditorStub,
};

let outcome;
try {
  // eslint-disable-next-line no-new-func
  const factory = new Function(
    ...Object.keys(sandbox),
    `${compiled}\nreturn MarketingContent;`,
  );
  const MarketingContent = factory(...Object.values(sandbox));

  const props = {
    payload: { pages: [{ slug: 'home', name: 'Homepage', content: {} }], schema: {} },
    onSave: () => {},
    onCreate: () => {},
    onDelete: () => {},
    onNotice: () => {},
  };
  const element = MarketingContent(props);

  // Actually render one level, so the stub is invoked. Stopping at the element
  // object would only prove the wrapper returned *something*.
  let renderedType = null;
  if (element && typeof element.type === 'function') {
    element.type(element.props);
    renderedType = element.type.name || 'anonymous';
  }

  outcome = {
    threw: null,
    forwarded: received.length === 1 ? Object.keys(received[0]).sort() : null,
    // The props the caller supplies, by name, so the test can require that
    // each one arrives rather than being silently dropped.
    supplied: Object.keys(props).sort(),
    // Any prop that reached the editor as `undefined` - the failure mode where
    // the wrapper looks right and the editor silently does nothing.
    undefinedForwarded: received.length === 1
      ? Object.entries(received[0]).filter(([, v]) => v === undefined).map(([k]) => k)
      : null,
    renderedType,
  };
} catch (error) {
  outcome = {
    threw: `${error.name}: ${error.message}`,
    forwarded: null,
    supplied: null,
    undefinedForwarded: null,
    renderedType: null,
  };
}

process.stdout.write(JSON.stringify(outcome));
