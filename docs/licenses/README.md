# Chart dependencies

The dashboard self-hosts Vega 6.4.0 and vega-interpreter 2.3.2 under the BSD 3-Clause license. Their licenses, and the bundled vega-util license, are included here.

`vega.min.js` comes from the Vega 6.4.0 npm distribution. The interpreter browser bundle combines vega-interpreter 2.3.2 and vega-util 2.1.3 using esbuild 0.25.0. Its entry is:

```js
import {expressionInterpreter} from 'vega-interpreter';
globalThis.vega.expressionInterpreter = expressionInterpreter;
```

Build it as a minified browser IIFE. The dashboard parses specs with `{ast: true}` and passes `vega.expressionInterpreter` to each view. It does not require `unsafe-eval`, a public CDN, or a Node build in Docker.
