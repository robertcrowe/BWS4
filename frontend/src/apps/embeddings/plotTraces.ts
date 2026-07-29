// Built with Spec4 AI - https://spec4.ai
import type { PlacementResult, PresetPoint } from '../../api/embeddings'

/**
 * Category colours, taken from the design mock's palette so this plot matches
 * the rest of the showcase: Animals `--accent2`, Emotions `--danger`,
 * Technology `--accent1`, Food `--warn`.
 *
 * Hard-coded hex rather than Tailwind classes because plotly draws to its own
 * SVG canvas and cannot resolve CSS utility classes. These four read
 * acceptably against both the light and dark card backgrounds, which is why
 * the plot's own background is left transparent rather than themed.
 */
export const CATEGORY_COLORS: Record<string, string> = {
  Animals: '#4ea1ff',
  Emotions: '#ff6b6b',
  Technology: '#7c5cff',
  Food: '#f6b93b',
}

/** Fallback for a category the palette does not name, so a new backend category still plots. */
export const FALLBACK_COLOR = '#9b9cb5'

/**
 * Visual treatment for a visitor's own point, distinct from presets on four
 * independent axes: a different symbol (diamond, not circle), a larger size,
 * a thick contrasting outline, and a colour no category uses.
 *
 * The design mock fills the custom marker with the violet→blue accent
 * gradient. That is not reproducible on a plotly marker, and worse, both of
 * its stops are already category colours here — violet is Technology and blue
 * is Animals — so a gradient marker would read as a preset. `--success` from
 * the same palette is unused by any category, which keeps the "your text"
 * point unmistakable while staying inside the mock's colour set.
 */
export const CUSTOM_POINT_COLOR = '#34d399'
export const CUSTOM_POINT_SYMBOL = 'diamond'
export const CUSTOM_TRACE_NAME = 'Your text'

/** One plotly scatter trace: a category's points, sharing a colour and a legend entry. */
export interface CategoryTrace {
  type: 'scatter'
  mode: 'markers'
  name: string
  x: number[]
  y: number[]
  text: string[]
  hovertemplate: string
  marker: { size: number; color: string; line: { width: number; color: string } }
}

/** The visitor's own point: a labelled diamond with its own legend entry. */
export interface CustomTrace {
  type: 'scatter'
  mode: 'markers+text'
  name: string
  x: number[]
  y: number[]
  text: string[]
  textposition: string
  textfont: { size: number; color: string }
  hovertemplate: string
  marker: {
    size: number
    color: string
    symbol: string
    line: { width: number; color: string }
  }
}

/**
 * Group presets into one plotly trace per category.
 *
 * One trace per category rather than a single trace with a colour array: it
 * is what gives plotly a legend entry per category, and lets a visitor
 * isolate one cluster by clicking it. That legend is doing real explanatory
 * work here — the clustering claim is only legible if you can tell which
 * colour means what.
 *
 * Categories are emitted in first-seen order so the legend is stable across
 * renders rather than reordering with object key iteration.
 *
 * @param presets - The preset points returned by the backend.
 * @returns One trace per distinct category, each carrying its points' labels
 * for the hover tooltip.
 */
export function buildCategoryTraces(presets: PresetPoint[]): CategoryTrace[] {
  const order: string[] = []
  const grouped = new Map<string, PresetPoint[]>()

  for (const preset of presets) {
    if (!grouped.has(preset.category)) {
      grouped.set(preset.category, [])
      order.push(preset.category)
    }
    grouped.get(preset.category)!.push(preset)
  }

  return order.map((category) => {
    const points = grouped.get(category)!
    return {
      type: 'scatter',
      mode: 'markers',
      name: category,
      x: points.map((point) => point.x),
      y: points.map((point) => point.y),
      text: points.map((point) => point.label),
      // %{text} is the source text; the category comes from the trace name.
      hovertemplate: `<b>%{text}</b><br>${category}<extra></extra>`,
      marker: {
        size: 11,
        color: CATEGORY_COLORS[category] ?? FALLBACK_COLOR,
        line: { width: 1, color: 'rgba(255,255,255,0.35)' },
      },
    }
  })
}

/**
 * Build the trace for a visitor's placed text.
 *
 * Returned as a separate trace appended after the category traces, never
 * merged into one of them: it keeps the preset traces byte-identical when a
 * point is added (so plotly has no reason to redraw them), and it earns the
 * custom point its own legend entry saying whose point it is.
 *
 * The label is drawn on the plot rather than left to hover, since the whole
 * question a visitor has just asked is "where did *my* text go?" — that
 * should not require finding and hovering the right marker.
 *
 * @param placement - The backend's placement response.
 * @param labelColor - Theme-appropriate colour for the on-plot label.
 * @returns A single-point trace visually distinct from every preset trace.
 */
export function buildCustomTrace(placement: PlacementResult, labelColor: string): CustomTrace {
  return {
    type: 'scatter',
    mode: 'markers+text',
    name: CUSTOM_TRACE_NAME,
    x: [placement.point.x],
    y: [placement.point.y],
    text: [placement.text],
    textposition: 'top center',
    textfont: { size: 12, color: labelColor },
    hovertemplate: `<b>%{text}</b><br>${CUSTOM_TRACE_NAME}<extra></extra>`,
    marker: {
      size: 18,
      color: CUSTOM_POINT_COLOR,
      symbol: CUSTOM_POINT_SYMBOL,
      line: { width: 2, color: '#ffffff' },
    },
  }
}
