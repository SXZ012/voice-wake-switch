# 🎤 离线语音唤醒智能开关

一个基于 Vosk 离线语音识别的智能开关系统。说出 "小派 + 命令词" 就能控制家里的灯和风扇，**完全离线运行，无需联网，保护隐私。**

---

## 功能特性

- **离线语音识别**：使用 Vosk 引擎，不需要联网，语音数据不出本地
- **唤醒词 + 命令词**：先说"小派"唤醒，再说命令词（避免误触发）
- **多设备控制**：支持灯（红/绿 LED）、风扇的独立开关和全开/全关
- **MQTT 实时上报**：每次操作都发布到 MQTT，方便接入 HomeAssistant / Node-RED
- **Mac 模拟模式**：没有树莓派也能在 Mac 上跑，所有 GPIO 操作用日志模拟
- **防盗链冷却**：识别到命令后进入 1.5 秒冷却期，防止一句话重复触发

---

## 硬件接线图

```
树莓派 GPIO（BCM 编号）        继电器模块           设备
─────────────────────────────────────────────────────────
  GPIO17 (引脚11)    ───────  IN1 ───────  NO ─── 红色 LED 灯
  GPIO27 (引脚13)    ───────  IN2 ───────  NO ─── 绿色 LED 灯
  GPIO22 (引脚15)    ───────  IN3 ───────  NO ─── 风扇
  GND  (引脚9)       ───────  GND（公共地）
  5V   (引脚2/4)     ───────  VCC（继电器供电）

⚠️  注意事项：
  - 继电器模块需要独立供电（树莓派 5V 引脚供小功率继电器够用）
  - 大功率设备（真正的大风扇）请用外接电源，继电器只做开关
  - COM 接火线，NO 接设备，NC 悬空不用
```

**继电器工作逻辑**：
- 引脚输出**低电平** → 继电器吸合 → 设备通电
- 引脚输出**高电平** → 继电器释放 → 设备断电
- 这样设计是因为树莓派开机时 GPIO 默认为不确定状态，高电平断电更安全

---

## 安装步骤

### 1. 克隆项目并进入目录

```bash
cd voice-wake-switch
```

### 2. 创建虚拟环境（推荐）

```bash
python3 -m venv venv
source venv/bin/activate        # Mac / Linux
# venv\Scripts\activate         # Windows
```

### 3. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

**Mac 用户注意**：RPi.GPIO 在 Mac 上无法安装，这是正常的。程序会自动检测并切换到模拟模式，不影响功能测试。

**树莓派用户**：额外安装 GPIO 库：
```bash
pip install RPi.GPIO
```

### 4. 下载 Vosk 中文语音模型

```bash
# 下载轻量中文模型（约 42MB，推荐）
wget https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip

# 解压到项目目录
unzip vosk-model-small-cn-0.22.zip

# 解压后的文件夹名默认就是 vosk-model-small-cn-0.22
# 和 config.py 里的 VOSK_MODEL_PATH 一致，不需要改名
```

> 如果下载慢，可以手动浏览器下载后放到项目目录解压。
> 其他模型（更大更准）见：https://alphacephei.com/vosk/models

### 5. 配置文件说明

打开 `config.py`，可以修改以下内容：

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `WAKE_WORD` | 唤醒词 | "小派" |
| `COMMANDS` | 命令词→动作映射 | 开灯/关灯/开风扇/关风扇/全开/全关 |
| `GPIO_MAP` | 设备→引脚映射 | red_led=17, green_led=27, fan=22 |
| `MQTT_BROKER` | MQTT 服务器地址 | localhost |
| `COOLDOWN_SECONDS` | 冷却时间(秒) | 1.5 |

---

## 使用方法

### Mac 上模拟测试

```bash
# 1. 确保麦克风可用（系统设置 → 隐私与安全性 → 麦克风 → 允许终端）
python main.py
```

运行后你会看到：
```
2025-06-07 12:00:00 [INFO ] main: 🎤 离线语音唤醒智能开关 启动中...
2025-06-07 12:00:00 [INFO ] main: 【1/3】初始化 MQTT 连接...
2025-06-07 12:00:00 [INFO ] main: 【2/3】初始化设备控制器...
2025-06-07 12:00:00 [INFO ] main: ⚠️  [MOCK] 未检测到 RPi.GPIO，切换到模拟模式
2025-06-07 12:00:00 [INFO ] main: 【3/3】初始化语音识别器...
2025-06-07 12:00:00 [INFO ] main: 系统已就绪！
2025-06-07 12:00:00 [INFO ] main: 对着麦克风说「小派开灯」试试吧～
```

然后对着麦克风说 **"小派开灯"**，你会看到：
```
🔔 检测到唤醒词：「小派」
🎯 匹配到命令 → lights_on
[MOCK] GPIO.output(pin=17, level=False) LOW(吸合)
[MOCK] GPIO.output(pin=27, level=False) LOW(吸合)
📡 MQTT 发布 → home/device/status：{"device":"开灯","state":"on",...}
```

按 `Ctrl+C` 退出。

### 树莓派上真实运行

```bash
# 确认 GPIO 库正常
python -c "import RPi.GPIO; print('GPIO OK')"

# 如果有 MQTT Broker（比如 Mosquitto）
sudo systemctl start mosquitto

# 运行
python main.py
```

### 开机自启（可选）

```bash
# 编辑 rc.local
sudo nano /etc/rc.local

# 在 exit 0 之前加入：
cd /home/pi/voice-wake-switch
/usr/bin/python main.py &

# 保存退出
```

---

## 故障排查

| 现象 | 可能原因 | 解决方法 |
|---|---|---|
| `找不到 Vosk 模型` | 模型没下载或路径不对 | 确认 `vosk-model-small-cn-0.22` 文件夹在项目目录下 |
| `无法打开麦克风` | 权限问题 | Mac: 系统设置→隐私→麦克风。树莓派: `arecord -l` 检查设备 |
| `ImportError: RPi.GPIO` | Mac 上没装 | 正常的，程序会自动切到模拟模式 |
| 识别不灵敏 | 环境噪音大 / 麦克风差 | 靠近麦克风说话，用 USB 麦克风效果更好 |
| 继电器不动作 | 接线错误 / 供电不足 | 检查 GND 共地，大功率继电器需要外接电源 |
| MQTT 连接失败 | Broker 没启动 | `sudo systemctl start mosquitto` 或忽略（系统仍可用） |

---

## 技术栈

| 组件 | 技术 | 用途 |
|---|---|---|
| 语音识别 | Vosk (Kaldi) | 离线中文语音转文字 |
| 音频采集 | PyAudio | 麦克风录音 |
| 硬件控制 | RPi.GPIO | 树莓派 GPIO 引脚控制 |
| 消息通信 | MQTT (paho-mqtt) | 设备状态上报 |
| 语言 | Python 3.9+ | 主逻辑 |

---

## 项目结构

```
voice-wake-switch/
├── config.py             # 配置文件（唤醒词、命令词、引脚、MQTT 参数）
├── vosk_asr.py           # 语音识别模块（麦克风 → Vosk → 文本匹配）
├── device_controller.py  # 设备控制模块（GPIO 抽象层，支持 Mock）
├── mqtt_publisher.py     # MQTT 发布模块（状态上报）
├── main.py               # 主程序（串联所有模块）
├── requirements.txt      # Python 依赖清单
└── README.md             # 本文件
```
