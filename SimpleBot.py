from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Callable, Iterable

try:
    import cv2
    import numpy as np
    import psutil
    import pyautogui
except ImportError as exc:  # A friendly error is more useful than a long traceback.
    missing_package = getattr(exc, "name", "dependency")
    raise SystemExit(
        f"The {missing_package} package is not installed. Run: "
        f'"{sys.executable}" -m pip install -r requirements.txt'
    ) from exc


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "bot_config.json"
TEMPLATE_DIR = APP_DIR / "templates"
LOG_PATH = APP_DIR / "hs_bot.log"
DEBUG_IMAGE_PATH = APP_DIR / "debug_last.png"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
LOGGER = logging.getLogger("hs-bot")


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc


@dataclass(frozen=True)
class ClientArea:
    left: int
    top: int
    width: int
    height: int

    def point(self, relative_point: Iterable[float]) -> tuple[int, int]:
        x_ratio, y_ratio = relative_point
        return (
            self.left + round(self.width * float(x_ratio)),
            self.top + round(self.height * float(y_ratio)),
        )

    @property
    def region(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height


class HearthstoneWindow:
    """Small Win32 wrapper; no window-management dependency is required."""

    SW_RESTORE = 9

    def __init__(self, title_fragments: list[str], process_names: list[str]) -> None:
        self._title_fragments = tuple(value.casefold() for value in title_fragments)
        self._process_names = {value.casefold() for value in process_names}
        self._user32 = ctypes.windll.user32 if os.name == "nt" else None
        if self._user32 is not None:
            hwnd = ctypes.wintypes.HWND
            self._user32.IsWindowVisible.argtypes = [hwnd]
            self._user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
            self._user32.IsIconic.argtypes = [hwnd]
            self._user32.IsIconic.restype = ctypes.wintypes.BOOL
            self._user32.GetWindowTextLengthW.argtypes = [hwnd]
            self._user32.GetWindowTextLengthW.restype = ctypes.c_int
            self._user32.GetWindowTextW.argtypes = [hwnd, ctypes.c_wchar_p, ctypes.c_int]
            self._user32.GetWindowTextW.restype = ctypes.c_int
            self._user32.GetWindowThreadProcessId.argtypes = [
                hwnd,
                ctypes.POINTER(ctypes.wintypes.DWORD),
            ]
            self._user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
            self._user32.AttachThreadInput.argtypes = [
                ctypes.wintypes.DWORD,
                ctypes.wintypes.DWORD,
                ctypes.wintypes.BOOL,
            ]
            self._user32.AttachThreadInput.restype = ctypes.wintypes.BOOL
            self._user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
            self._user32.BringWindowToTop.argtypes = [hwnd]
            self._user32.SetForegroundWindow.argtypes = [hwnd]
            self._user32.GetForegroundWindow.restype = hwnd
            self._user32.GetClientRect.argtypes = [
                hwnd,
                ctypes.POINTER(ctypes.wintypes.RECT),
            ]
            self._user32.GetClientRect.restype = ctypes.wintypes.BOOL
            self._user32.ClientToScreen.argtypes = [
                hwnd,
                ctypes.POINTER(ctypes.wintypes.POINT),
            ]
            self._user32.ClientToScreen.restype = ctypes.wintypes.BOOL

    def find(self) -> int | None:
        if self._user32 is None:
            return None

        matches: list[int] = []
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd: int, _lparam: int) -> bool:
            if not self._user32.IsWindowVisible(hwnd):
                return True
            length = self._user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.casefold()
            if any(fragment in title for fragment in self._title_fragments):
                process_id = ctypes.wintypes.DWORD()
                self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                try:
                    process_name = psutil.Process(process_id.value).name().casefold()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return True
                if process_name in self._process_names:
                    matches.append(int(hwnd))
                    return False
            return True

        callback = enum_proc_type(visit)
        self._user32.EnumWindows(callback, 0)
        return matches[0] if matches else None

    def activate(self, hwnd: int) -> bool:
        if self._user32 is None:
            return False
        foreground = self._user32.GetForegroundWindow()
        if foreground is not None and int(foreground) == int(hwnd):
            return True
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, self.SW_RESTORE)
            time.sleep(0.5)

        foreground = self._user32.GetForegroundWindow()
        foreground_thread = (
            self._user32.GetWindowThreadProcessId(foreground, None)
            if foreground is not None
            else 0
        )
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = False
        try:
            if foreground_thread and foreground_thread != current_thread:
                attached = bool(
                    self._user32.AttachThreadInput(current_thread, foreground_thread, True)
                )
            self._user32.BringWindowToTop(hwnd)
            self._user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                self._user32.AttachThreadInput(current_thread, foreground_thread, False)
        current_foreground = self._user32.GetForegroundWindow()
        return current_foreground is not None and int(current_foreground) == int(hwnd)

    def client_area(self, hwnd: int) -> ClientArea | None:
        if self._user32 is None:
            return None

        rect = ctypes.wintypes.RECT()
        origin = ctypes.wintypes.POINT(0, 0)
        if not self._user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        if not self._user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 640 or height < 360:
            return None
        return ClientArea(int(origin.x), int(origin.y), width, height)


