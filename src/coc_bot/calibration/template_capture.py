from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from coc_bot.calibration.picker import pick_interactive


def save_template(frame: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)


def crop_by_coords(frame: np.ndarray, coords: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = coords
    return frame[y : y + h, x : x + w].copy()


def sample_center_color(frame: np.ndarray, coords: tuple[int, int, int, int]) -> list[int]:
    crop = crop_by_coords(frame, coords)
    cy, cx = crop.shape[0] // 2, crop.shape[1] // 2
    bgr = crop[cy, cx].tolist()
    return [int(v) for v in bgr]


def _typed_roi(label: str) -> tuple[int, int, int, int]:
    print(f"\n--- {label} (digitacao alternativa) ---")
    print("Insira a ROI como: x y largura altura (pixels)")
    while True:
        raw = input("> ").strip()
        parts = raw.split()
        if len(parts) == 4:
            try:
                return tuple(int(p) for p in parts)  # type: ignore[return-value]
            except ValueError:
                pass
        print("Entrada invalida. Exemplo: 100 200 800 600")


def _typed_point(label: str) -> tuple[int, int]:
    print(f"\n--- {label} (digitacao alternativa) ---")
    print("Insira o ponto de toque como: x y")
    while True:
        raw = input("> ").strip()
        parts = raw.split()
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                pass
        print("Entrada invalida. Exemplo: 540 960")


def prompt_roi(
    label: str,
    frame: np.ndarray | None = None,
    *,
    refresh_cb=None,
    return_frame: bool = False,
):
    """
    Escolher ROI via popup de screenshot (preferido) ou coordenadas digitadas.

    Passe ``frame`` quando o assistente ja capturou a tela correta pra o seletor
    mostrar essa imagem. Se ``return_frame`` for True, retorna ``(roi, frame_usado)``.
    """
    result, used = pick_interactive(frame, label, mode="roi", refresh_cb=refresh_cb)
    if result is not None and len(result) == 4:
        x, y, w, h = (int(v) for v in result)
        if w > 0 and h > 0:
            print(f"ROI selecionada: {x} {y} {w} {h}")
            roi = (x, y, w, h)
            if return_frame:
                return roi, used if used is not None else frame
            return roi
        print("ROI estava vazia — tente novamente ou digite as coordenadas.")
    else:
        print("Seletor cancelado ou indisponivel.")
    roi = _typed_roi(label)
    if return_frame:
        return roi, used if used is not None else frame
    return roi


def prompt_point(
    label: str,
    frame: np.ndarray | None = None,
    *,
    refresh_cb=None,
) -> tuple[int, int]:
    """Escolher ponto de toque via popup de screenshot (preferido) ou coordenadas digitadas."""
    result, _used = pick_interactive(frame, label, mode="point", refresh_cb=refresh_cb)
    if result is not None and len(result) == 2:
        x, y = int(result[0]), int(result[1])
        print(f"Ponto selecionado: {x} {y}")
        return x, y
    print("Seletor cancelado ou indisponivel.")
    return _typed_point(label)


def prompt_yes_no(label: str) -> bool:
    raw = input(f"{label} [s/N]: ").strip().lower()
    return raw in ("s", "sim", "y", "yes")
