/* Shared inline SVG marks.
 *
 * These replace the emoji this UI used to render (🎯 for the brand, 🎙 for the
 * interviewer avatar). Emoji are drawn by the OS, so the product looked
 * different on every machine and never quite looked like a hiring tool; a mark
 * we own renders identically and inherits `currentColor`. */

/** Brand mark: a speech bubble with a rising bar chart — the two halves of the
 *  product, a conversation that produces a score. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v9a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.5A.75.75 0 0 1 4.6 20v-3.2A2.5 2.5 0 0 1 4 14.5z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <rect x="8" y="11" width="2" height="3" rx="0.6" fill="currentColor" />
      <rect x="11.5" y="9" width="2" height="5" rx="0.6" fill="currentColor" />
      <rect x="15" y="6.5" width="2" height="7.5" rx="0.6" fill="currentColor" />
    </svg>
  )
}

/** Interviewer avatar glyph. */
export function MicGlyph({ size = 15 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="9" y="2" width="6" height="11" rx="3" />
      <path d="M19 11v1a7 7 0 0 1-14 0v-1" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  )
}
