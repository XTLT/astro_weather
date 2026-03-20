"""
AstrBot 天气查询插件（修复版）
支持城市天气查询和天气预报功能
修复：使用地理编码 API 获取经纬度，再调用 forecast API
支持配置文件自定义 API 地址和超时时间
"""

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
import httpx
import json
from typing import Optional
from functools import lru_cache
import os
import yaml


class AstroWeather(Star):
    """天气查询插件主类（修复版）"""

    def __init__(self, context: Context):
        super().__init__(context)
        # 加载配置文件
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        self.config = self._load_config(config_path)

        self.api_base = self.config.get("api_base", "https://api.open-meteo.com/v1")
        self.geocoding_api = self.config.get("geocoding_api", f"{self.api_base}/geocoding")
        self.timeout = self.config.get("timeout", 10)
        self.cache_enabled = self.config.get("cache_enabled", True)

        logger.info(f"天气查询插件已加载 (API: {self.api_base}, 超时: {self.timeout}s)")

    @filter.command("天气")
    async def get_weather(self, event: AstrMessageEvent, city: str = ""):
        """查询当前天气"""
        if not city:
            yield event.plain_result("请提供城市名称，例如：/天气 北京")
            return

        try:
            # 步骤 1：通过地理编码 API 获取经纬度
            logger.info(f"正在搜索城市：{city}")
            geo_url = self.geocoding_api
            geo_params = {
                "name": city,
                "count": 1,
                "language": "zh_cn",
                "format": "json"
            }

            async with httpx.AsyncClient() as client:
                geo_response = await client.get(geo_url, params=geo_params, timeout=self.timeout)
                geo_response.raise_for_status()
                geo_data = geo_response.json()

            # 检查地理编码是否成功
            if "results" not in geo_data or len(geo_data["results"]) == 0:
                yield event.plain_result(f"❌ 未找到城市：{city}\n💡 提示：\n   1. 请尝试输入更常见的城市名称（如'北京'、'上海'、'广州'）\n   2. 支持英文城市名（如'London'、'New York'）\n   3. 建议使用 2-3 个字的城市名以提高准确度")
                return

            # 获取第一个结果
            result = geo_data["results"][0]
            latitude = result.get("latitude", "N/A")
            longitude = result.get("longitude", "N/A")
            location_name = result.get("name", city)

            logger.info(f"找到城市：{location_name} (纬度:{latitude}, 经度:{longitude})")

            # 步骤 2：调用 forecast API（使用经纬度）
            url = f"{self.api_base}/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

            if "error" in data:
                error_msg = data['error']['message']
                if "city" in error_msg.lower() or "location" in error_msg.lower():
                    yield event.plain_result(f"❌ 查询失败：{error_msg}\n💡 提示：该城市暂不支持天气查询，请尝试其他城市")
                else:
                    yield event.plain_result(f"❌ 查询失败：{error_msg}")
                return

            # 解析天气数据
            current = data.get("current", {})
            daily = data.get("daily", [])

            temp = current.get("temperature_2m", "N/A")
            humidity = current.get("relative_humidity_2m", "N/A")
            wind = current.get("wind_speed_10m", "N/A")
            code = current.get("weather_code", 0)

            weather_desc = self._get_weather_desc(code)
            
            # 使用城市名而非经纬度作为日期
            date = location_name

            result = (
                f"🌍 {location_name}\n"
                f"🌡️ 温度：{temp}°C\n"
                f"💧 湿度：{humidity}%\n"
                f"💨 风速：{wind} km/h\n"
                f"☁️ 天气：{weather_desc}\n"
            )

            # 添加未来 3 天预报
            if daily and len(daily) > 1:
                result += "\n📅 未来 3 天预报：\n"
                for i in range(1, min(4, len(daily))):
                    date_str = daily["time"][i] if daily.get("time") and i < len(daily["time"]) else f"{i} 天后"
                    max_temp = daily.get("temperature_2m_max", [])[i] if daily.get("temperature_2m_max") and i < len(daily["temperature_2m_max"]) else "N/A"
                    min_temp = daily.get("temperature_2m_min", [])[i] if daily.get("temperature_2m_min") and i < len(daily["temperature_2m_min"]) else "N/A"
                    day_code = daily.get("weather_code", [])[i] if daily.get("weather_code") and i < len(daily["weather_code"]) else 0
                    day_desc = self._get_weather_desc(day_code)

                    result += f"{date_str}: {day_desc}, {min_temp}°C ~ {max_temp}°C\n"

            yield event.plain_result(result)

        except httpx.TimeoutException:
            yield event.plain_result("❌ 查询超时，请稍后再试")
        except httpx.HTTPStatusError as e:
            yield event.plain_result(f"❌ 查询失败：HTTP {e.response.status_code} - {str(e)}")
        except Exception as e:
            logger.error(f"天气查询错误：{e}")
            yield event.plain_result(f"❌ 查询失败：{str(e)}")

    @lru_cache(maxsize=self.config.get("cache_maxsize", 128))
    def _get_weather_desc(self, code: int) -> str:
        """根据天气代码获取描述（带缓存）"""
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

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        default_config = {
            "api_base": "https://api.open-meteo.com/v1",
            "geocoding_api": "https://api.open-meteo.com/v1/geocoding",
            "timeout": 10,
            "cache_enabled": True,
            "cache_maxsize": 128,
            "log_enabled": True
        }

        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = yaml.safe_load(f) or {}
                    return {**default_config, **user_config}
            except Exception as e:
                logger.warning(f"加载配置文件失败，使用默认配置: {e}")
        else:
            logger.info(f"配置文件不存在，使用默认配置: {config_path}")

        return default_config

    async def terminate(self):
        """插件卸载时的清理工作"""
        if self.cache_enabled:
            self._get_weather_desc.cache_clear()  # 清除缓存
        logger.info("天气查询插件已卸载")
