"""
硬件抽象层
==========
负责控制真实的硬件设备（通过 GPIO），同时在 Mac/Windows 上开发时
自动切换到模拟模式，方便调试。

设计思路：
  - 树莓派上装 RPi.GPIO → 控制真实的继电器
  - 开发机上没装 RPi.GPIO → 用 MockGPIO 假动作，只打日志
"""

import logging
import time
from typing import Optional

from config import GPIO_MAP, DEVICE_GROUPS

logger = logging.getLogger(__name__)

# ==================== 尝试导入 GPIO 库 ====================
# 树莓派上有 RPi.GPIO，Mac 上没有，所以用 try/except 做兼容

_GPIO: Optional[object] = None        # 真实的 GPIO 模块
_MOCK_MODE: bool = False              # 是否在模拟模式

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _GPIO = GPIO
    logger.info("✅ 使用真实 GPIO（RPi.GPIO）")
except ImportError:
    # 没有 RPi.GPIO？那就用假的，不耽误开发测试
    _MOCK_MODE = True
    logger.info("⚠️  [MOCK] 未检测到 RPi.GPIO，切换到模拟模式")
    logger.info("⚠️  [MOCK] 所有 GPIO 操作只会打印日志，不会控制真实硬件")


# ==================== 模拟 GPIO 类 ====================

class MockGPIO:
    """
    假的 GPIO 类，行为像真的 GPIO，但实际上只打日志。
    方便在 Mac 上开发调试。
    """

    BCM: str = "BCM"  # 只是为了兼容 RPi.GPIO 的常量
    OUT: str = "OUT"
    HIGH: bool = True
    LOW: bool = False

    @staticmethod
    def setmode(mode: str) -> None:
        """设置引脚编号模式（模拟）"""
        logger.info("[MOCK] GPIO.setmode(%s)", mode)

    @staticmethod
    def setwarnings(flag: bool) -> None:
        """开关警告信息（模拟）"""
        pass

    @staticmethod
    def setup(pin: int, mode: str, initial: bool = False) -> None:
        """
        设置引脚模式（模拟）

        参数：
            pin: GPIO 引脚号（BCM 编号）
            mode: 输入/输出模式
            initial: 初始电平
        """
        logger.info("[MOCK] GPIO.setup(pin=%d, mode=%s, initial=%s)", pin, mode, initial)

    @staticmethod
    def output(pin: int, level: bool) -> None:
        """
        设置引脚电平（模拟）

        参数：
            pin: GPIO 引脚号
            level: True=高电平, False=低电平
        """
        state_str: str = "HIGH(释放)" if level else "LOW(吸合)"
        logger.info("[MOCK] GPIO.output(pin=%d, level=%s) %s", pin, level, state_str)

    @staticmethod
    def cleanup() -> None:
        """清理所有引脚（模拟）"""
        logger.info("[MOCK] GPIO.cleanup()")

    @staticmethod
    def input(pin: int) -> bool:
        """读取引脚电平（模拟）"""
        logger.debug("[MOCK] GPIO.input(pin=%d)", pin)
        return True  # 假装是高电平


# ==================== 设备控制器 ====================

