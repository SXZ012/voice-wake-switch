"""
主程序
======
把语音识别、设备控制、MQTT 发布三个模块串起来，组成完整的
"离线语音唤醒智能开关"系统。

运行方式：
    python main.py

退出方式：
    按 Ctrl+C（程序会优雅退出，释放所有硬件资源）
"""

import logging
import signal
import sys
import time
from typing import Optional

from config import MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_STATUS, COMMANDS, WAKE_WORD
from device_controller import DeviceController
from mqtt_publisher import MQTTPublisher
from vosk_asr import VoiceRecognizer

# ==================== 日志配置 ====================
# 设置日志格式：时间 + 级别 + 来源模块 + 消息内容
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger: logging.Logger = logging.getLogger("main")


# ==================== 全局实例 ====================
# 需要在退出时清理的实例们，先声明为 None

_mqtt_pub: Optional[MQTTPublisher] = None
_device_ctrl: Optional[DeviceController] = None
_voice_rec: Optional[VoiceRecognizer] = None


# ==================== 命令词 → 中文名映射 ====================
# 建立一个反向映射：action → 中文命令词
# 比如 "lights_on" → "开灯"，方便日志和 MQTT 显示

# 反向映射：action → 主命令词（用于显示）
# 注意多个命令词可能映射到同一个 action，这里保留正式的命令词
_ACTION_TO_COMMAND: dict[str, str] = {
    "lights_on":  "开灯",
    "lights_off": "关灯",
    "fan_on":     "开风扇",
    "fan_off":    "关风扇",
    "all_on":     "全开",
    "all_off":    "全关",
}


# ==================== 回调函数 ====================

def on_command_recognized(action: str) -> None:
    """
    语音识别到命令后的回调。
    执行硬件操作 + 发布 MQTT 状态。
    """
    command_word: str = _ACTION_TO_COMMAND.get(action, action)
    # 简单清晰的成功提示
    logger.info("⚡ 执行命令：%s", command_word)

    # 执行硬件操作
    if _device_ctrl is not None:
        _device_ctrl.execute(action)

    # 发布 MQTT 状态
    if action.endswith("_on"):
        state: str = "on"
    elif action.endswith("_off"):
        state = "off"
    else:
        state = action

    if _mqtt_pub is not None:
        _mqtt_pub.publish(command_word, state)


# ==================== 信号处理（Ctrl+C） ====================

def _signal_handler(signum: int, frame: object) -> None:
    """
    处理 Ctrl+C 信号，优雅退出。
    先停止语音识别，再清理 GPIO，最后断开 MQTT。
    """
    logger.info("收到退出信号（Ctrl+C），正在清理资源...")
    cleanup()
    sys.exit(0)


def cleanup() -> None:
    """
    清理所有资源。
    顺序：先停耳朵（麦克风），再停手（GPIO），最后停嘴（MQTT）。
    """
    # 停语音识别（释放麦克风）
    if _voice_rec is not None:
        _voice_rec.stop()

    # 停设备控制（释放 GPIO 引脚）
    if _device_ctrl is not None:
        _device_ctrl.cleanup()

    # 停 MQTT（断开连接）
    if _mqtt_pub is not None:
        _mqtt_pub.disconnect()

    logger.info("👋 系统已安全退出，所有资源已释放")


# ==================== 主函数 ====================

def main() -> None:
    """
    程序入口。
    流程：
        初始化 MQTT → 初始化 GPIO → 初始化语音识别 → 监听 → 等 Ctrl+C
    """
    global _mqtt_pub, _device_ctrl, _voice_rec

    logger.info("🎤 离线语音唤醒智能开关 启动中...")
    logger.info("-" * 40)

    # 注册 Ctrl+C 信号处理
    signal.signal(signal.SIGINT, _signal_handler)

    # 初始化各模块
    _mqtt_pub = MQTTPublisher(MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_STATUS)
    _device_ctrl = DeviceController()
    _voice_rec = VoiceRecognizer()

    # 启动语音监听
    logger.info("-" * 40)
    logger.info("✅ 系统就绪 | 唤醒词：「%s」", WAKE_WORD)
    logger.info("   命令：%s", "、".join(_ACTION_TO_COMMAND.values()))
    logger.info("   说「小派开灯」试试吧 | Ctrl+C 退出")
    logger.info("-" * 40)

    _voice_rec.listen(on_command_recognized)

    # ----- 第 5 步：主线程等待 -----
    # 语音识别在后台线程跑，主线程在这里等待，直到 Ctrl+C
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        # 双重保险：万一信号处理没捕获到
        pass
    finally:
        cleanup()


# ==================== 入口 ====================

if __name__ == "__main__":
    main()
