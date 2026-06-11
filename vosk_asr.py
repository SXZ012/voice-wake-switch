"""
Vosk 离线语音识别模块
======================
核心功能：用麦克风持续监听，检测到唤醒词 + 命令词后，回调通知主程序。
整个过程完全离线运行，不需要联网，保护隐私。
"""

import json
import logging
import os
import sys
import threading
import time
from typing import Callable, Optional

from vosk import Model, KaldiRecognizer

from config import (
    WAKE_WORD,
    WAKE_WORD_VARIANTS,
    COMMANDS,
    VOSK_MODEL_PATH,
    COOLDOWN_SECONDS,
)

# 拿一个日志记录器，别的模块引用时就知道日志是谁打的
logger = logging.getLogger(__name__)


class VoiceRecognizer:
    """
    语音识别器
    ----------
    做的事：
    1. 加载 Vosk 中文模型
    2. 打开麦克风
    3. 在后台线程中不断听你说话
    4. 听到"小派 + 命令词"就通知主程序

    用人话说就是：让树莓派"长耳朵"。
    """

    # 音频参数（一般不用改）
    SAMPLE_RATE: int = 16000        # 采样率 16kHz，Vosk 要求的值
    CHANNELS: int = 1               # 单声道，够用
    CHUNK_SIZE: int = 512           # 每次读 512 个音频采样点

    def __init__(self) -> None:
        """
        初始化语音识别器
        - 加载 Vosk 模型
        - 打开麦克风
        - 创建识别器实例
        """
        # --- 第 1 步：加载 Vosk 模型 ---
        self._model: Optional[Model] = None
        self._load_model()

        # --- 第 2 步：初始化 PyAudio 并打开麦克风 ---
        self._open_microphone()

        # --- 第 3 步：创建 Vosk 识别器 ---
        self._recognizer: KaldiRecognizer = KaldiRecognizer(
            self._model,          # type: ignore[arg-type]
            self.SAMPLE_RATE
        )
        self._recognizer.SetWords(True)

        # --- 第 4 步：后台线程控制 ---
        self._stop_event: threading.Event = threading.Event()
        self._listening_thread: Optional[threading.Thread] = None

        # --- 第 5 步：状态跟踪 ---
        self._last_trigger_time: float = 0.0     # 冷却时间戳
        self._wake_detected_time: float = 0.0    # 最近一次检测到唤醒词的时间
        self._wake_active_window: float = 4.0    # 唤醒后 4 秒内可以直接说命令

        logger.info("✅ 语音识别器初始化完成")

    # ==================== 模型加载 ====================

    def _load_model(self) -> None:
        """
        加载 Vosk 中文语音模型。
        如果模型文件夹不存在，打印下载地址并退出。
        """
        if not os.path.exists(VOSK_MODEL_PATH):
            logger.error(f"❌ 找不到 Vosk 模型文件夹：{VOSK_MODEL_PATH}")
            logger.error("   请去以下地址下载中文模型：")
            logger.error("   https://alphacephei.com/vosk/models")
            logger.error("   推荐下载 vosk-model-small-cn-0.22（体积小、速度快的那个）")
            logger.error("   下载后解压到本项目目录下即可。")
            sys.exit(1)

        logger.info(f"正在加载 Vosk 模型：{VOSK_MODEL_PATH} ...")
        self._model = Model(VOSK_MODEL_PATH)
        logger.info("模型加载完成 ✅")

    # ==================== 麦克风初始化 ====================
    def _open_microphone(self) -> None:
        """
        使用 arecord 打开 C270 麦克风，通过管道读取音频。
        """
        import subprocess, sys

        self._audio = None
        self._stream = None

        try:
            self._rec_process = subprocess.Popen(
                [
                    "arecord",
                    "-D", "plughw:2,0",
                    "-f", "S16_LE",
                    "-r", str(self.SAMPLE_RATE),
                    "-c", str(self.CHANNELS),
                    "-t", "raw",
                    "-q"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            self._read_chunk = self.CHUNK_SIZE * self.CHANNELS * 2
            logger.info("麦克风已就绪 ✅ (arecord)")
        except FileNotFoundError:
            logger.error("❌ 找不到 arecord")
            sys.exit(1)
        except Exception as e:
            logger.error("❌ 无法通过 arecord 打开麦克风: %s", e)
            sys.exit(1)
    # ==================== 语音监听（核心） ====================

    def listen(self, callback: Callable[[str], None]) -> None:
        """
        启动后台监听。

        参数：
            callback: 回调函数，当识别到命令时会调用它
                      接收一个参数 → action 字符串（如 "lights_on"）

        流程：
            麦克风收音 → Vosk 实时识别 → 找唤醒词 → 找命令词 → 回调
        """
        if self._listening_thread is not None and self._listening_thread.is_alive():
            logger.warning("语音监听已经在运行，不要重复启动哈")
            return

        self._stop_event.clear()
        self._listening_thread = threading.Thread(
            target=self._listening_loop,
            args=(callback,),
            daemon=True,  # 守护线程：主程序退出时自动结束
        )
        self._listening_thread.start()
        logger.info('🎤 开始语音监听...（唤醒词：「%s」）', WAKE_WORD)

    def _listening_loop(self, callback: Callable[[str], None]) -> None:
        """
        后台线程的主循环。

        两种模式：
          一句话模式：直接说「小派开灯」→ 一次性触发
          两步模式：先说「小派」→ 有提示 → 再说「开灯」→ 触发

        每轮执行后自动重置所有状态，保证可以无限次触发。
        """
        while not self._stop_event.is_set():
            try:
                # 第 1 步：从麦克风读取音频
                try:
                    data = self._rec_process.stdout.read(self._read_chunk)
                except OSError:
                    continue

                if len(data) == 0:
                    continue

                # 第 2 步：喂给 Vosk
                is_final: bool = self._recognizer.AcceptWaveform(data)

                # 第 3 步：获取识别文本
                partial_text: str = self._extract_text(self._recognizer.PartialResult())
                final_text: str = ""
                if is_final:
                    final_text = self._extract_text(self._recognizer.Result())

                best_text: str = final_text if final_text else partial_text
                if not best_text:
                    continue

                # 第 4 步：提取匹配信息
                now: float = time.time()
                matched_wake: str = self._check_wake_word(best_text)
                matched_action: Optional[str] = self._match_command(best_text)

                # 判断当前是否在冷却期
                in_cooldown: bool = (now - self._last_trigger_time) < COOLDOWN_SECONDS
                if in_cooldown:
                    continue  # 冷却中，啥都不做

                # 判断是否在唤醒窗口内（两步模式的第2步用）
                in_wake_window: bool = (
                    self._wake_detected_time > 0
                    and (now - self._wake_detected_time) < self._wake_active_window
                )

                # --- 模式1：一句话模式（唤醒词 + 命令词都在）---
                if matched_wake and matched_action:
                    self._last_trigger_time = now
                    self._wake_detected_time = 0.0   # 全部重置
                    logger.info("🎯 识别成功 → %s", matched_action)
                    callback(matched_action)
                    continue

                # --- 模式2-第1步：只听到唤醒词，进入等待命令状态 ---
                if matched_wake and not matched_action:
                    # _wake_detected_time 为 0 说明刚进入等待状态，打印提示
                    if self._wake_detected_time == 0.0:
                        logger.info("💡 听到「%s」，请说命令...", matched_wake)
                    self._wake_detected_time = now
                    continue

                # --- 模式2-第2步：在唤醒窗口内听到命令词 ---
                if not matched_wake and matched_action and in_wake_window:
                    self._last_trigger_time = now
                    self._wake_detected_time = 0.0   # 全部重置
                    logger.info("🎯 识别成功 → %s", matched_action)
                    callback(matched_action)
                    continue

                # --- 唤醒窗口过期自动重置 ---
                if self._wake_detected_time > 0 and not in_wake_window:
                    self._wake_detected_time = 0.0

            except Exception as e:
                logger.error("监听循环出错：%s", e, exc_info=True)
                time.sleep(0.1)

    # ==================== 文本解析 ====================

    @staticmethod
    def _extract_text(json_str: str) -> str:
        """
        从 Vosk 返回的 JSON 字符串中提取识别文本。

        Vosk 输出中文时会自动加空格（如 "小 派 开灯"），
        所以提取后要把空格去掉，方便后续匹配。

        参数：
            json_str: Vosk 返回的 JSON，例如 {"partial" : "小 派 开灯"}

        返回：
            识别到的文本内容（已去除空格），失败时返回空字符串
        """
        try:
            result: dict = json.loads(json_str)
            text: str = result.get("partial", "")
            # Vosk 中文输出带空格（如 "小 派 开灯"），去掉空格统一变成 "小派开灯"
            return text.replace(" ", "").strip()
        except json.JSONDecodeError:
            return ""

    @staticmethod
    def _check_wake_word(text: str) -> str:
        """
        检查文本中是否包含唤醒词（包括容错变体）。

        参数：
            text: 识别到的文本

        返回：
            匹配到的唤醒词文本，没匹配到返回空字符串
        """
        # 先检查正式唤醒词
        if WAKE_WORD in text:
            return WAKE_WORD

        # 再检查容错变体（比如把"小派"听成"笑喷"）
        for variant in WAKE_WORD_VARIANTS:
            if variant in text:
                return variant

        return ""

    @staticmethod
    def _match_command(text: str) -> Optional[str]:
        """
        在文本中查找命令词，返回对应的 action。

        参数：
            text: 识别到的文本，比如 "小派开灯"

        返回：
            匹配到的 action 字符串，没匹配到返回 None

        注意：
            命令词按字符串长度降序排列，优先匹配长的（比如有"开灯"
            和"开灯全部"时，先匹配后者，避免被短的抢先）。
        """
        # 按命令词长度从长到短排序，防止短命令抢跑
        sorted_commands: list[tuple[str, str]] = sorted(
            COMMANDS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )

        for command_word, action in sorted_commands:
            if command_word in text:
                return action

        return None

    # ==================== 资源释放 ====================
    def stop(self) -> None:
        """
        停止语音监听，释放麦克风和模型资源。
        程序退出前一定要调用，否则麦克风可能被占着。
        """
        logger.info("正在停止语音识别...")
        self._stop_event.set()

        # 等待监听线程退出
        if self._listening_thread is not None and self._listening_thread.is_alive():
            self._listening_thread.join(timeout=2.0)

        # 终止 arecord 进程
        if hasattr(self, '_rec_process') and self._rec_process:
            self._rec_process.terminate()
            self._rec_process.wait()
            logger.info("arecord 进程已终止")

        # 释放 Vosk 模型（如果有的话）
        if self._model:
            self._model = None

        logger.info("语音识别已停止")
