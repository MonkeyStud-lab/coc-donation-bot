# Harbor web interface

Harbor is the only web interface, with black translucent panels, cobalt actions,
brass highlights, and a local abstract wallpaper. There is no web theme selector.
Legacy desktop theme preferences stay separate.

Panels use ordinary CSS backgrounds: 78% opaque near-black for content and 82%
for navigation. Text, controls, logs, and game video remain native browser content.
No WebGL canvas, refraction renderer, page snapshots, blur, or scroll-driven
rendering is used. Rounded corners follow the panels themselves.

Reduced transparency, increased contrast, and forced colors use opaque panels.
Text contrast is checked against both bright and dark backdrop extremes. Page
switching has no animation, and clicking the current page preserves unsaved settings.

The wallpaper is `web/public/harbor-abstract.jpg`, served locally with no external
image requests. It stays fixed as the page scrolls.

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

Run `pnpm --dir web test` and `pnpm --dir web run build`. Use the isolated web
preview to check responsive layouts, native controls, and scrolling. Include
right-hand corners in screenshots when checking panel boundaries.

Design craft follows [Unslop](https://heydamir.design/unslop), by Damir Sokolovsky
(@heydamir), CC BY 4.0, and Apple's readability and accessibility principles.