class DeviceController:
    """
    设备控制器
    ----------
    把"开灯""关风扇"这样的指令翻译成 GPIO 引脚的高低电平操作。

    继电器逻辑（重要！）：
      - 高电平(HIGH/True) → 继电器释放 → 设备断电
      - 低电平(LOW/False)  → 继电器吸合 → 设备通电

    为什么反过来？因为树莓派开机时引脚默认状态不可靠，用高电平
    做"断电"状态更安全（即使树莓派重启，灯也不会意外亮起）。
    """

    def __init__(self) -> None:
        """
        初始化所有设备引脚。
        遍历 GPIO_MAP，把每个引脚设为输出模式，初始为高电平（断电）。
        """
        # 根据有没有 RPi.GPIO 来决定用真的还是假的
        if _GPIO is not None and not _MOCK_MODE:
            self._gpio = _GPIO
        else:
            self._gpio = MockGPIO

        self._mock_mode: bool = _MOCK_MODE

        # 初始化所有 GPIO 引脚
        logger.info("正在初始化设备引脚...")
        for device_name, pin in GPIO_MAP.items():
            self._gpio.setup(pin, self._gpio.OUT)
            self._gpio.output(pin, self._gpio.HIGH)   
            logger.info("  引脚 GPIO%d → %s（初始=断电）", pin, device_name)

        logger.info("设备控制器就绪 ✅")

    # ==================== 单设备控制 ====================

    def turn_on(self, device: str) -> None:
        """
        打开指定设备（继电器吸合，引脚置低电平）

        参数：
            device: 设备名字，如 "red_led", "fan"
        """
        pin: int = self._get_pin(device)
        if pin == -1:
            return

        tag: str = "[MOCK] " if self._mock_mode else ""
        logger.info("%s🔛 打开设备：%s（GPIO%d 置低电平）", tag, device, pin)
        self._gpio.output(pin, self._gpio.LOW) 

    def turn_off(self, device: str) -> None:
        """
        关闭指定设备（继电器释放，引脚置高电平）

        参数：
            device: 设备名字，如 "red_led", "fan"
        """
        pin: int = self._get_pin(device)
        if pin == -1:
            return

        tag: str = "[MOCK] " if self._mock_mode else ""
        logger.info("%s🔴 关闭设备：%s（GPIO%d 置高电平）", tag, device, pin)
        self._gpio.output(pin, self._gpio.HIGH) 

    def _get_pin(self, device: str) -> int:
        """
        根据设备名字查找对应的 GPIO 引脚号。

        返回：
            引脚号，找不到时返回 -1
        """
        pin: Optional[int] = GPIO_MAP.get(device)
        if pin is None:
            logger.warning("未知设备：%s，已跳过", device)
            return -1
        return pin

    # ==================== 批量控制（核心） ====================

    def execute(self, action: str) -> None:
        """
        执行一个动作指令。

        参数：
            action: 动作名称，如 "lights_on", "fan_off", "all_on"

        内部逻辑：
            1. 解析 action → 知道要控制哪组设备、开还是关
            2. 找到这组设备包含哪些硬件
            3. 挨个执行 turn_on() 或 turn_off()
            4. 真实设备之间加一点间隔，防止瞬间电流太大

        示例：
            execute("lights_on")
            → 组="lights", 状态="on"
            → 设备=["red_led", "green_led"]
            → red_led 开、green_led 开
        """
        # 特殊情况："全开""全关" → 控制所有设备
        if action == "all_on":
            logger.info("🌟 执行全开")
            for device in GPIO_MAP:
                self.turn_on(device)
                if not self._mock_mode:
                    time.sleep(0.1)
            return

        if action == "all_off":
            logger.info("🌟 执行全关")
            for device in GPIO_MAP:
                self.turn_off(device)
                if not self._mock_mode:
                    time.sleep(0.1)
            return

        # 普通情况：从 action 解析出组名和状态
        # action 格式："{组名}_{状态}"，如 "lights_on" → 组="lights", 状态="on"
        if "_" not in action:
            logger.warning("无效的动作：%s（格式应为 组名_状态）", action)
            return

        group, state = action.rsplit("_", 1)

        if state not in ("on", "off"):
            logger.warning("无效的状态：%s（只支持 on 或 off）", state)
            return

        # 找到这组包含的设备
        devices: list[str] = DEVICE_GROUPS.get(group, [])
        if not devices:
            logger.warning("未知设备组：%s", group)
            return

        logger.info("执行动作：%s → 组=%s, 状态=%s, 设备=%s", action, group, state, devices)

        # 挨个控制
        for device in devices:
            if state == "on":
                self.turn_on(device)
            else:
                self.turn_off(device)

            # 真实硬件上加点间隔（继电器切换需要时间）
            if not self._mock_mode:
                time.sleep(0.1)

    # ==================== 资源释放 ====================

    def cleanup(self) -> None:
        logger.info("正在关闭所有设备并清理 GPIO...")
        self._gpio.setmode(self._gpio.BCM)
        for pin in GPIO_MAP.values():
            try:
                self._gpio.output(pin, self._gpio.HIGH)   # 先拉高
            except RuntimeError:
                # 如果引脚未初始化，忽略错误
                pass
        self._gpio.cleanup()
        logger.info("所有设备已关闭，GPIO 已清理 ✅")
