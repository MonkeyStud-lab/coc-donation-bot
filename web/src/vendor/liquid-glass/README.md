# Liquid Glass renderer

Source: https://github.com/dashersw/liquid-glass-js

Pinned commit: `78cb6ccb0b9987bb60a88b14ccbd13a9e6e8ab2a`

Copyright (c) 2025 Armagan Amcalar. MIT; see LICENSE.

Container.js retains the upstream vertex/fragment shaders, shape masks, geometry,
refraction, and Gaussian sampling. The adapter replaces full-page html2canvas
capture and nested buttons with the supplied fixed wallpaper. Scroll, resize, and
visibility changes request draws; no continuous animation loop is used.

Changes include an ES module export, owned React canvas mounting, configurable
refraction controls, zero document-scroll offset for the fixed wallpaper, cached
viewport textures, explicit buffer/program/context disposal, shader error handling,
and skipping the sampled-tint work when tint is disabled. The tint is applied as a
separate dark readability veil above the refracted image; DOM controls remain sharp.

No upstream demo, html2canvas, Button class, CDN script, or remote asset is bundled.
The license is also included in the distributed web assets.
