# Web interfaces

Use **Interface** in the page header to choose **Original**, **Watchtower**, or
**Harbor**. The choice applies immediately and stays in this browser, independently
of the game account. Other browsers keep their own choice. Original remains the
default layout.

Switching retains the current page, open dialogs, calibration selections, and unsaved
settings. It sends no command to the controller and requires no bot restart. If browser
storage is unavailable, switching still works for the current session. The first-launch
test has a separate preference, so experimenting there does not change the normal view.

Watchtower uses graphite surfaces with an amber accent, a horizontal navigation
rail, and a compact activity ledger with tabular timestamps. Harbor uses a light
pearl palette with a blue accent, a persistent sidebar, horizontal settings categories,
larger grouped inputs, and a resource summary above the activity feed. Original keeps
the previous layout with the graphite palette. Both new interfaces retain every
operational page and control, keyboard focus indicators, and reduced-motion support.
At narrow widths, navigation scrolls horizontally and settings fields stack below labels.

The interface choice includes its palette. The old separate web Theme menu is removed.
Legacy desktop theme preferences are retained for the desktop fallback and do not
change the browser's appearance.

The implementation shares the mounted React tree. `InterfacePicker.tsx` manages the
validated browser preference; `interfaces.css` scopes layout rules to the root
`data-interface` attribute. `interfacePalettes.ts` defines semantic colors and
maps the interface to its palette. The root also gets `data-appearance` and a matching
`color-scheme`, so native inputs and pop-up menus use the appropriate appearance.
Do not key the application by interface: remounting would discard in-progress work.

Run `pnpm --dir web test` and `pnpm --dir web run build` after changes. For visual
checks, use `scripts/preview_web_offline.py` with the compiled assets. Check all three
interfaces at desktop and narrow widths, then edit a setting, switch interfaces, and
verify the draft and selected category remain intact. Reload to check persistence.
Palette checks enforce 4.5:1 for text and action labels, and 3:1 for resource meters.
The preview uses temporary configuration and forbids live ADB calls.

Design references: the [Unslop skill](https://heydamir.design/unslop) by Damir
Sokolovsky (@heydamir), CC BY 4.0, informed Watchtower's spacing, quiet chrome,
typographic hierarchy, and restrained use of color. Apple's Human Interface Guidelines
for [layout](https://developer.apple.com/design/human-interface-guidelines/layout),
[accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility),
and [settings](https://developer.apple.com/design/human-interface-guidelines/settings)
informed Harbor's adaptive grouping and controls. These are web interfaces, not
imitations of native macOS windows.
