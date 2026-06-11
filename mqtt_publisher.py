"""
MQTT 发布模块
=============
把设备的开关状态发布到 MQTT Broker，这样其他设备（比如手机 App、
HomeAssistant、Node-RED）都能实时知道状态变化。

简单说：树莓派是"嘴巴"，通过 MQTT 把消息广播出去。
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """
    MQTT 消息发布器
    ---------------
    负责连接 MQTT Broker，把设备状态发布到指定主题。

    使用示例：
        mqtt_pub = MQTTPublisher("localhost", 1883, "home/device/status")
        mqtt_pub.publish("red_led", "on")
        mqtt_pub.disconnect()
    """

    # 连接重试参数
    _RETRY_MAX: int = 5        # 最多重试 5 次
    _RETRY_DELAY: float = 2.0  # 每次重试间隔 2 秒

    def __init__(self, broker: str, port: int, topic: str) -> None:
        """
        初始化 MQTT 发布器并连接到 Broker。

        参数：
            broker: MQTT Broker 地址（IP 或域名）
            port:   端口号（默认 1883）
            topic:  发布消息的主题（如 "home/device/status"）
        """
        self._broker: str = broker
        self._port: int = port
        self._topic: str = topic

        # 创建 MQTT 客户端
        # client_id 用时间戳保证不重复（多个实例同时跑时不冲突）
        client_id: str = f"voice_switch_{int(time.time() * 1000)}"
        self._client: mqtt.Client = mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311,  # MQTT 3.1.1 版本，兼容性最好
        )

        # 设置回调函数
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        # 连接（带重试）
        self._connected: bool = False
        self._connect_with_retry()

    # ==================== 连接管理 ====================

    def _connect_with_retry(self) -> None:
        """
        连接到 MQTT Broker，失败自动重试。

        流程：
            循环尝试连接 → 成功就退出 → 失败等几秒再试
            超过最大重试次数后不抛异常（MQTT 不是必须的，系统还能跑）
        """
        for attempt in range(1, self._RETRY_MAX + 1):
            try:
                logger.info(
                    "正在连接 MQTT Broker（%s:%d）... 第 %d/%d 次",
                    self._broker, self._port, attempt, self._RETRY_MAX,
                )
                self._client.connect(self._broker, self._port, keepalive=60)
                self._client.loop_start()  # 启动后台网络线程
                self._connected = True
                logger.info("✅ MQTT 连接成功")
                return
            except Exception as e:
                logger.warning("MQTT 连接失败（%d/%d）：%s", attempt, self._RETRY_MAX, e)
                if attempt < self._RETRY_MAX:
                    time.sleep(self._RETRY_DELAY)

        logger.warning(
            "⚠️  MQTT 连接最终失败，系统将在无 MQTT 模式下运行（设备控制正常）"
        )
        self._connected = False

    def _on_connect(
        self, client: mqtt.Client, userdata: object, flags: dict, rc: int
    ) -> None:
        """
        连接成功后的回调（由 paho-mqtt 库调用）。

        参数：
            client:   客户端实例
            userdata: 用户数据（这里没用）
            flags:    应答标志
            rc:       返回码，0 表示成功
        """
        if rc == 0:
            logger.info("MQTT 回调：连接确认")
        else:
            logger.warning("MQTT 回调：连接异常，返回码=%d", rc)

    def _on_disconnect(
        self, client: mqtt.Client, userdata: object, rc: int
    ) -> None:
        """
        断开连接后的回调。

        参数：
            rc: 0 表示主动断开，非 0 表示异常断开
        """
        if rc != 0:
            logger.warning("MQTT 异常断开，返回码=%d", rc)
        self._connected = False

    # ==================== 消息发布 ====================

    def publish(self, device: str, state: str) -> None:
        """
        发布设备状态消息到 MQTT。

        参数：
            device: 设备名字（如 "red_led"）
            state:  设备状态（"on" 或 "off"）

        发布的消息格式（JSON）：
            {
                "device": "red_led",
                "state": "on",
                "timestamp": "2025-06-07T12:00:00+08:00"
            }
        """
        if not self._connected:
            logger.debug("MQTT 未连接，跳过发布：%s=%s", device, state)
            return

        # 构造消息体
        payload: dict[str, str] = {
            "device": device,
            "state": state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        payload_str: str = json.dumps(payload, ensure_ascii=False)

        try:
            result: mqtt.MQTTMessageInfo = self._client.publish(
                self._topic,
                payload_str,
                qos=1,       # QoS 1：至少送达一次
                retain=False,  # 不保留（新订阅者不会收到旧消息）
            )

            # 等待发送完成（带超时）
            result.wait_for_publish(timeout=1.0)

            logger.info("📡 MQTT 发布 → %s：%s", self._topic, payload_str)

        except Exception as e:
            logger.error("MQTT 发布失败：%s", e)

    # ==================== 资源释放 ====================

    def disconnect(self) -> None:
        """
        断开 MQTT 连接并释放资源。
        程序退出前要调用。
        """
        if self._connected:
            logger.info("正在断开 MQTT 连接...")
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            logger.info("MQTT 已断开 ✅")