class TemplateMatcher:
    def __init__(self, directory: Path, confidence: float) -> None:
        self._directory = directory
        self._confidence = confidence
        self._available = True

    def path_for(self, name: str) -> Path | None:
        for suffix in ("png", "jpg", "jpeg"):
            candidate = self._directory / f"{name}.{suffix}"
            if candidate.is_file():
                return candidate
        return None

    def installed(self, name: str) -> bool:
        return self._available and self.path_for(name) is not None

    def locate(self, name: str, area: ClientArea):
        path = self.path_for(name)
        if path is None:
            return None
        try:
            return pyautogui.locateOnScreen(
                str(path),
                confidence=self._confidence,
                grayscale=True,
                region=area.region,
            )
        except pyautogui.ImageNotFoundException:
            return None
        except NotImplementedError as exc:
            self._available = False
            LOGGER.warning("Template matching has been disabled: %s", exc)
            return None
        except (OSError, ValueError) as exc:
            LOGGER.warning("Could not check template %s: %s", name, exc)
            return None

    def click_if_found(
        self,
        name: str,
        area: ClientArea,
        hold_seconds: float,
        move_duration: float,
    ) -> bool:
        location = self.locate(name, area)
        if location is None:
            return False
        center = pyautogui.center(location)
        pyautogui.moveTo(center.x, center.y, duration=move_duration)
        pyautogui.mouseDown(button="left")
        try:
            time.sleep(hold_seconds)
        finally:
            pyautogui.mouseUp(button="left")
        LOGGER.info("Clicked an element matched by template: %s", name)
        return True


@dataclass(frozen=True)
class VisionItem:
    center: tuple[int, int]
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class VisionSnapshot:
    board_visible: bool
    result_visible: bool
    mulligan_visible: bool
    play_visible: bool
    turn_active: bool
    playable_cards: tuple[VisionItem, ...]
    attackers: tuple[VisionItem, ...]


