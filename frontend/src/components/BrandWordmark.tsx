/**
 * River wordmark for in-app use (header / dashboard).
 *
 * Renders the product name in the --font-serif stack (system Georgia), regular
 * weight, slight tracking, with fill="currentColor" so it inherits the link's
 * --color-text-primary and stays legible in both light and dark themes.
 *
 * The standalone, fixed-color assets used outside React live in
 * public/river-wordmark.svg (horizontal) and public/river-mark.svg (favicon).
 */
export default function BrandWordmark() {
  return (
    <svg viewBox="0 0 172 76" role="img" aria-hidden="true" focusable="false">
      <text
        x="8"
        y="54"
        fontFamily="Georgia, 'Source Serif 4', 'Lora', 'Times New Roman', serif"
        fontSize="60"
        fontWeight="400"
        letterSpacing="0.9"
        fill="currentColor"
      >
        River
      </text>
    </svg>
  );
}
