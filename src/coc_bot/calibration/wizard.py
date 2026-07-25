from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.adb.input import InputController
from coc_bot.calibration.template_capture import (
    prompt_point,
    prompt_roi,
    prompt_yes_no,
    sample_center_color,
    save_template,
)  # noqa: F401 — prompt_point/roi used by _pick_* helpers
from coc_bot.config import BotConfig, load_config, save_calibrated
from coc_bot.logging_utils import setup_logging
from coc_bot.vision.rois import normalize_roi


STEP_IDS = (
    "home",
    "clan_chat",
    "donation_request",
    "donation_panel",
    "slot_colors",
    "grid",
    "farm",
    "optional",
)


@dataclass(frozen=True)
class CalibrationPart:
    """One tangible item inside a calibration step (shown as a subsection in the GUI)."""

    key: str
    label: str
    kind: str  # tap | template | roi | color | grid | meta
    optional: bool = False
    description: str = ""


@dataclass(frozen=True)
class CalibrationStep:
    step_id: str
    title: str
    summary: str
    status_keys: tuple[str, ...]
    parts: tuple[CalibrationPart, ...] = ()


STEPS: dict[str, CalibrationStep] = {
    "home": CalibrationStep(
        "home",
        "Tela inicial",
        "Tamanho da tela, ancora home (opcional), botao abrir chat",
        ("frame_width", "open_chat"),
        (
            CalibrationPart("frame_width", "Tamanho da tela", "meta", description="Capturado automaticamente do screenshot"),
            CalibrationPart("home", "Ancora home", "template", optional=True, description="Foto de algo fixo na tela da vila (ex: edificio, botao Atacar)"),
            CalibrationPart(
                "open_chat",
                "Botao abrir chat",
                "tap",
                description="A bolha/aba '>' que abre o chat do clan — fica na lateral esquerda da vila",
            ),
        ),
    ),
    "clan_chat": CalibrationStep(
        "clan_chat",
        "Chat do clan",
        "Areas do chat, ancora clan_chat, aba fechar, icones de pular",
        ("chat_panel", "chat_requests", "clan_chat", "chat_scroll_down", "chat_request_jump"),
        (
            CalibrationPart("chat_panel", "ROI de todo o chat aberto", "roi", description="Retangulo cobrindo toda a area do chat aberto (de cima ate baixo)"),
            CalibrationPart("chat_requests", "ROI dos pedidos de doacao", "roi", description="Area onde aparecem as msgs 'Precisamos de...' com botao Doar"),
            CalibrationPart("clan_chat", "Ancora do chat", "template", description="Algo fixo visivel no chat aberto que some quando o painel de doacao abre"),
            CalibrationPart(
                "close_chat",
                "Aba fechar chat '<'",
                "tap",
                optional=True,
                description="A tab laranja '<' na borda direita do chat aberto",
            ),
            CalibrationPart(
                "chat_request_jump",
                "Icone de exclamacao '!'",
                "template",
                optional=True,
                description="Icone ! que aparece no topo ou rodape do chat quando tem pedido",
            ),
            CalibrationPart(
                "chat_scroll_down",
                "Icone seta pra baixo",
                "template",
                optional=True,
                description="Seta pra baixo no chat (seta pra cima quando ha msgs acima)",
            ),
        ),
    ),
    "donation_request": CalibrationStep(
        "donation_request",
        "Botao Doar",
        "Template do botao 'Doar' que aparece nas msgs do chat do clan",
        ("donate_button",),
        (
            CalibrationPart(
                "donate_button",
                "Botao Doar",
                "template",
                description="O botao verde/amarelo 'Doar' dentro de uma mensagem de pedido no chat",
            ),
        ),
    ),
    "donation_panel": CalibrationStep(
        "donation_panel",
        "Painel de doacao",
        "Titulo, barras de tropas/magias, toque fora pra fechar",
        ("donation_troop_bar", "donation_spell_bar", "tap_outside_donation"),
        (
            CalibrationPart(
                "donation_panel",
                "Titulo 'Doar Recurso'",
                "template",
                optional=True,
                description="Texto 'Doar Recurso' no topo do painel branco de doacao",
            ),
            CalibrationPart("donation_troop_bar", "ROI da barra de tropas + cerco", "roi", description="Retangulo na barra horizontal de tropas (inclui maquinas de cerco)"),
            CalibrationPart("donation_spell_bar", "ROI da barra de magias", "roi", description="Retangulo na barra horizontal de magias abaixo da barra de tropas"),
            CalibrationPart(
                "tap_outside_donation",
                "Toque fora pra fechar",
                "tap",
                description="Ponto na area escura (fora do painel branco) pra fechar o painel",
            ),
        ),
    ),
    "slot_colors": CalibrationStep(
        "slot_colors",
        "Cores dos slots",
        "Amostras de cor de slots disponiveis e indisponiveis no painel de doacao",
        ("donatable_troop", "disabled_troop", "donatable_spell", "disabled_spell"),
        (
            CalibrationPart("donatable_troop", "Cor slot tropa disponivel", "color", description="Cor de uma barra de tropa colorida (pode receber doacao)"),
            CalibrationPart("disabled_troop", "Cor slot tropa indisponivel", "color", description="Cor de uma barra de tropa cinza/escura (nao pode receber)"),
            CalibrationPart("donatable_spell", "Cor slot magia disponivel", "color", description="Cor de uma barra de magia colorida (pode receber doacao)"),
            CalibrationPart("disabled_spell", "Cor slot magia indisponivel", "color", description="Cor de uma barra de magia cinza/escura (nao pode receber)"),
        ),
    ),
    "grid": CalibrationStep(
        "grid",
        "Grade de slots",
        "Quantas colunas/linhas de slots sao visiveis no painel de doacao",
        ("grid",),
        (
            CalibrationPart("troop_bar", "Grade tropas + cerco", "grid", description="Linhas x colunas visiveis na barra de tropas"),
            CalibrationPart("spell_bar", "Grade magias", "grid", description="Linhas x colunas visiveis na barra de magias"),
        ),
    ),
    "farm": CalibrationStep(
        "farm",
        "Farm / ataque sem rank",
        "Botao Atacar, Batalha sem rank, Encontrar oponente, Voltar, slots de tropas/heroi",
        ("attack_button", "unranked_battle", "return_home"),
        (
            CalibrationPart(
                "attack_button",
                "Botao Atacar!",
                "tap",
                description="O botao 'Atacar!' no canto inferior esquerdo da tela HOME",
            ),
            CalibrationPart(
                "unranked_battle",
                "Batalha sem rank",
                "tap",
                description="O botao 'Batalha' (sem classificacao) dentro do menu Atacar",
            ),
            CalibrationPart(
                "find_match",
                "Encontrar oponente",
                "tap",
                optional=True,
                description="Botao 'Encontrar Oponente' (se aparecer separado da Batalha)",
            ),
            CalibrationPart(
                "return_home",
                "Voltar pra vila",
                "tap",
                description="Botao 'Voltar' / 'OK' no fim da batalha (tela de resultado)",
            ),
            CalibrationPart(
                "edrag_slot",
                "Slot electro dragon",
                "tap",
                optional=True,
                description="Centro da primeira carta de tropa (e-drag) na barra de batalha",
            ),
            CalibrationPart(
                "siege_slot",
                "Slot maquina de cerco",
                "tap",
                optional=True,
                description="Centro da carta de cerco na barra de batalha",
            ),
            CalibrationPart(
                "rage_slot",
                "Slot magia furia",
                "tap",
                optional=True,
                description="Centro da carta de furia na barra de batalha",
            ),
            CalibrationPart(
                "hero_1",
                "Slot heroi 1 (esquerda)",
                "tap",
                optional=True,
                description="Centro da 1a carta de heroi (mais a esquerda)",
            ),
            CalibrationPart(
                "hero_2",
                "Slot heroi 2",
                "tap",
                optional=True,
                description="Centro da 2a carta de heroi",
            ),
            CalibrationPart(
                "hero_3",
                "Slot heroi 3",
                "tap",
                optional=True,
                description="Centro da 3a carta de heroi",
            ),
            CalibrationPart(
                "hero_4",
                "Slot heroi 4 (direita)",
                "tap",
                optional=True,
                description="Centro da 4a carta de heroi (mais a direita)",
            ),
        ),
    ),
    "optional": CalibrationStep(
        "optional",
        "UI opcional",
        "Tela de loading e popup pra dispensar automaticamente",
        ("loading",),
        (
            CalibrationPart("loading", "Tela de loading", "template", optional=True, description="Tela de carregamento que aparece ao abrir o CoC"),
            CalibrationPart("popup_dismiss", "Botao dispensar popup", "template", optional=True, description="Botao X ou 'Fechar' de popups/events"),
            CalibrationPart("popup", "Ancora do popup", "template", optional=True, description="Algo fixo nos popups pra detecta-los"),
        ),
    ),
}


