"""
AstrBot 天气查询插件
支持城市天气查询和天气预报功能
"""

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
import httpx
import json
from typing import Optional


class AstroWeather(Star):
    """天气查询插件主类"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.api_base = "https://api.open-meteo.com/v1"
        logger.info("天气查询插件已加载")

    @filter.command("天气")
    async def get_weather(self, event: AstrMessageEvent, city: str = ""):
        """查询当前天气"""
        if not city:
            yield event.plain_result("请提供城市名称，例如：/天气 北京")
            return

        try:
            # 调用 Open-Meteo API
            url = f"{self.api_base}/forecast"
            params = {
                "city": city,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

            if "error" in data:
                yield event.plain_result(f"查询失败：{data['error']['message']}")
                return

            # 解析天气数据
            current = data.get("current", {})
            daily = data.get("daily", {})

            temp = current.get("temperature_2m", "N/A")
            humidity = current.get("relative_humidity_2m", "N/A")
            wind = current.get("wind_speed_10m", "N/A")
            code = current.get("weather_code", 0)

            weather_desc = self._get_weather_desc(code)
            date = daily.get("time", [])[0] if daily.get("time") else "今日"

            result = (
                f"🌍 {city} - {date}\n"
                f"🌡️ 温度：{temp}°C\n"
                f"💧 湿度：{humidity}%\n"
                f"💨 风速：{wind} km/h\n"
                f"☁️ 天气：{weather_desc}\n"
            )

            # 添加未来3天预报
            if daily.get("time") and len(daily["time"]) > 1:
                result += "\n📅 未来3天预报：\n"
                for i in range(1, min(4, len(daily["time"]))):
                    date_str = daily["time"][i]
                    max_temp = daily.get("temperature_2m_max", [])[i] if daily.get("temperature_2m_max") else "N/A"
                    min_temp = daily.get("temperature_2m_min", [])[i] if daily.get("temperature_2m_min") else "N/A"
                    day_code = daily.get("weather_code", [])[i] if daily.get("weather_code") else 0
                    day_desc = self._get_weather_desc(day_code)

                    result += f"{date_str}: {day_desc}, {min_temp}°C ~ {max_temp}°C\n"

            yield event.plain_result(result)

        except httpx.TimeoutException:
            yield event.plain_result("查询超时，请稍后再试")
        except httpx.HTTPStatusError as e:
            yield event.plain_result(f"查询失败：HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"天气查询错误：{e}")
            yield event.plain_result(f"查询失败：{str(e)}")

    def _get_weather_desc(self, code: int) -> str:
        """根据天气代码获取描述"""
        weather_codes = {
            0: "晴朗",
            1: "大部分晴朗",
            2: "多云",
            3: "阴天",
            45: "雾",
            48: "雾凇",
            51: "毛毛雨",
            53: "中毛毛雨",
            55: "大毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            95: "雷雨"
        }
        return weather_codes.get(code, "未知")

    async def terminate(self):
        """插件卸载时的清理工作"""
        logger.info("天气查询插件已卸载")
