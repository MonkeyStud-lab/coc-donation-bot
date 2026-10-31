# Harbor web interface

Harbor is the only web interface, with black content surfaces, cobalt actions,
brass highlights, and a local abstract wallpaper. There is no interface or theme
selector. Legacy desktop theme preferences stay separate.

The sidebar, page header, and main panels use the actual WebGL refraction shader adapted from
[dashersw/liquid-glass-js](https://github.com/dashersw/liquid-glass-js), pinned to
`78cb6ccb0b9987bb60a88b14ccbd13a9e6e8ab2a`. The shader bends the wallpaper at
rounded edges and corners. This is not a CSS backdrop-blur substitution. Settings,
logs, account cards, labels, and buttons remain sharp DOM content above it.

The upstream MIT license is retained in `web/src/vendor/liquid-glass/LICENSE`,
in the renderer's bundle notice, and in the distributed `liquid-glass-LICENSE.txt`.
The adapter replaces page screenshots and nested demo buttons with a cached
viewport-sized wallpaper texture. It draws on load, scroll, resize, and visibility
changes rather than running a continuous animation loop. Hidden tabs do not render.
All registered surfaces share one fixed canvas, one GL context, and one wallpaper
texture. Scroll events draw immediately with current viewport rectangles; resize
and layout notifications are batched. Offscreen regions are skipped and tall
panels are clipped before drawing. Internal log scrolling does not redraw stationary
panels. The last surface leaving releases the renderer and its listeners.

Refraction displacement is normalized to CSS pixels so resizing the browser does
not stretch its apparent offset. The production renderer uses a sharp texture
sample instead of the upstream multi-sample blur; its actual edge/corner
refraction remains enabled. Only the fixed wallpaper is refracted, not changing
log text, game video, or other DOM content. The opaque fallback preserves operation
if the browser cannot provide a GL context.

Reduced transparency, increased contrast, forced colors, unavailable WebGL, image
errors, and context loss fall back to opaque panels and navigation. A dark readability veil
keeps text legible over bright portions of the image. The controller and game do
not depend on WebGL. GPU rendering happens in the viewing browser.

Page-switch animations have been removed. Sidebar navigation changes pages
immediately, and clicking the current page preserves its unsaved settings.

The generated wallpaper is `web/public/harbor-abstract.jpg`, served locally; it
makes no external image requests. The previous landscape asset was removed.
Built-in image-generation prompt:

> Create an original abstract 16:9 desktop wallpaper for a dark self-hosted dashboard.
> Main colors: deep near-black, saturated cobalt blue, and warm brushed brass.
> Sculptural, broad flowing bands of cobalt glass and thin brass metallic ribbons
> curving across a black field, with restrained realistic edge lighting and deep
> negative space. The brightest curved details live toward the left and top/right
> edges so they can be visibly bent through refractive glass navigation panels;
> keep the center mostly black and calm for opaque UI content cards. Elegant
> material study, photographic 3D abstraction rather than illustration, no neon glow,
> no purple, no pink, no text, no symbols, no logo, no UI. Crisp large forms, not busy
> fine textures or particles. Wide wallpaper, dark and understated, cobalt is the
> dominant chromatic color and brass is a limited accent.

Run `pnpm --dir web test` and `pnpm --dir web run build`. The optional
`node scripts/build-refraction-probe.mjs` command, run from `web/`, builds a
separate GPU fixture under `data/debug/refraction-probe`; it is never included
in the distributed app. Its checkerboard comparison verifies that turning on
refraction changes rendered pixels while preserving zero WebGL errors and clean
resource disposal. The fixture also tests the shared renderer against known source
pixels after movement and with partly offscreen or very tall panels. Use the
isolated web preview for responsive and live-state checks; the hidden
`.glass-scene` element records the sampled scroll offset and surface count for QA.

Design craft also follows [Unslop](https://heydamir.design/unslop), by Damir
Sokolovsky (@heydamir), CC BY 4.0, and Apple's material-layer accessibility guidance.