def part_is_configured(config: BotConfig, part: CalibrationPart) -> bool:
    """Whether a subsection item is present in the current calibration."""
    key = part.key
    if part.kind == "meta":
        if key == "frame_width":
            return int(config.frame_width or 0) > 0 and int(config.frame_height or 0) > 0
        return False
    if part.kind == "tap":
        if key == "tap_outside_donation":
            return bool(
                config.tap_points.get("tap_outside_donation")
                or config.tap_points.get("close_donation")
            )
        return bool(config.tap_points.get(key)) or bool(config.templates.get(key))
    if part.kind == "template":
        return bool(config.templates.get(key))
    if part.kind == "roi":
        return key in config.rois
    if part.kind == "color":
        return bool(config.colors.get(key))
    if part.kind == "grid":
        grid = config.grid or {}
        if key in ("troop_bar", "spell_bar"):
            return bool(grid.get(key))
        return bool(grid)
    return False


def parent_step_id(tree_iid: str) -> str:
    """Map a tree selection iid (step or step::part) to the wizard --step id."""
    if "::" in tree_iid:
        return tree_iid.split("::", 1)[0]
    return tree_iid


def _roi_list(coords: tuple[int, int, int, int], w: int, h: int) -> list[float]:
    nr = normalize_roi(*coords, w, h)
    return [nr.x, nr.y, nr.w, nr.h]


