// Built with Spec4 AI - https://spec4.ai
/**
 * Local ambient declarations for plotly.js, which ships no TypeScript types.
 *
 * `react-plotly.js` v4 *does* ship first-party types, and they deliberately do
 * not depend on `@types/plotly.js` — its `data`/`layout`/`config` props are
 * typed `unknown`. So importing the `react-plotly.js` component alone needs
 * nothing from this file.
 *
 * What does need it is the **partial-bundle** import. plotly.js's full bundle
 * is ~4.7 MB minified; `plotly-basic` is ~1.1 MB and carries the scatter
 * traces this app actually plots. Selecting it means importing a dist file
 * directly and handing it to `react-plotly.js/factory`, and those dist paths
 * are untyped — `tsc` fails with TS7016 without the declarations below.
 *
 * Typed as `unknown` rather than `any`: nothing here inspects the Plotly
 * namespace, it is only passed through to the factory, and `any` would
 * silently disable checking at every future call site.
 */

declare module 'plotly.js' {
  const Plotly: unknown
  export default Plotly
}

declare module 'plotly.js/dist/plotly-basic.min.js' {
  const Plotly: unknown
  export default Plotly
}

declare module 'plotly.js/dist/plotly-cartesian.min.js' {
  const Plotly: unknown
  export default Plotly
}
