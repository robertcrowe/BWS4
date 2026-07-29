// Built with Spec4 AI - https://spec4.ai
import createPlotlyComponent from 'react-plotly.js/factory'
// The *basic* bundle, not the full one. plotly.js ships ~4.7 MB minified;
// plotly-basic is ~1.1 MB and carries the scatter traces this plot needs.
// Measured on this project: the embeddings route chunk is 4,656 kB with the
// full bundle and 1,087 kB with this one, with no change to the entry chunk
// either way. Importing a dist path is why src/types/plotly-js.d.ts exists.
import Plotly from 'plotly.js/dist/plotly-basic.min.js'

import type { PlacementResult, PresetPoint } from '../../api/embeddings'
import { useIsDarkTheme } from '../../useIsDarkTheme'
import { buildCategoryTraces, buildCustomTrace } from './plotTraces'

const Plot = createPlotlyComponent(Plotly)

interface SemanticPlotProps {
  presets: PresetPoint[]
  /** The visitor's placed text, appended as its own trace. */
  customPlacement?: PlacementResult | null
}

/**
 * The 2D semantic plot: one marker per preset, coloured and legended by
 * category, with the source text on hover.
 *
 * Isolated in its own module so plotly is imported from exactly one place.
 * The route is already lazy-loaded, so the charting engine lands in the
 * embeddings chunk and never touches the initial bundle.
 *
 * The axes are deliberately blank. They are PCA components — they carry no
 * unit and their absolute values mean nothing, so tick numbers would invite
 * a reading the data does not support. Only relative position is meaningful,
 * which is exactly what the design mock shows.
 */
export function SemanticPlot({ presets, customPlacement }: SemanticPlotProps) {
  const isDark = useIsDarkTheme()

  // Backgrounds stay transparent so the Tailwind card behind shows through
  // and the plot is themed without plotly knowing about it. Only the legend
  // font needs an explicit colour, since plotly draws that text itself.
  const fontColor = isDark ? '#9b9cb5' : '#4b5563'
  const labelColor = isDark ? '#eef0fa' : '#111827'

  // The preset traces are rebuilt from the same unchanged preset data, so
  // adding a custom point appends a trace and leaves every existing marker
  // exactly where it was. Nothing here recomputes a projection — the backend
  // transforms the new point into the presets' already-fitted space.
  const traces = [
    ...buildCategoryTraces(presets),
    ...(customPlacement ? [buildCustomTrace(customPlacement, labelColor)] : []),
  ]

  return (
    <Plot
      data={traces}
      layout={{
        autosize: true,
        height: 420,
        margin: { l: 16, r: 16, t: 16, b: 16 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: fontColor, size: 12 },
        showlegend: true,
        legend: { orientation: 'h', y: -0.08, font: { color: fontColor } },
        hovermode: 'closest',
        xaxis: { visible: false, zeroline: false },
        yaxis: { visible: false, zeroline: false, scaleanchor: 'x' },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%', height: '420px' }}
      useResizeHandler
      aria-label="Semantic plot of preset example texts"
    />
  )
}