def _press_enter(message: str = "Aperte Enter quando estiver pronto...") -> None:
    input(message)


def _keeping(label: str) -> None:
    print(f"Mantendo '{label}' existente (sem alterações).")


def print_step_menu(status: dict[str, bool]) -> None:
    print("\n============================================")
    print("         ETAPAS DE CALIBRACAO               ")
    print("============================================")
    for idx, step_id in enumerate(STEPS, 1):
        step = STEPS[step_id]
        mark = "OK" if status.get(step_id) else "  "
        print(f"\n  {idx}. [{mark}] {step.title}")
        print(f"      {step.summary}")
        for part in step.parts:
            opt = " (opcional)" if part.optional else ""
            print(f"        - {part.label}{opt}")
    print("\n--------------------------------------------")
    print("  Digite o NUMERO da etapa (ex: 1, 2, 3)")
    print("  Varios: 1,3,5  |  Todas: a  |  Sair: q")
    print("--------------------------------------------")


class CalibrationWizard:
    """Interactive calibration with per-step re-run support."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()
        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        self.input = InputController(self.client, dry_run=False)
        self.capture.bind_input(self.input)
        self.templates_dir = self.config.templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        if self.config.calibrated:
            logger.info("Loaded existing calibration from data/calibrated.yaml")

    # --- skip/update helpers (answer 'n' to keep existing values) ---

    def _has_roi(self, key: str) -> bool:
        return key in self.config.rois

    def _has_template(self, key: str) -> bool:
        return key in self.config.templates

    def _has_tap(self, key: str) -> bool:
        return bool(self.config.tap_points.get(key))

    def _has_color(self, key: str) -> bool:
        return key in self.config.colors

    def _should_update(self, label: str, *, exists: bool, optional: bool = False) -> bool:
        if not exists:
            if optional:
                if prompt_yes_no(f"Deseja capturar '{label}' agora?"):
                    return True
                print(f"Pulando '{label}' (não obrigatório).")
                return False
            return True
        if prompt_yes_no(f"Atualizar '{label}'? (já existe uma calibração)"):
            return True
        _keeping(label)
        return False

    def _fresh_frame(self):
        return self.capture.screenshot()

    def _pick_roi(self, label: str, frame=None):
        if frame is None:
            frame = self._fresh_frame()
        return prompt_roi(label, frame, refresh_cb=self._fresh_frame, return_frame=True)

    def _pick_point(self, label: str, frame=None) -> tuple[int, int]:
        if frame is None:
            frame = self._fresh_frame()
        return prompt_point(label, frame, refresh_cb=self._fresh_frame)

    def _maybe_update_roi(self, key: str, label: str, w: int, h: int, *, optional: bool = False) -> None:
        if not self._should_update(label, exists=self._has_roi(key), optional=optional):
            return
        coords, frame = self._pick_roi(label)
        fh, fw = frame.shape[:2]
        self.config.rois[key] = _roi_list(coords, fw, fh)
        self.config.frame_width = fw
        self.config.frame_height = fh
        logger.info("Saved ROI {}", key)

    def _maybe_update_template(
        self,
        key: str,
        label: str,
        rel_path: str,
        frame,
        *,
        optional: bool = False,
    ) -> None:
        if not self._should_update(label, exists=self._has_template(key), optional=optional):
            return
        coords, picked_frame = self._pick_roi(label, frame)
        self._save_template_from_frame(picked_frame, coords, rel_path, key)

    def _maybe_update_template_after_setup(
        self,
        key: str,
        label: str,
        rel_path: str,
        setup_message: str,
        *,
        optional: bool = False,
    ) -> None:
        if not self._should_update(label, exists=self._has_template(key), optional=optional):
            return
        print(setup_message)
        _press_enter()
        frame = self._fresh_frame()
        coords, picked_frame = self._pick_roi(label, frame)
        self._save_template_from_frame(picked_frame, coords, rel_path, key)

    def _maybe_update_tap_point(self, key: str, label: str) -> None:
        if not self._should_update(label, exists=self._has_tap(key)):
            return
        pt = self._pick_point(label)
        self.config.tap_points[key] = list(pt)
        logger.info("Saved tap point {}", key)

    def _maybe_update_color(self, key: str, label: str, frame) -> None:
        if not self._should_update(label, exists=self._has_color(key)):
            return
        coords, picked_frame = self._pick_roi(label, frame)
        self.config.colors[key] = sample_center_color(picked_frame, coords)
        logger.info("Saved color {}", key)

    def _ensure_connected(self) -> None:
        self.client.ensure_connected()

    def _frame_size(self) -> tuple[int, int]:
        w, h = self.config.frame_width, self.config.frame_height
        if w <= 0 or h <= 0:
            frame = self.capture.screenshot()
            h, w = frame.shape[:2]
            self.config.frame_width = w
            self.config.frame_height = h
            self._save()
        return w, h

    def _save(self) -> None:
        save_calibrated(self.config)
        logger.info("Saved data/calibrated.yaml")

    def _save_template_from_frame(
        self,
        frame,
        coords: tuple[int, int, int, int],
        rel_path: str,
        template_key: str,
    ) -> None:
        crop = frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
        save_template(crop, self.templates_dir / rel_path)
        self.config.templates[template_key] = rel_path
        logger.info("Saved template {}", template_key)

    def step_status(self) -> dict[str, bool]:
        status: dict[str, bool] = {}
        for step_id, step in STEPS.items():
            status[step_id] = self._step_configured(step)
        return status

    def _step_configured(self, step: CalibrationStep) -> bool:
        if step.step_id == "home":
            has_open = bool(self.config.tap_points.get("open_chat")) or bool(
                self.config.templates.get("open_chat")
            )
            return self.config.frame_width > 0 and has_open
        if step.step_id == "clan_chat":
            return all(
                k in self.config.rois or k in self.config.templates
                for k in ("chat_panel", "chat_requests", "clan_chat", "chat_scroll_down")
            ) and (
                "chat_scroll_down" in self.config.templates or "chat_request_jump" in self.config.templates
            )
        if step.step_id == "donation_request":
            return "donate_button" in self.config.templates
        if step.step_id == "donation_panel":
            return "donation_troop_bar" in self.config.rois and bool(
                self.config.tap_points.get("tap_outside_donation")
                or self.config.tap_points.get("close_donation")
            )
        if step.step_id == "slot_colors":
            return bool(self.config.colors.get("donatable_troop")) and bool(
                self.config.colors.get("disabled_troop")
            )
        if step.step_id == "grid":
            return bool(self.config.grid)
        if step.step_id == "farm":
            return bool(
                self.config.tap_points.get("attack_button")
                and self.config.tap_points.get("unranked_battle")
                and self.config.tap_points.get("return_home")
            )
        if step.step_id == "optional":
            return "loading" in self.config.templates or "popup_dismiss" in self.config.templates
        return False

    def run_interactive(self) -> None:
        self._ensure_connected()
        print("\n============================================")
        print("   CoC Donation Bot - Calibracao (LDPlayer)")
        print("============================================")
        if self.config.calibrated:
            print("\nCalibracao existente carregada.")
            print("Voce pode reexecutar qualquer etapa sem perder as outras.\n")

        handlers = self._handlers()
        step_list = list(STEP_IDS)
        while True:
            print_step_menu(self.step_status())
            print("\nDigite o numero da etapa (ex: 1), varias (ex: 1,3,5), 'a' pra todas ou 'q' pra sair:")
            raw = input("> ").strip().lower()
            if raw in ("q", "quit", "exit"):
                print("Saindo da calibracao.")
                break
            if raw in ("a", "all"):
                self.run_steps(step_list)
                continue
            if not raw:
                continue
            # Parse numbers or names
            selected: list[str] = []
            invalid: list[str] = []
            for part in raw.replace(" ", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                # Try number
                if part.isdigit():
                    num = int(part)
                    if 1 <= num <= len(step_list):
                        selected.append(step_list[num - 1])
                    else:
                        invalid.append(part)
                # Try name
                elif part in STEP_IDS:
                    selected.append(part)
                else:
                    invalid.append(part)
            if invalid:
                print(f"Opcao(s) invalida(s): {', '.join(invalid)}")
                continue
            if selected:
                self.run_steps(selected)

    def run_steps(self, step_ids: list[str]) -> None:
        self._ensure_connected()
        handlers = self._handlers()
        for step_id in step_ids:
            if step_id not in handlers:
                logger.error("Etapa desconhecida: {}", step_id)
                continue
            print(f"\n{'=' * 50}")
            print(f"  ETAPA: {STEPS[step_id].title}")
            print(f"{'=' * 50}")
            handlers[step_id]()
            self._save()
            print(f"\n✓ Etapa '{step_id}' salva com sucesso!\n")
        print("\n============================================")
        print("        Calibracao concluida com sucesso!   ")
        print("============================================")

    def _handlers(self) -> dict[str, Callable[[], None]]:
        return {
            "home": self.step_home,
            "clan_chat": self.step_clan_chat,
            "donation_request": self.step_donation_request,
            "donation_panel": self.step_donation_panel,
            "slot_colors": self.step_slot_colors,
            "grid": self.step_grid,
            "farm": self.step_farm,
            "optional": self.step_optional,
        }

    def step_home(self) -> None:
        print("=== ETAPA 1: TELA HOME ===\n")
        print("Vá para a tela INICIAL da sua vila (onde aparecem os edifícios).")
        print("NÃO abra o chat nem nenhum painel. Deixe a tela limpa.")
        _press_enter("Quando estiver na tela HOME, aperte Enter...")
        frame = self.capture.screenshot()
        h, w = frame.shape[:2]
        self.config.frame_width = w
        self.config.frame_height = h
        logger.info("Frame size: {}x{}", w, h)

        self._maybe_update_template(
            "home",
            "Ancora da tela HOME (algo fixo que aparece sempre na vila)",
            "ui/home.png",
            frame,
            optional=True,
        )

        print("\n--- Botão ABRIR CHAT (bolha `>` na lateral esquerda) ---")
        print(
            "Essa é a BOLHA/ABA `>` que abre o chat do clan.\n"
            "Fica na LATERAL ESQUERDA da tela da vila, geralmente no meio.\n"
            "Capture como IMAGEM: arraste um retângulo ao redor da bolha `>`.\n"
            "\n"
            "IMPORTANTE: Não confunda com a aba `<` (fechar chat) — essa é OUTRA coisa!"
        )
        has_tpl = self._has_template("open_chat")
        has_tap = self._has_tap("open_chat")
        if not has_tpl or prompt_yes_no("Atualizar imagem da bolha open_chat?"):
            coords, picked = self._pick_roi(
                "Arraste um retângulo ao redor da bolha de chat `>` na lateral esquerda da HOME", frame
            )
            self._save_template_from_frame(picked, coords, "ui/open_chat.png", "open_chat")
            x, y, bw, bh = coords
            self.config.tap_points["open_chat"] = [int(x + bw / 2), int(y + bh / 2)]
            logger.info("Saved open_chat template + tap at center")
        elif not has_tap or prompt_yes_no("Atualizar só o ponto de toque open_chat?"):
            pt = self._pick_point("Toque no CENTRO da bolha de chat `>` na lateral esquerda", frame)
            self.config.tap_points["open_chat"] = list(pt)
            logger.info("Saved tap point open_chat")
        else:
            _keeping("open_chat")

    def step_clan_chat(self) -> None:
        w, h = self._frame_size()
        print("=== ETAPA 2: CHAT DO CLAN ===\n")
        print("Abra o chat do clan (toque na bolha `>` da HOME).")
        print("NÃO abra o painel de doação — apenas veja as mensagens do chat.")
        _press_enter("Quando o chat estiver aberto, aperte Enter...")
        frame = self.capture.screenshot()

        self._maybe_update_roi(
            "chat_panel",
            "ROI de TODO o chat aberto (cima pra baixo, lateral esquerda)",
            w, h
        )
        self._maybe_update_roi(
            "chat_requests",
            "ROI dos PEDIDOS DE DOAÇÃO (onde aparece 'Precisamos de...' com botão Doar)",
            w, h
        )

        print(
            "\n--- Âncora clan_chat (algo fixo no chat que some quando painel abre) ---\n"
            "Escolha algo visível no chat aberto que FIQUE ESCONDIDO quando o painel de doação abre.\n"
            "Bom: aba 'Clan' selecionada, cabeçalho do chat, ícone de clan.\n"
            "Ruim: qualquer coisa coberta pelo popup de doação."
        )
        self._maybe_update_template(
            "clan_chat",
            "Âncora do chat (algo fixo que some quando painel de doação abre)",
            "ui/clan_chat.png",
            frame,
        )

        print(
            "\n--- Aba fechar chat (`<` laranja na borda DIREITA do chat aberto) ---\n"
            "Com o chat do clan ABERTO, toque na ABA LARANJA `<` na borda direita.\n"
            "Essa aba fecha o chat. NÃO confunda com a bolha `>` que ABRE o chat!"
        )
        has_close = self._has_tap("close_chat") or self._has_template("close_chat")
        if not has_close or prompt_yes_no("Atualizar controle close_chat?"):
            if prompt_yes_no("Capturar close_chat como template de imagem?"):
                coords, picked = self._pick_roi("Aba laranja `<` de fechar chat (borda direita)", frame)
                self._save_template_from_frame(picked, coords, "ui/close_chat.png", "close_chat")
            pt = self._pick_point("Toque no CENTRO da aba laranja `<` de fechar chat", frame)
            self.config.tap_points["close_chat"] = list(pt)
            logger.info("Saved tap point close_chat")
        else:
            _keeping("close_chat")

        print(
            "\n--- Ícone de EXCLAMAÇÃO `!` no topo ou rodapé do chat ---\n"
            "Quando tem pedido de doação acima ou abaixo da visão atual, aparece um `!`.\n"
            "Toque nele pula direto pro pedido. Capture UMA vez — o bot busca dos dois lados.\n"
            "Dica: role o chat até o `!` aparecer na borda, e capture."
        )
        self._maybe_update_template_after_setup(
            "chat_request_jump",
            "Ícone de exclamação `!` (topo ou rodapé do chat)",
            "ui/chat_request_jump.png",
            "Quando o `!` estiver visível no topo ou rodapé do chat, aperte Enter...",
            optional=True,
        )

        print(
            "\n--- Ícone seta pra BAIXO (legado) ---\n"
            "Se já capturou o `!` como chat_request_jump, pode PULAR.\n"
            "Caso role o chat pra CIMA até aparecer uma seta no rodapé, capture."
        )
        self._maybe_update_template_after_setup(
            "chat_scroll_down",
            "Ícone seta pra baixo no rodapé do chat (legado)",
            "ui/chat_scroll_down.png",
            "Quando a seta pra baixo estiver visível no rodapé, aperte Enter...",
            optional=True,
        )

    def step_donation_request(self) -> None:
        w, h = self._frame_size()
        print("=== ETAPA 3: BOTÃO DOAR ===\n")
        print("Mostre um PEDIDO DE DOAÇÃO no chat do clan com o botão DOAR visível.")
        print("Esse é o botão verde/amarelo 'Doar' que aparece DENTRO da mensagem do chat.")
        print("NÃO confunda com o painel de doação — aqui é só a mensagem do chat!")
        _press_enter("Quando o botão 'Doar' estiver visível no chat, aperte Enter...")
        frame = self.capture.screenshot()

        self._maybe_update_template(
            "donate_button",
            "Template do botão 'Doar' (verde/amarelo, dentro da mensagem do chat)",
            "ui/donate_button.png",
            frame,
        )
        self.config.rois.pop("request_header", None)

    def step_donation_panel(self) -> None:
        w, h = self._frame_size()
        print("=== ETAPA 4: PAINEL DE DOAÇÃO ===\n")
        print("Toque no botão 'Doar' (etapa anterior) para ABRIR o painel de doação.")
        print("Esse painel mostra as barras de tropas e magias que podem ser doadas.")
        _press_enter("Com o painel de doação ABERTO, aperte Enter...")
        frame = self.capture.screenshot()

        print(
            "\n--- Título 'Doar Recurso' (no topo do painel branco) ---\n"
            "Recorte bem de perto o texto 'Doar Recurso' no topo do painel branco.\n"
            "Opcional mas recomendado — ajuda a confirmar que o painel está aberto."
        )
        self._maybe_update_template(
            "donation_panel",
            "Título 'Doar Recurso' (topo do painel branco)",
            "ui/donation_panel.png",
            frame,
            optional=True,
        )

        print(
            "\nA barra de tropas contém tropas normais E máquinas de cerco na mesma área."
        )
        self._maybe_update_roi(
            "donation_troop_bar",
            "ROI da barra de TROPAS + CERCO (barra horizontal no meio do painel)",
            w, h
        )
        self._maybe_update_roi(
            "donation_spell_bar",
            "ROI da barra de MAGIAS (barra horizontal abaixo da tropa)",
            w, h
        )

        # Legacy — siege shared troop bar in current CoC UI
        self.config.rois.pop("donation_siege_bar", None)

        print(
            "\n--- Fechar painel de doação (toque FORA do painel branco) ---\n"
            "O CoC não tem botão X para fechar. Toque na área ESCURA (fundo do chat) para fechar."
        )
        self._maybe_update_tap_point(
            "tap_outside_donation",
            "Ponto na área ESCURA (fora do painel branco) para fechar o painel",
        )

    def step_slot_colors(self) -> None:
        print("=== ETAPA 5: CORES DOS SLOTS ===\n")
        print("Abra o painel de doação (toque em 'Doar' no chat).")
        print("Cada barra de tropa/magia tem uma cor: COLORIDA = pode receber doação, CINZA = não pode.")
        print("Para melhores resultados, mostre UM slot colorido E um cinza de cada tipo.")
        _press_enter("Com o painel de doação aberto, aperte Enter...")
        frame = self.capture.screenshot()

        self._maybe_update_color(
            "donatable_troop",
            "COR de uma barra de TROPA/CERCO COLORIDA (pode receber doação) — clique nela",
            frame,
        )
        self._maybe_update_color(
            "disabled_troop",
            "COR de uma barra de TROPA/CERCO CINZA (não pode receber) — clique nela",
            frame,
        )
        self._maybe_update_color(
            "donatable_spell",
            "COR de uma barra de MAGIA COLORIDA (pode receber doação) — clique nela",
            frame,
        )
        self._maybe_update_color(
            "disabled_spell",
            "COR de uma barra de MAGIA CINZA (não pode receber) — clique nela",
            frame,
        )

    def step_grid(self) -> None:
        if self.config.grid and not prompt_yes_no("Atualizar layout da grade?"):
            _keeping("grid")
            return

        print("=== ETAPA 6: GRADE DE SLOTS ===\n")
        print("Quantas colunas/linhas de slots são visíveis no painel de doação?")
        print("Exemplo: 2 linhas x 7 colunas de tropas visíveis antes de rolar.")
        print("\nRecomendado: use o seletor gráfico para desenhar a grade na tela:")
        print("  python scripts/pick_grid.py\n")
        if prompt_yes_no("Iniciar o seletor de grade agora (precisa de tela / RustDesk)?"):
            import subprocess
            import sys

            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[3] / "scripts" / "pick_grid.py")])
            return

        if not prompt_yes_no("Inserir contagem de colunas/linhas manualmente?"):
            print("Execute depois: python scripts/pick_grid.py")
            return

        current = self.config.grid or {}
        troop_bar = current.get("troop_bar", {})
        spell_bar = current.get("spell_bar", {})
        troop_cols_default = troop_bar.get("cols", 7)
        troop_rows_default = troop_bar.get("rows", 1)
        spell_cols_default = spell_bar.get("cols", 5)
        spell_rows_default = spell_bar.get("rows", 1)

        print("Insira o layout VISÍVEL dos slots nas barras do painel de doação (Enter mantém padrão).")
        print("Exemplo: 2 linhas x 7 colunas de tropas visíveis antes de rolar horizontalmente.")
        print("A barra de tropas inclui tropas normais e máquinas de cerco.")
        raw = input(f"Colunas tropas+cerco (slots por linha) [{troop_cols_default}]: ").strip()
        troop_cols = int(raw) if raw else troop_cols_default
        raw = input(f"Linhas tropas+cerco [{troop_rows_default}]: ").strip()
        troop_rows = int(raw) if raw else troop_rows_default
        raw = input(f"Colunas de magias (slots por linha) [{spell_cols_default}]: ").strip()
        spell_cols = int(raw) if raw else spell_cols_default
        raw = input(f"Linhas de magias [{spell_rows_default}]: ").strip()
        spell_rows = int(raw) if raw else spell_rows_default

        self.config.grid = {
            "troop_bar": {"cols": troop_cols, "rows": troop_rows},
            "spell_bar": {"cols": spell_cols, "rows": spell_rows},
        }

    def step_farm(self) -> None:
        """
        Calibrar toques de farm de Batalha sem rank.

        Deixe seu exercito de electro dragon como o preset ativo antes de ativar o farm.
        """
        w, h = self._frame_size()
        print(
            "\n=== ETAPA 7: FARM / ATAQUE SEM RANK ===\n"
            "IMPORTANTE: Deixe seu exército de electro dragon como o preset ATIVO.\n"
            "O bot não treina tropas nem troca exércitos — só usa o que já está pronto.\n"
        )

        print("Vá para a tela HOME da sua vila (chat fechado).")
        _press_enter("Quando estiver na HOME, aperte Enter...")
        frame = self.capture.screenshot()

        print("\n--- Botão 'Atacar!' (canto inferior esquerdo da HOME) ---")
        has_attack = self._has_tap("attack_button") or self._has_template("attack_button")
        if not has_attack or prompt_yes_no("Atualizar attack_button?"):
            if prompt_yes_no("Capturar attack_button como template de imagem?"):
                coords, picked = self._pick_roi("Botão 'Atacar!' (inferior esquerdo da HOME)", frame)
                self._save_template_from_frame(picked, coords, "ui/attack_button.png", "attack_button")
            pt = self._pick_point("Toque no CENTRO do botão 'Atacar!'", frame)
            self.config.tap_points["attack_button"] = list(pt)
            logger.info("Saved tap point attack_button")
        else:
            _keeping("attack_button")

        print(
            "\nAbra o menu Atacar para ver Classificado vs Batalha (sem rank).\n"
            "Toque em 'Atacar!' você mesmo, depois aperte Enter."
        )
        _press_enter("Com o menu Atacar aberto, aperte Enter...")
        frame = self.capture.screenshot()

        print("\n--- Batalha sem rank (NAO 'Classificado') ---")
        has_battle = self._has_tap("unranked_battle") or self._has_template("unranked_battle")
        if not has_battle or prompt_yes_no("Atualizar unranked_battle?"):
            if prompt_yes_no("Capturar unranked_battle como template de imagem?"):
                coords, picked = self._pick_roi("Botão 'Batalha' (sem rank, NÃO 'Classificado')", frame)
                self._save_template_from_frame(
                    picked, coords, "ui/unranked_battle.png", "unranked_battle"
                )
            pt = self._pick_point("Toque no CENTRO da 'Batalha' sem rank", frame)
            self.config.tap_points["unranked_battle"] = list(pt)
            logger.info("Saved tap point unranked_battle")
        else:
            _keeping("unranked_battle")

        print(
            "\nSe 'Encontrar Oponente' for um botão separado após 'Batalha', mostre essa tela.\n"
            "Caso contrário, pule (a Batalha pode iniciar busca imediatamente)."
        )
        if prompt_yes_no("Calibrar 'Encontrar Oponente' / próximo botão?"):
            _press_enter("Com 'Encontrar Oponente' visível, aperte Enter...")
            frame = self.capture.screenshot()
            if prompt_yes_no("Capturar find_match como template de imagem?"):
                coords, picked = self._pick_roi("Botão 'Encontrar Oponente'", frame)
                self._save_template_from_frame(picked, coords, "ui/find_match.png", "find_match")
            pt = self._pick_point("Toque no CENTRO de 'Encontrar Oponente'", frame)
            self.config.tap_points["find_match"] = list(pt)
            logger.info("Saved tap point find_match")
        elif self._has_tap("find_match") or self._has_template("find_match"):
            _keeping("find_match")

        print(
            "\n--- Voltar pra vila (após um ataque finalizado) ---\n"
            "Finalize ou espere qualquer tela de fim de batalha que mostre 'Voltar' / 'OK'.\n"
            "Ou pule e defina um ponto onde esse botão normalmente aparece."
        )
        if prompt_yes_no("Atualizar return_home agora (recomendado)?"):
            _press_enter("Na tela de resultado da batalha, aperte Enter...")
            frame = self.capture.screenshot()
            if prompt_yes_no("Capturar return_home / battle_end como template de imagem?"):
                coords, picked = self._pick_roi("Botão 'Voltar' / 'OK' da tela de resultado", frame)
                self._save_template_from_frame(picked, coords, "ui/return_home.png", "return_home")
                self.config.templates["battle_end"] = self.config.templates.get(
                    "return_home", "ui/return_home.png"
                )
            pt = self._pick_point("Toque no CENTRO do botão 'Voltar' / 'OK'", frame)
            self.config.tap_points["return_home"] = list(pt)
            logger.info("Saved tap point return_home")
        elif not self._has_tap("return_home"):
            # Sensible default near bottom-center for end-of-battle UI.
            self.config.tap_points["return_home"] = [int(w * 0.50), int(h * 0.85)]
            logger.info(
                "Saved default return_home tap ({}, {}) — recalibrate if needed",
                self.config.tap_points["return_home"][0],
                self.config.tap_points["return_home"][1],
            )
        else:
            _keeping("return_home")

        # deploy_strip ROI removed — bot pans from center with fixed swipes instead.
        if "deploy_strip" in self.config.rois:
            del self.config.rois["deploy_strip"]
            logger.info("Removed obsolete deploy_strip ROI (not used anymore)")

        print(
            "\n--- Slots da barra de exército (Opcional mas recomendado) ---\n"
            "Em uma tela de BATALHA com seu exército visível na barra inferior:\n"
            "  • Carta de electro dragon (primeira tropa)\n"
            "  • Carta de máquina de cerco\n"
            "  • Carta de magia furia\n"
            "  • Cada uma das 4 cartas de herói (esquerda → direita)\n"
            "Pule para usar as posições padrão do sistema."
        )
        if prompt_yes_no("Calibrar toques da barra de exército (e-drag, cerco, furia, heróis) agora?"):
            print("Abra qualquer batalha para que a barra de exército fique visível, depois aperte Enter.")
            _press_enter("Com a barra de exército visível, aperte Enter...")
            frame = self.capture.screenshot()
            pt = self._pick_point("CENTRO da carta de electro dragon (primeira tropa)", frame)
            self.config.tap_points["edrag_slot"] = list(pt)
            logger.info("Saved tap point edrag_slot")
            if prompt_yes_no("Calibrar siege_slot?"):
                frame = self.capture.screenshot()
                pt = self._pick_point("CENTRO da carta de máquina de cerco", frame)
                self.config.tap_points["siege_slot"] = list(pt)
                logger.info("Saved tap point siege_slot")
            if prompt_yes_no("Calibrar rage_slot?"):
                frame = self.capture.screenshot()
                pt = self._pick_point("CENTRO da carta de magia furia", frame)
                self.config.tap_points["rage_slot"] = list(pt)
                logger.info("Saved tap point rage_slot")
            for i in range(1, 5):
                if not prompt_yes_no(f"Calibrar hero_{i}?"):
                    break
                frame = self.capture.screenshot()
                pt = self._pick_point(f"CENTRO da carta de herói #{i} (esquerda para direita)", frame)
                self.config.tap_points[f"hero_{i}"] = list(pt)
                logger.info("Saved tap point hero_{}", i)
        else:
            for key in ("edrag_slot", "siege_slot", "rage_slot", "hero_1", "hero_2", "hero_3", "hero_4"):
                if key in self.config.tap_points:
                    _keeping(key)

        print(
            "\nCalibração de farm salva. Ative o farm nas Configurações após verificar.\n"
            "Mantenha electro dragons como o preset de exército ativo (e-drags + heróis + furia)."
        )

    def step_optional(self) -> None:
        print("=== ETAPA 8: UI OPCIONAL ===\n")
        print("Essas capturas são OPCIONAIS — ajudam o bot a detectar telas de loading e popups.")

        self._maybe_update_template_after_setup(
            "loading",
            "Tela de loading (tela preta/azul ao abrir o CoC)",
            "ui/loading.png",
            "Reabra o CoC para mostrar a tela de loading, depois aperte Enter...",
            optional=True,
        )

        self._maybe_update_template_after_setup(
            "popup_dismiss",
            "Botão 'X' ou 'Fechar' de popups/events",
            "ui/popup_dismiss.png",
            "Mostre um popup/evento dispensável, depois aperte Enter...",
            optional=True,
        )


def main() -> None:
    """CLI entry para calibracao (usado por scripts/calibrate.py e coc-bot-calibrate)."""
    setup_logging(debug=False)
    parser = argparse.ArgumentParser(
        description="Calibrar bot de doacao CoC (execucao completa ou etapas individuais)",
    )
    parser.add_argument(
        "--step",
        action="append",
        dest="steps",
        choices=STEP_IDS,
        metavar="STEP",
        help=f"Rodar uma etapa so (pode repetir). Opcoes: {', '.join(STEP_IDS)}",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Rodar todas as etapas em ordem",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Listar etapas e se estao configuradas",
    )
    args = parser.parse_args()

    wizard = CalibrationWizard()
    if args.list:
        print_step_menu(wizard.step_status())
    elif args.steps:
        wizard.run_steps(args.steps)
    elif args.all:
        wizard.run_steps(list(STEP_IDS))
    else:
        wizard.run_interactive()


if __name__ == "__main__":
    main()