class ScreenVision:
    """Recognizes UI states from color highlights without reading game memory."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def capture(self, area: ClientArea) -> np.ndarray:
        screenshot = pyautogui.screenshot(region=area.region)
        return cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _roi_pixels(
        frame: np.ndarray, roi: Iterable[float]
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        height, width = frame.shape[:2]
        left, top, right, bottom = [float(value) for value in roi]
        x1 = max(0, min(width - 1, round(width * left)))
        y1 = max(0, min(height - 1, round(height * top)))
        x2 = max(x1 + 1, min(width, round(width * right)))
        y2 = max(y1 + 1, min(height, round(height * bottom)))
        return frame[y1:y2, x1:x2], (x1, y1, x2, y2)

    @staticmethod
    def _hsv_mask(image: np.ndarray, hsv_range: dict) -> np.ndarray:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        lower = np.asarray(hsv_range["lower"], dtype=np.uint8)
        upper = np.asarray(hsv_range["upper"], dtype=np.uint8)
        return cv2.inRange(hsv, lower, upper)

    def _color_ratio(self, frame: np.ndarray, roi_name: str, color_name: str) -> float:
        roi, _bounds = self._roi_pixels(frame, self.config[roi_name])
        if roi.size == 0:
            return 0.0
        mask = self._hsv_mask(roi, self.config[color_name])
        return float(cv2.countNonZero(mask)) / float(mask.shape[0] * mask.shape[1])

    def _low_saturation_ratio(self, frame: np.ndarray, roi_name: str) -> float:
        roi, _bounds = self._roi_pixels(frame, self.config[roi_name])
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        threshold = int(self.config["result_gray_saturation_max"])
        return float(np.mean(hsv[:, :, 1] <= threshold))

    def _green_items(
        self,
        frame: np.ndarray,
        area: ClientArea,
        roi_name: str,
    ) -> tuple[VisionItem, ...]:
        roi, (offset_x, offset_y, _right, _bottom) = self._roi_pixels(
            frame, self.config[roi_name]
        )
        mask = self._hsv_mask(roi, self.config["green_hsv"])
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8), iterations=1)
        contours, _hierarchy = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        frame_height, frame_width = frame.shape[:2]
        min_width_key = (
            "hand_item_min_width_ratio"
            if roi_name == "hand_roi"
            else "board_item_min_width_ratio"
        )
        min_width = frame_width * float(self.config[min_width_key])
        max_width = frame_width * float(self.config["item_max_width_ratio"])
        min_height = frame_height * float(self.config["item_min_height_ratio"])
        max_height = frame_height * float(self.config["item_max_height_ratio"])
        min_area = frame_width * frame_height * float(self.config["item_min_area_ratio"])
        candidates: list[VisionItem] = []
        generated_hand_items: list[VisionItem] = []
        wide_hand_spans: list[tuple[int, int]] = []

        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            contour_area = cv2.contourArea(contour)
            valid_height_and_area = (
                min_height <= height <= max_height and contour_area >= min_area
            )
            if (
                roi_name == "hand_roi"
                and valid_height_and_area
                and max_width < width <= frame_width * 0.4
            ):
                absolute_left = area.left + offset_x + x
                margin = frame_width * float(self.config["hand_group_margin_ratio"])
                spacing = frame_width * float(self.config["hand_card_spacing_ratio"])
                usable_width = max(0.0, width - 2 * margin)
                card_count = max(1, round(usable_width / max(1.0, spacing)) + 1)
                first_center = absolute_left + margin
                last_center = absolute_left + width - margin
                if card_count == 1:
                    centers = [absolute_left + width / 2]
                else:
                    centers = [
                        first_center
                        + (last_center - first_center) * index / (card_count - 1)
                        for index in range(card_count)
                    ]
                source_y = area.top + round(
                    area.height * float(self.config["hand_source_y_ratio"])
                )
                debug_width = round(
                    frame_width * float(self.config["hand_card_width_ratio"])
                )
                for center_x in centers:
                    generated_hand_items.append(
                        VisionItem(
                            center=(round(center_x), source_y),
                            box=(
                                round(center_x - debug_width / 2),
                                area.top + offset_y + y,
                                debug_width,
                                height,
                            ),
                        )
                    )
                wide_hand_spans.append((absolute_left, absolute_left + width))
                continue
            if not (
                min_width <= width <= max_width
                and valid_height_and_area
            ):
                continue
            absolute_box = (
                area.left + offset_x + x,
                area.top + offset_y + y,
                width,
                height,
            )
            candidates.append(
                VisionItem(
                    center=(
                        absolute_box[0] + width // 2,
                        (
                            area.top
                            + round(
                                area.height
                                * float(self.config["hand_source_y_ratio"])
                            )
                            if roi_name == "hand_roi"
                            else absolute_box[1] + height // 2
                        ),
                    ),
                    box=absolute_box,
                )
            )

        if generated_hand_items:
            candidates = [
                item
                for item in candidates
                if not any(left <= item.center[0] <= right for left, right in wide_hand_spans)
            ]
            candidates.extend(generated_hand_items)

        # Nearby fragments of one glow are collapsed to one click target.
        candidates.sort(key=lambda item: item.center[0])

        if roi_name == "hand_roi":
            changed = True
            while changed:
                changed = False
                compacted: list[VisionItem] = []
                consumed: set[int] = set()
                for first_index, first in enumerate(candidates):
                    if first_index in consumed:
                        continue
                    merged_item = first
                    for second_index in range(first_index + 1, len(candidates)):
                        if second_index in consumed:
                            continue
                        second = candidates[second_index]
                        ax, ay, aw, ah = merged_item.box
                        bx, by, bw, bh = second.box
                        horizontal_overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                        vertical_gap = max(0, max(ay, by) - min(ay + ah, by + bh))
                        overlap_ratio = horizontal_overlap / max(1, min(aw, bw))
                        if (
                            overlap_ratio >= 0.45
                            and vertical_gap <= frame_height * 0.03
                        ):
                            union_x = min(ax, bx)
                            union_y = min(ay, by)
                            union_right = max(ax + aw, bx + bw)
                            union_bottom = max(ay + ah, by + bh)
                            union_width = union_right - union_x
                            union_height = union_bottom - union_y
                            merged_item = VisionItem(
                                center=(
                                    union_x + union_width // 2,
                                    union_y + union_height // 2,
                                ),
                                box=(union_x, union_y, union_width, union_height),
                            )
                            consumed.add(second_index)
                            changed = True
                    compacted.append(merged_item)
                candidates = sorted(compacted, key=lambda item: item.center[0])

        # A green minion aura is often split into left and right vertical contours.
        # Pair only narrow, vertically overlapping neighbours; complete minions remain
        # separate even when several of them stand next to one another.
        if roi_name == "own_board_roi":
            paired: list[VisionItem] = []
            index = 0
            while index < len(candidates):
                first = candidates[index]
                if index + 1 < len(candidates):
                    second = candidates[index + 1]
                    first_x, first_y, first_width, first_height = first.box
                    second_x, second_y, second_width, second_height = second.box
                    horizontal_gap = second_x - (first_x + first_width)
                    overlap = max(
                        0,
                        min(first_y + first_height, second_y + second_height)
                        - max(first_y, second_y),
                    )
                    overlap_ratio = overlap / max(1, min(first_height, second_height))
                    both_narrow = max(first_width, second_width) <= frame_width * 0.04
                    if (
                        both_narrow
                        and -5 <= horizontal_gap <= frame_width * 0.025
                        and overlap_ratio >= 0.55
                    ):
                        union_x = min(first_x, second_x)
                        union_y = min(first_y, second_y)
                        union_right = max(
                            first_x + first_width, second_x + second_width
                        )
                        union_bottom = max(
                            first_y + first_height, second_y + second_height
                        )
                        union_width = union_right - union_x
                        union_height = union_bottom - union_y
                        paired.append(
                            VisionItem(
                                center=(
                                    union_x + union_width // 2,
                                    union_y + union_height // 2,
                                ),
                                box=(union_x, union_y, union_width, union_height),
                            )
                        )
                        index += 2
                        continue
                paired.append(first)
                index += 1
            candidates = paired

        merged: list[VisionItem] = []
        merge_distance = frame_width * float(self.config["item_merge_distance_ratio"])
        for candidate in candidates:
            if merged and abs(candidate.center[0] - merged[-1].center[0]) < merge_distance:
                previous = merged[-1]
                previous_area = previous.box[2] * previous.box[3]
                candidate_area = candidate.box[2] * candidate.box[3]
                if candidate_area > previous_area:
                    merged[-1] = candidate
            else:
                merged.append(candidate)
        return tuple(merged)

    def green_ratio_at_point(
        self,
        frame: np.ndarray,
        relative_point: Iterable[float],
        radius: Iterable[float],
    ) -> float:
        x, y = [float(value) for value in relative_point]
        radius_x, radius_y = [float(value) for value in radius]
        roi = (x - radius_x, y - radius_y, x + radius_x, y + radius_y)
        pixels, _bounds = self._roi_pixels(frame, roi)
        mask = self._hsv_mask(pixels, self.config["green_hsv"])
        return float(cv2.countNonZero(mask)) / float(mask.shape[0] * mask.shape[1])

    def analyze(self, frame: np.ndarray, area: ClientArea) -> VisionSnapshot:
        blue_ratio = self._color_ratio(frame, "play_roi", "blue_hsv")
        mulligan_blue = self._color_ratio(frame, "mulligan_roi", "blue_hsv")
        end_gold = self._color_ratio(frame, "end_turn_roi", "gold_hsv")
        end_green = self._color_ratio(frame, "end_turn_roi", "green_hsv")
        result_gray = (
            self._low_saturation_ratio(frame, "result_left_roi")
            + self._low_saturation_ratio(frame, "result_right_roi")
        ) / 2.0
        result_visible = result_gray >= float(self.config["result_gray_ratio"])
        board_visible = max(end_gold, end_green) >= float(
            self.config["board_button_color_ratio"]
        )
        mulligan_visible = (
            not result_visible
            and not board_visible
            and mulligan_blue >= float(self.config["mulligan_color_ratio"])
        )
        return VisionSnapshot(
            board_visible=board_visible,
            result_visible=result_visible,
            mulligan_visible=mulligan_visible,
            # The mana tray is also blue; never call it Play after the board is proven.
            play_visible=(
                not board_visible
                and not result_visible
                and not mulligan_visible
                and blue_ratio >= float(self.config["play_color_ratio"])
            ),
            turn_active=end_green
            >= float(self.config["end_turn_green_ratio"]),
            playable_cards=self._green_items(frame, area, "hand_roi"),
            attackers=self._green_items(frame, area, "own_board_roi"),
        )

    def save_debug(
        self,
        frame: np.ndarray,
        area: ClientArea,
        snapshot: VisionSnapshot,
    ) -> None:
        if not bool(self.config.get("save_debug_image", True)):
            return
        debug = frame.copy()
        for item, label, color in (
            *((item, "CARD", (0, 255, 0)) for item in snapshot.playable_cards),
            *((item, "ATTACK", (0, 220, 255)) for item in snapshot.attackers),
        ):
            x, y, width, height = item.box
            local_x = x - area.left
            local_y = y - area.top
            cv2.rectangle(
                debug,
                (local_x, local_y),
                (local_x + width, local_y + height),
                color,
                3,
            )
            cv2.putText(
                debug,
                label,
                (local_x, max(20, local_y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
            )
        state_text = (
            f"BOARD={int(snapshot.board_visible)} "
            f"RESULT={int(snapshot.result_visible)} "
            f"MULLIGAN={int(snapshot.mulligan_visible)} "
            f"PLAY={int(snapshot.play_visible)} "
            f"TURN={int(snapshot.turn_active)} "
            f"CARDS={len(snapshot.playable_cards)} ATTACKERS={len(snapshot.attackers)}"
        )
        cv2.putText(
            debug,
            state_text,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        cv2.imwrite(str(DEBUG_IMAGE_PATH), debug)


class HearthstoneBot:
    def __init__(self, config: dict, on_state_change: Callable[[], None]) -> None:
        self.config = config
        self._on_state_change = on_state_change
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._game_state = "Game is not running"
        self._bot_state = "Bot is stopped"
        self._window = HearthstoneWindow(
            config["game"]["window_titles"], config["game"]["process_names"]
        )
        self._matcher = TemplateMatcher(
            TEMPLATE_DIR, float(config["behavior"]["template_confidence"])
        )
        self._vision = ScreenVision(config["vision"])
        self._last_launch_attempt = 0.0
        self._next_actions_at = 0.0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def states(self) -> tuple[str, str]:
        with self._state_lock:
            return self._game_state, self._bot_state

    def _set_states(self, game: str | None = None, bot: str | None = None) -> None:
        with self._state_lock:
            if game is not None:
                self._game_state = game
            if bot is not None:
                self._bot_state = bot
        self._on_state_change()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._next_actions_at = 0.0
        self._thread = threading.Thread(target=self._run, name="hs-bot", daemon=True)
        self._thread.start()
        self._set_states(bot="Bot is running")

    def stop(self) -> None:
        self._stop_event.set()
        self._set_states(bot="Bot is stopped")

    def observe_game(self) -> None:
        """Refresh the GUI indicator without focusing or changing the game window."""
        if self.running:
            return
        if self._process_running() and self._window.find() is not None:
            self._set_states(game="Game is running")
        else:
            self._set_states(game="Game is not running")

    def join(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout)

    def _sleep(self, seconds: float) -> bool:
        """True means the bot was stopped during the wait."""
        return self._stop_event.wait(max(0.0, seconds))

    def _process_running(self) -> bool:
        wanted = {name.casefold() for name in self.config["game"]["process_names"]}
        for process in psutil.process_iter(["name"]):
            try:
                name = (process.info.get("name") or "").casefold()
                if name in wanted:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def _launch_game(self) -> None:
        game_config = self.config["game"]
        executable = str(game_config.get("executable", "")).strip()
        try:
            if executable:
                executable_path = Path(executable).expanduser()
                if not executable_path.is_file():
                    raise FileNotFoundError(executable_path)
                subprocess.Popen([str(executable_path)])
                LOGGER.info("Started Hearthstone: %s", executable_path)
            elif os.name == "nt":
                os.startfile(game_config.get("launch_uri", "battlenet://WTCG"))
                LOGGER.info("Sent the launch command through Battle.net")
            else:
                raise RuntimeError("automatic launch is supported only on Windows")
        except (OSError, RuntimeError) as exc:
            LOGGER.error("Could not start the game: %s", exc)
            self._set_states(game="Game launch failed — see hs_bot.log")

    def _ensure_game(self) -> tuple[int, ClientArea] | None:
        if not self._process_running():
            self._set_states(game="Game is not running — starting it...")
            retry = float(self.config["behavior"]["launch_retry_seconds"])
            if time.monotonic() - self._last_launch_attempt >= retry:
                self._last_launch_attempt = time.monotonic()
                self._launch_game()
            return None

        hwnd = self._window.find()
        if hwnd is None:
            self._set_states(game="Game is starting...")
            return None
        if not self._window.activate(hwnd):
            self._set_states(game="Could not bring the game to the foreground")
            return None
        area = self._window.client_area(hwnd)
        if area is None:
            self._set_states(game="Could not determine the game area")
            return None
        self._set_states(game="Game is running")
        return hwnd, area

    def _point(self, area: ClientArea, name: str) -> tuple[int, int]:
        return area.point(self.config["points"][name])

    def _click(self, point: tuple[int, int], hold_seconds: float | None = None) -> None:
        if self._stop_event.is_set():
            return
        behavior = self.config["behavior"]
        hold = (
            float(hold_seconds)
            if hold_seconds is not None
            else float(behavior["click_hold_seconds"])
        )
        pyautogui.moveTo(*point, duration=float(behavior["move_duration"]))
        pyautogui.mouseDown(button="left")
        try:
            self._sleep(hold)
        finally:
            # Never leave the mouse button held when Ctrl+C is pressed mid-click.
            pyautogui.mouseUp(button="left")
        self._sleep(float(self.config["behavior"]["action_delay"]))

    def _drag(self, source: tuple[int, int], target: tuple[int, int]) -> None:
        if self._stop_event.is_set():
            return
        behavior = self.config["behavior"]
        pyautogui.moveTo(*source, duration=float(behavior["move_duration"]))
        pyautogui.mouseDown(button="left")
        try:
            if self._sleep(float(behavior["drag_hold_before_seconds"])):
                return
            pyautogui.moveTo(*target, duration=float(behavior["drag_duration"]))
            self._sleep(float(behavior["drag_hold_after_seconds"]))
        finally:
            pyautogui.mouseUp(button="left")
        self._sleep(float(behavior["action_delay"]))

    def _handle_screen_buttons(self, area: ClientArea) -> str | None:
        behavior = self.config["behavior"]
        for name in ("disconnect_ok", "reconnect", "continue", "play", "mulligan_confirm"):
            if self._matcher.click_if_found(
                name,
                area,
                hold_seconds=float(behavior["navigation_click_hold_seconds"]),
                move_duration=float(behavior["move_duration"]),
            ):
                self._sleep(float(self.config["behavior"]["screen_change_wait"]))
                return name
        return None

    @staticmethod
    def _item_near(
        items: Iterable[VisionItem],
        point: tuple[int, int],
        max_distance: float,
    ) -> bool:
        return any(
            abs(item.center[0] - point[0]) <= max_distance
            and abs(item.center[1] - point[1]) <= max_distance
            for item in items
        )

    def _vision_snapshot(self, area: ClientArea) -> tuple[np.ndarray, VisionSnapshot]:
        frame = self._vision.capture(area)
        snapshot = self._vision.analyze(frame, area)
        self._vision.save_debug(frame, area, snapshot)
        return frame, snapshot

    def _play_highlighted_cards(self, area: ClientArea) -> None:
        vision_config = self.config["vision"]
        failed: list[tuple[int, int]] = []
        max_attempts = int(vision_config["max_cards_per_turn"])
        failure_distance = area.width * float(vision_config["failure_distance_ratio"])
        board = self._point(area, "board_play")

        for _attempt in range(max_attempts):
            if self._stop_event.is_set():
                return
            _frame, snapshot = self._vision_snapshot(area)
            available = [
                item
                for item in snapshot.playable_cards
                if not any(
                    abs(item.center[0] - failed_point[0]) <= failure_distance
                    for failed_point in failed
                )
            ]
            if not available:
                return

            # Explicitly play left-to-right; the left card is never postponed.
            card = min(available, key=lambda item: item.center[0])
            before_count = len(snapshot.playable_cards)
            self._set_states(bot=f"Bot is running: playing a card ({before_count})")
            LOGGER.info("Dragging a card: %s -> %s", card.center, board)
            self._drag(card.center, board)
            self._sleep(float(vision_config["after_card_wait_seconds"]))

            _after_frame, after = self._vision_snapshot(area)
            unchanged = len(after.playable_cards) == before_count and self._item_near(
                after.playable_cards, card.center, failure_distance
            )
            if unchanged:
                failed.append(card.center)
                LOGGER.info(
                    "Card position did not change after dragging; trying the next card"
                )
            else:
                failed.clear()

    def _attack_highlighted_characters(self, area: ClientArea) -> None:
        vision_config = self.config["vision"]
        failed: list[tuple[int, int]] = []
        failure_distance = area.width * float(vision_config["failure_distance_ratio"])
        max_attempts = int(vision_config["max_attacks_per_turn"])
        enemy_hero = self._point(area, "enemy_hero")

        for _attempt in range(max_attempts):
            if self._stop_event.is_set():
                return
            _frame, snapshot = self._vision_snapshot(area)
            available = [
                item
                for item in snapshot.attackers
                if not any(
                    abs(item.center[0] - failed_point[0]) <= failure_distance
                    for failed_point in failed
                )
            ]
            if not available:
                return
            attacker = min(available, key=lambda item: item.center[0])
            self._set_states(bot=f"Bot is running: attacking ({len(available)})")
            self._drag(attacker.center, enemy_hero)
            self._sleep(float(vision_config["after_attack_wait_seconds"]))

            _after_frame, after = self._vision_snapshot(area)
            if not self._item_near(after.attackers, attacker.center, failure_distance):
                failed.clear()
                continue
            # Do not sweep random target positions: one failed face attack is skipped.
            failed.append(attacker.center)

    def _take_visual_turn(
        self,
        area: ClientArea,
        initial_frame: np.ndarray,
        initial_snapshot: VisionSnapshot,
    ) -> None:
        self._set_states(bot="Bot is running: my turn")
        if initial_snapshot.playable_cards:
            self._play_highlighted_cards(area)
        if self._stop_event.is_set():
            return

        frame, after_cards = self._vision_snapshot(area)
        hero_power_ratio = self._vision.green_ratio_at_point(
            frame,
            self.config["points"]["hero_power"],
            self.config["vision"]["hero_power_radius"],
        )
        if (
            not after_cards.playable_cards
            and hero_power_ratio
            >= float(self.config["vision"]["hero_power_green_ratio"])
        ):
            self._set_states(bot="Bot is running: using Hero Power")
            self._click(self._point(area, "hero_power"))
            self._sleep(float(self.config["vision"]["after_card_wait_seconds"]))

        self._attack_highlighted_characters(area)
        if not self._stop_event.is_set():
            self._set_states(bot="Bot is running: ending the turn")
            self._click(
                self._point(area, "end_turn"),
                float(self.config["behavior"]["navigation_click_hold_seconds"]),
            )
            self._sleep(float(self.config["vision"]["after_end_turn_wait_seconds"]))

    def _run(self) -> None:
        pyautogui.PAUSE = 0.01
        pyautogui.FAILSAFE = True
        try:
            while not self._stop_event.is_set():
                game = self._ensure_game()
                if game is None:
                    if self._sleep(2.0):
                        break
                    continue

                _hwnd, area = game
                handled = self._handle_screen_buttons(area)
                if handled is not None:
                    if handled == "play":
                        self._set_states(bot="Bot is running: starting a match")
                        self._next_actions_at = time.monotonic() + float(
                            self.config["vision"]["after_menu_click_wait_seconds"]
                        )
                    elif handled == "mulligan_confirm":
                        self._next_actions_at = time.monotonic() + float(
                            self.config["behavior"]["mulligan_wait_seconds"]
                        )
                    continue

                now = time.monotonic()
                if now < self._next_actions_at:
                    self._sleep(min(1.0, self._next_actions_at - now))
                    continue

                frame, snapshot = self._vision_snapshot(area)
                if snapshot.result_visible:
                    self._set_states(bot="Bot is running: closing the match result")
                    self._click(
                        self._point(area, "result_continue"),
                        float(self.config["behavior"]["navigation_click_hold_seconds"]),
                    )
                    self._next_actions_at = time.monotonic() + float(
                        self.config["vision"]["result_click_wait_seconds"]
                    )
                    LOGGER.info("Result or rank screen was recognized and closed")
                    continue

                if snapshot.mulligan_visible:
                    self._set_states(bot="Bot is running: confirming the starting hand")
                    self._click(
                        self._point(area, "mulligan_confirm"),
                        float(self.config["behavior"]["navigation_click_hold_seconds"]),
                    )
                    self._next_actions_at = time.monotonic() + float(
                        self.config["behavior"]["mulligan_wait_seconds"]
                    )
                    LOGGER.info("Starting-hand screen recognized; clicked OK")
                    continue

                if snapshot.play_visible:
                    self._set_states(bot="Bot is running: Play button detected")
                    self._click(
                        self._point(area, "play"),
                        float(self.config["behavior"]["navigation_click_hold_seconds"]),
                    )
                    self._next_actions_at = time.monotonic() + float(
                        self.config["vision"]["after_menu_click_wait_seconds"]
                    )
                    LOGGER.info("Play button recognized by its blue glow")
                    continue

                template_turn = self._matcher.installed("end_turn") and (
                    self._matcher.locate("end_turn", area) is not None
                )
                # Green decorations also exist in menus. The End Turn button first
                # proves this is a board; a green object or green button proves action.
                if snapshot.board_visible and (
                    snapshot.playable_cards
                    or snapshot.attackers
                    or snapshot.turn_active
                    or template_turn
                ):
                    self._take_visual_turn(area, frame, snapshot)
                else:
                    self._set_states(bot="Bot is running: waiting for a recognized screen")
                self._sleep(float(self.config["vision"]["scan_interval_seconds"]))
        except pyautogui.FailSafeException:
            LOGGER.warning("PyAutoGUI fail-safe was triggered")
            self._set_states(bot="Bot is stopped (fail-safe)")
        except Exception:
            LOGGER.exception("Unhandled error in the worker thread")
            self._set_states(bot="Bot error — see hs_bot.log")
        finally:
            self._stop_event.set()
            if self.states()[1] == "Bot is running":
                self._set_states(bot="Bot is stopped")


class GlobalCtrlCHotkey:
    HOTKEY_ID = 0x4842
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_CONTROL = 0x0002

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if os.name != "nt" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._listen, name="ctrl-c-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(1.0)

    def _listen(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        if not user32.RegisterHotKey(None, self.HOTKEY_ID, self.MOD_CONTROL, ord("C")):
            LOGGER.warning("Global Ctrl+C is already in use; Ctrl+C still works in the app window")
            self._ready.set()
            return
        self._ready.set()
        message = ctypes.wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == self.WM_HOTKEY and message.wParam == self.HOTKEY_ID:
                    self._callback()
        finally:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)

    def stop(self) -> None:
        if os.name == "nt" and self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)


class BotGui:
    def __init__(self, config: dict) -> None:
        self.root = tk.Tk()
        self.root.title("Hearthstone Simple Bot")
        self.root.geometry("380x230")
        self.root.resizable(False, False)
        self.root.configure(bg="#171b22")

        self.game_text = tk.StringVar(value="Game is not running")
        self.bot_text = tk.StringVar(value="Bot is stopped")
        self.bot = HearthstoneBot(config, lambda: None)
        self.hotkey = GlobalCtrlCHotkey(self._hotkey_stop)

        title = tk.Label(
            self.root,
            text="Hearthstone Simple Bot",
            font=("Segoe UI", 17, "bold"),
            fg="#f4c76b",
            bg="#171b22",
        )
        title.pack(pady=(18, 13))

        self.game_label = tk.Label(
            self.root,
            textvariable=self.game_text,
            font=("Segoe UI", 11),
            fg="#ef6b73",
            bg="#171b22",
        )
        self.game_label.pack()

        self.bot_label = tk.Label(
            self.root,
            textvariable=self.bot_text,
            font=("Segoe UI", 11),
            fg="#9aa4b2",
            bg="#171b22",
        )
        self.bot_label.pack(pady=(4, 15))

        buttons = tk.Frame(self.root, bg="#171b22")
        buttons.pack()
        self.start_button = tk.Button(
            buttons,
            text="Start",
            width=13,
            command=self.start,
            bg="#2e9b62",
            fg="white",
            activebackground="#257d50",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        self.start_button.grid(row=0, column=0, padx=6)
        self.stop_button = tk.Button(
            buttons,
            text="Stop",
            width=13,
            command=self.stop,
            bg="#b94d55",
            fg="white",
            activebackground="#913d44",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            state="disabled",
        )
        self.stop_button.grid(row=0, column=1, padx=6)

        tk.Label(
            self.root,
            text="Ctrl+C — stop the bot",
            font=("Segoe UI", 9),
            fg="#7f8996",
            bg="#171b22",
        ).pack(pady=(15, 0))

        self.root.bind_all("<Control-c>", lambda _event: self.stop())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.hotkey.start()
        self._refresh()
        self.root.after(500, self._poll)

    def _poll(self) -> None:
        self.bot.observe_game()
        self._refresh()
        self.root.after(500, self._poll)

    def _refresh(self) -> None:
        game_state, bot_state = self.bot.states()
        self.game_text.set(game_state)
        self.bot_text.set(bot_state)
        self.game_label.configure(fg="#55c986" if game_state == "Game is running" else "#ef6b73")
        self.bot_label.configure(
            fg="#55c986" if bot_state.startswith("Bot is running") else "#9aa4b2"
        )
        running = self.bot.running
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _hotkey_stop(self) -> None:
        # Event.set and the protected text state are safe outside Tk's main thread.
        self.bot.stop()

    def start(self) -> None:
        LOGGER.info("Bot started by the user")
        self.bot.start()
        self._refresh()

    def stop(self) -> None:
        LOGGER.info("Bot stopped by the user")
        self.bot.stop()
        self._refresh()

    def close(self) -> None:
        self.bot.stop()
        self.bot.join()
        self.hotkey.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    try:
        config = load_config()
    except RuntimeError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Hearthstone Simple Bot", str(exc))
        root.destroy()
        return

    app = BotGui(config)

    def stop_from_console(_signum, _frame) -> None:
        app.stop()

    signal.signal(signal.SIGINT, stop_from_console)
    app.run()


if __name__ == "__main__":
    main()
