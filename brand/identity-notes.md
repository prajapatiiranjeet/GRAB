# Grab identity

## Design direction

The symbol is a square, open-frame G. Its heavy modular strokes borrow the proportions of a media viewport; the inward bar makes the frame read as a G and as a selected item being pulled into a tool. It avoids the usual play triangle and download arrow, and remains one solid shape in monochrome.

The wordmark is drawn as a compact, angular display face, paired with a high-legibility monospace interface. The visual tone stays direct and utilitarian, while the warm paper and oxide palette keeps the brutalist layout from feeling clinical. The logo is built as vector geometry and does not depend on a downloadable font.

## Palette

| Token | Light | Dark | Use |
|---|---|---|---|
| Page | `#F4F0E7` · RGB 244 240 231 | `#191917` · RGB 25 25 23 | Main canvas |
| Surface | `#FFFCF5` · RGB 255 252 245 | `#22221F` · RGB 34 34 31 | Panels and controls |
| Ink | `#191916` · RGB 25 25 22 | `#F3EEE4` · RGB 243 238 228 | Text and wordmark |
| Accent | `#BF4328` · RGB 191 67 40 | `#FF8968` · RGB 255 137 104 | Symbol, primary actions, progress |
| Focus | `#176A83` · RGB 23 106 131 | `#8BD1E2` · RGB 139 209 226 | Keyboard focus |

## Logo files

- `grab-symbol.svg` is the standalone one-colour master.
- `grab-horizontal-light.svg` and `grab-horizontal-dark.svg` are theme-specific lockups.
- `grab-stacked-light.svg` and `grab-stacked-dark.svg` are tall-format lockups.
- `grab-horizontal-black.svg`, `grab-horizontal-white.svg`, `grab-symbol-black.svg`, and `grab-symbol-white.svg` are single-colour production variants.
- `grab-symbol-square.svg` and `grab-app-icon.svg` cover avatar and app-tile use.
- Web and app icons are generated into `public/` from the symbol master.
- The application header draws the lockup inline with theme-token fills so it follows manual and system theme changes.

## Use

- Keep at least 48 symbol-grid units of clear space around the mark; the symbol-only file already includes its own padding.
- Use the symbol at 16 px or larger. Keep the horizontal lockup at 220 px wide or larger; use the symbol alone in smaller spaces.
- Use the light lockup on warm paper or light surfaces and the dark lockup on charcoal surfaces. Do not place either on noisy imagery or recolour the elements independently.
- The primary oxide ink converts approximately to CMYK 0 / 65 / 79 / 25. Verify a physical swatch with the printer; no Pantone match has been assigned.
- The interface uses operating-system monospace and sans-serif stacks; no webfont or added font licence is required.
- Avoid gradients, drop shadows, skewing, stretching, rotations, and adding a tagline inside the lockup.

The wordmark is intentionally built from monoline vector strokes. For cutting, embroidery, or print workflows that require filled contours, outline those strokes in a vector editor first. Trademark clearance has not been performed.
