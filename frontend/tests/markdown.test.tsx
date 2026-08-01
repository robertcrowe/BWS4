// Built with Spec4 AI - https://spec4.ai
/**
 * The shared markdown renderer's contract.
 *
 * Five screens now point model output at this component, so its behaviour is
 * tested once here rather than five times over. Each app's own suite asserts
 * only that its answer surface *goes through* this renderer; what the renderer
 * then does is this file's job.
 *
 * Two properties matter more than the rest:
 *
 * - **Raw HTML in model output stays text.** This is the reason the component
 *   exists. Every one of those five surfaces is public, unauthenticated, and
 *   shows prose derived from free-form visitor input.
 * - **A single newline still breaks the line.** Markdown collapses soft breaks
 *   into spaces, and four of the five callers render output from prompts that
 *   never asked for markdown. Without this the change would silently reflow
 *   text that plain rendering used to lay out correctly.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Markdown } from '../src/components/Markdown'

describe('the shared markdown renderer', () => {
  it('turns markdown into real elements rather than printing the syntax', () => {
    render(<Markdown>{'A **bold** claim.\n\n- first point\n- second point'}</Markdown>)

    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    // The syntax itself is gone, not merely styled.
    expect(screen.queryByText(/\*\*bold\*\*/)).toBeNull()
  })

  it('renders an ordered list as an ordered list', () => {
    render(<Markdown>{'1. first\n2. second'}</Markdown>)

    const list = screen.getAllByRole('list')[0]
    expect(list.tagName).toBe('OL')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  describe('raw HTML in model output', () => {
    const PAYLOAD = '<img src=x onerror="alert(1)"> and <script>alert(2)</script>'

    it('is rendered as text, never as markup', () => {
      const { container } = render(<Markdown>{PAYLOAD}</Markdown>)

      expect(container).toHaveTextContent('<img src=x onerror="alert(1)">')
      expect(container.querySelector('img')).toBeNull()
      expect(container.querySelector('script')).toBeNull()
      // Note this deliberately does *not* assert the absence of `onerror=`:
      // the payload survives as escaped text, so that substring is present and
      // inert. What must be absent is a tag opening.
      expect(container.innerHTML).not.toContain('<img')
      expect(container.innerHTML).not.toContain('<script')
    })

    it('is escaped in the emitted HTML, not just absent from the DOM tree', () => {
      const { container } = render(<Markdown>{PAYLOAD}</Markdown>)

      // The distinction matters: an element could be stripped by jsdom while
      // the string still round-trips somewhere else as live markup.
      expect(container.innerHTML).toContain('&lt;img')
    })
  })

  it('drops link targets, keeping only the text', () => {
    const { container } = render(
      <Markdown>{'See [the docs](https://example.invalid/evil).'}</Markdown>,
    )

    expect(container).toHaveTextContent('the docs')
    // A link in model output points wherever the model decided.
    expect(container.querySelector('a')).toBeNull()
    expect(container.innerHTML).not.toContain('example.invalid')
  })

  describe('output that is not markdown at all', () => {
    it('keeps a single newline as a line break', () => {
      // Markdown itself collapses this to a space. The `\n` survives into the
      // text node and `whitespace-pre-wrap` is what renders it as a break, so
      // both halves are asserted — either one alone would pass while the text
      // reflowed on screen.
      const { container } = render(<Markdown>{'line one\nline two'}</Markdown>)

      const paragraph = container.querySelector('p')
      expect(paragraph?.textContent).toBe('line one\nline two')
      expect(paragraph?.className).toContain('whitespace-pre-wrap')
    })

    it('leaves prose containing no markdown exactly as written', () => {
      const prose = 'The latest release adds agent composition. It shipped in June.'
      const { container } = render(<Markdown>{prose}</Markdown>)

      expect(container.textContent).toBe(prose)
    })

    it('renders an empty string as nothing rather than throwing', () => {
      const { container } = render(<Markdown>{''}</Markdown>)

      expect(container.textContent).toBe('')
    })
  })

  it('leaves a bare bracketed citation marker literal', () => {
    // The RAG screen's passage cards are keyed to these markers, and a `[1]`
    // with no matching link definition is plain text in CommonMark. If that
    // ever stopped holding, every RAG answer would lose its citations.
    const { container } = render(<Markdown>{'Voyager 1 launched in 1977 [1].'}</Markdown>)

    expect(container).toHaveTextContent('Voyager 1 launched in 1977 [1].')
    expect(container.querySelector('a')).toBeNull()
  })

  describe('the prominence variants', () => {
    it('renders the lead variant larger and darker than the default', () => {
      const { container: lead } = render(<Markdown variant="lead">text</Markdown>)
      const { container: base } = render(<Markdown variant="default">text</Markdown>)

      expect(lead.querySelector('p')?.className).toContain('text-[15px]')
      expect(base.querySelector('p')?.className).toContain('text-sm')
      expect(lead.querySelector('p')?.className).not.toBe(
        base.querySelector('p')?.className,
      )
    })

    it('defaults to the quieter variant when none is given', () => {
      const { container: implicit } = render(<Markdown>text</Markdown>)
      const { container: explicit } = render(<Markdown variant="default">text</Markdown>)

      expect(implicit.querySelector('p')?.className).toBe(
        explicit.querySelector('p')?.className,
      )
    })

    it('applies the variant to list items too, not only paragraphs', () => {
      const { container } = render(<Markdown variant="lead">{'- a point'}</Markdown>)

      expect(container.querySelector('li')?.className).toContain('text-[15px]')
    })
  })
})
