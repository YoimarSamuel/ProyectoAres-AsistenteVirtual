"""
================================================================================
        ARES v2.0 — Telemetría: System Stats + Weather + Uptime
================================================================================
"""

from __future__ import annotations
import time
import shutil
from datetime import datetime
from typing import Dict, Any
from icecream import ic

import psutil
import requests


_SESION_INICIO = time.time()
_COMANDOS_EJECUTADOS = 0


def incrementar_comandos() -> None:
    global _COMANDOS_EJECUTADOS
    _COMANDOS_EJECUTADOS += 1


# ============================== SISTEMA ==============================
def stats_sistema() -> Dict[str, Any]:
    """CPU + RAM + Disco."""
    try:
        cpu = psutil.cpu_percent(interval=0.0)
        ram = psutil.virtual_memory()
        disk_total, disk_used, disk_free = shutil.disk_usage("/")

        return {
            "cpu": {
                "percent": cpu,
                "cores":   psutil.cpu_count(logical=True)
            },
            "ram": {
                "percent": ram.percent,
                "usado_gb": round(ram.used / (1024**3), 1),
                "total_gb": round(ram.total / (1024**3), 1)
            },
            "disco": {
                "usado_gb": round(disk_used / (1024**3), 1),
                "total_gb": round(disk_total / (1024**3), 1),
                "percent":  round(100 * disk_used / disk_total, 1)
            },
            "load_general": min(100, (cpu + ram.percent) / 2)
        }
    except Exception as e:
        ic(f" stats_sistema: {e}")
        return {"error": str(e)}


def uptime() -> Dict[str, Any]:
    """Tiempo de sesión + comandos."""
    secs = int(time.time() - _SESION_INICIO)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return {
        "segundos": secs,
        "formateado": f"{h:02d}:{m:02d}:{s:02d}",
        "comandos_ejecutados": _COMANDOS_EJECUTADOS
    }


# ============================== WEATHER ==============================
_WEATHER_CACHE = {"ts": 0, "data": None}
_WEATHER_TTL = 600  # 10 min


def obtener_clima(ciudad: str = "auto") -> Dict[str, Any]:
    """
    Usa Open-Meteo + IP-geolocation (sin API key).
    Cachea 10 minutos.
    """
    now = time.time()
    if (_WEATHER_CACHE["data"]
            and now - _WEATHER_CACHE["ts"] < _WEATHER_TTL):
        return _WEATHER_CACHE["data"]

    try:
        # 1) Geolocalizar por IP si ciudad='auto'
        if ciudad == "auto":
            geo = requests.get("https://ipapi.co/json/", timeout=6).json()
            lat, lon = geo.get("latitude"), geo.get("longitude")
            ciudad_nombre = geo.get("city", "Desconocida")
            pais = geo.get("country_name", "")
        else:
            g = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": ciudad, "count": 1, "language": "es"},
                timeout=6
            ).json()
            if not g.get("results"):
                return {"error": f"Ciudad no encontrada: {ciudad}"}
            r0 = g["results"][0]
            lat, lon = r0["latitude"], r0["longitude"]
            ciudad_nombre = r0.get("name", ciudad)
            pais = r0.get("country", "")

        # 2) Tiempo actual
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,"
                            "wind_speed_10m,apparent_temperature,"
                            "weather_code",
                "timezone": "auto"
            },
            timeout=6
        ).json()

        cur = w.get("current", {})
        codigo = cur.get("weather_code", 0)
        data = {
            "ciudad":      ciudad_nombre,
            "pais":        pais,
            "temperatura": cur.get("temperature_2m"),
            "sensacion":   cur.get("apparent_temperature"),
            "humedad":     cur.get("relative_humidity_2m"),
            "viento":      cur.get("wind_speed_10m"),
            "codigo":      codigo,
            "descripcion": _wmo_a_descripcion(codigo)
        }
        _WEATHER_CACHE["ts"] = now
        _WEATHER_CACHE["data"] = data
        return data

    except Exception as e:
        ic(f" Weather error: {e}")
        return {"error": str(e)}


def _wmo_a_descripcion(code: int) -> str:
    tabla = {
        0: "Despejado", 1: "Mayormente despejado",
        2: "Parcialmente nublado", 3: "Nublado",
        45: "Niebla", 48: "Niebla escarchada",
        51: "Llovizna ligera", 53: "Llovizna", 55: "Llovizna densa",
        61: "Lluvia ligera", 63: "Lluvia", 65: "Lluvia fuerte",
        71: "Nieve ligera", 73: "Nieve", 75: "Nieve fuerte",
        80: "Chubascos", 81: "Chubascos fuertes", 82: "Chubascos violentos",
        95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta severa"
    }
    return tabla.get(code, "Desconocido")


# ============================== FECHA / HORA ==============================
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
          "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def hora_actual(formato_24h: bool = True) -> Dict[str, Any]:
    """Devuelve la hora local en formato hablable y técnico."""
    now = datetime.now()
    if formato_24h:
        hablado = now.strftime("%H:%M")
    else:
        h12 = now.strftime("%I:%M").lstrip("0") or "12:00"
        sufijo = "a. m." if now.hour < 12 else "p. m."
        hablado = f"{h12} {sufijo}"
    return {
        "iso": now.isoformat(timespec="seconds"),
        "hora": now.strftime("%H:%M:%S"),
        "hablado": hablado
    }


def fecha_actual() -> Dict[str, Any]:
    """Devuelve la fecha local en español, sin depender de locale del SO."""
    now = datetime.now()
    dia_semana = _DIAS[now.weekday()]
    mes = _MESES[now.month - 1]
    hablado = f"{dia_semana} {now.day} de {mes} de {now.year}"
    return {
        "iso": now.date().isoformat(),
        "dia_semana": dia_semana,
        "dia": now.day,
        "mes": mes,
        "anio": now.year,
        "hablado": hablado
    }


def formato_clima_humano(d: Dict[str, Any]) -> str:
    """Convierte el dict de `obtener_clima` en una frase corta y natural."""
    if not d or d.get("error"):
        return "No pude obtener el clima ahora mismo."
    desc = d.get("descripcion") or ""
    temp = d.get("temperatura")
    sens = d.get("sensacion")
    hum = d.get("humedad")
    ciudad = d.get("ciudad") or ""
    partes = []
    if ciudad:
        partes.append(f"En {ciudad}")
    if desc:
        partes.append(desc.lower() if not partes else f", {desc.lower()}")
    if temp is not None:
        partes.append(f", {round(temp)}°C")
    if sens is not None and abs((sens or 0) - (temp or 0)) >= 2:
        partes.append(f" (sensación {round(sens)}°C)")
    if hum is not None:
        partes.append(f", humedad {hum}%")
    return "".join(partes).strip(", ").capitalize() + "."
