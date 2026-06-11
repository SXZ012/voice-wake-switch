"""
配置文件
=======
所有可调参数都集中在这里，方便修改。
- 想改唤醒词？改 WAKE_WORD
- 想加新命令？在 COMMANDS 里加一行
- 想绑定不同的 GPIO 引脚？改 GPIO_MAP
"""

# ==================== 语音识别相关 ====================

# 唤醒词：说出这个词后，系统才会理你
WAKE_WORD: str = "小派"

# 唤醒词容错变体：语音识别可能把"小派"听成别的词
# 这些变体也会被当作唤醒词处理（解决"小派"被识别成"笑喷"之类的问题）
WAKE_WORD_VARIANTS: list[str] = ["笑喷", "小喷", "小盆", "校派", "小牌", "消派"]

# 命令词映射表
# 键(key)  = 你说的中文命令（含容错变体）
# 值(value) = 程序内部用的 action 名字
# 注：Vosk 小模型不太准，常见的听错版本也加进来做容错
COMMANDS: dict[str, str] = {
    # 灯
    "开灯":   "lights_on",
    "关灯":   "lights_off",
    # 风扇（含常见识别错误：开封闪/关风山等）
    "开风扇": "fan_on",
    "开封闪": "fan_on",
    "开封市": "fan_on",
    "开封山": "fan_on",
    "关风扇": "fan_off",
    "关封闪": "fan_off",
    "关风山": "fan_off",
    # 全局
    "全开":   "all_on",
    "全关":   "all_off",
}

# Vosk 模型文件夹路径
# 模型需要提前下载，默认放在项目同级目录下
# 下载地址：https://alphacephei.com/vosk/models
VOSK_MODEL_PATH: str = "vosk-model-small-cn-0.22"

# 唤醒后冷却时间（秒）
# 防止一句话里同时包含唤醒词和多个命令词，导致重复触发
COOLDOWN_SECONDS: float = 1.5

# ==================== 硬件相关 ====================

# 设备分组：一个 action 可能同时控制多个硬件
# 比如"开灯"会同时打开 red_led 和 green_led
DEVICE_GROUPS: dict[str, list[str]] = {
    "lights": ["red_led"],
    "fan":    ["fan"],
}

# GPIO 引脚映射（BCM 编号）
# 把设备名字映射到树莓派的 GPIO 引脚号
GPIO_MAP: dict[str, int] = {
    "red_led":   17,
    "fan":       27,
}

# ==================== MQTT 相关 ====================

# MQTT Broker 地址（就是消息中间件的 IP 地址）
MQTT_BROKER: str = "localhost"

# MQTT 端口号（默认 1883）
MQTT_PORT: int = 1883

# 设备状态上报的主题(topic)
# 其他设备可以订阅这个主题，实时知道开关状态
MQTT_TOPIC_STATUS: str = "home/device/status"
