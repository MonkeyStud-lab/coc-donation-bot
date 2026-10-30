# Harbor web interface

Harbor is the only web interface. Every browser opens it automatically, regardless of
any previously saved Original or Watchtower preference. There is no interface or web
theme selector. Legacy desktop theme settings remain separate.

The sidebar and page toolbar use translucent fills, backdrop blur, and quiet edge
highlights. Settings, activity logs, account cards, and other content stay opaque for
readability. Browsers without backdrop-filter support receive solid navigation surfaces.
Reduced-transparency and increased-contrast preferences remove the wallpaper and glass.

Sidebar navigation animates the existing page element for 180 ms with a short fade and
8 px rise. It does not remount the application, delay input, or restart the controller.
Further navigation cancels the previous animation. Reduced motion disables it.

The original mountain-and-lake wallpaper is served locally from
`web/public/harbor-wallpaper.jpg`; it adds about 180 KiB, makes no third-party requests,
and is fixed rather than animated. It was generated using the built-in image tool and
JPEG-encoded without altering the scene. Prompt: “A peaceful alpine mountain lake,
layered blue mountains, an evergreen peninsula, soft morning light, pearl-blue sky,
spacious low-contrast center, muted blue/slate/sage, no text, logos, or UI.”

`harbor.css` controls layout and materials, `interfacePalettes.ts` defines the single
semantic palette, and `pageTransition.ts` manages cancellable motion. Obsolete interface
selection code, alternate layout CSS, and the dark palette are removed. Existing browser
preferences are ignored; no storage migration or account-settings edit is required.

Run `pnpm --dir web test` and `pnpm --dir web run build`. Check sidebar navigation,
unsaved settings, keyboard focus, narrow widths, and motion preferences in the isolated
`scripts/preview_web_offline.py` preview before deployment. Color tests enforce 4.5:1
text/action contrast and 3:1 field boundaries and resource meters.

Design references: [Unslop](https://heydamir.design/unslop) by Damir Sokolovsky
(@heydamir), CC BY 4.0, informed spacing, hierarchy, icon consistency, and restraint.
Apple's [materials](https://developer.apple.com/design/human-interface-guidelines/materials)
and [motion](https://developer.apple.com/design/human-interface-guidelines/motion) guidance
informed navigation-only glass and brief, optional transitions.

The suggested [liquid-glass-js](https://github.com/dashersw/liquid-glass-js) implementation
was reviewed. It uses page snapshots and WebGL; this app uses native CSS backdrop filters
instead, with no html2canvas dependency, custom WebGL contexts, or snapshot rendering.
This is a web approximation of glass, not Apple's native Liquid Glass material.
