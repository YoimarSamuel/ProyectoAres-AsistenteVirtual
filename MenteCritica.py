"""
================================================================================
        ARES v2.0 — Mente Crítica + Pipeline de Consolidación
================================================================================
Funciones:
  1. Validar antes de ingerir cualquier hecho global:
     - Filtro semántico contra absurdos conocidos
     - Detección de contradicción contra mejor concepto existente
     - Heurísticas de coherencia (longitud, gramática mínima, dominio)
  2. Calcular score de calidad inicial.
  3. Pipeline de consolidación que fusiona versiones del mismo concepto
     y promueve la mejor.
================================================================================
"""

from __future__ import annotations
import re
from typing import Dict, Any, Tuple, List
from icecream import ic

from BaseDeConocimiento import base_global, embed
import numpy as np


# Falacias / absurdos clásicos: si la afirmación se parece semánticamente
# a alguno de estos > umbral, se rechaza directamente.
FALACIAS_PROTOTIPO = [
    "los barcos sirven para volar",
    "el sol gira alrededor de la tierra",
    "las variables en python se declaran con html",
    "el agua arde",
    "los humanos pueden respirar bajo el agua sin equipo",
    "la luna es un planeta",
    "la tierra es plana",
    "los carros funcionan con magia",
    "las plantas comen carne todas",
    "el fuego es frío",
    "los pájaros nadan en lava",
]

# Pares de incompatibilidades fuertes (palabra A en concepto y palabra B
# en la afirmación → contradicción evidente).
#
# OJO: estas reglas tienen que ser ESTRICTAS. Si una palabra del par
# aparece naturalmente al describir el otro lado, dispararíamos un
# falso positivo. Por ejemplo, antes había ({"python","lenguaje"},
# {"html"}): describir HTML usa "lenguaje" + "html" de manera
# perfectamente legítima. Lo dejamos sólo en python ↔ html para captar
# la falacia "en python se programa con html".
INCOMPATIBILIDADES = [
    ({"barco", "barcos"},           {"volar", "vuela"}),
    ({"avión", "aviones"},          {"nadar"}),
    ({"python"},                     {"html"}),
    ({"agua"},                       {"arde", "inflamable"}),
    ({"sol"},                        {"frío", "helado"}),
    ({"hielo"},                      {"caliente", "ardiente"}),
]

UMBRAL_FALACIA       = 0.78  # similitud con falacia conocida
UMBRAL_CONTRADICCION = 0.85  # similitud entre concepto existente y nuevo
                             # con sentidos opuestos detectados léxicamente


# ============================== UTILIDADES ==============================
def _cosine(a: List[float], b: List[float]) -> float:
    av, bv = np.array(a), np.array(b)
    na, nb = np.linalg.norm(av), np.linalg.norm(bv)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(av, bv) / (na * nb))


def _tokens(s: str) -> set:
    return set(re.findall(r"[a-záéíóúñ]+", s.lower()))


# ============================== MENTE CRÍTICA ==============================
class MenteCritica:

    def __init__(self):
        ic("Inicializando Mente Crítica…")
        # Pre-embed falacias para comparación rápida
        self._embeds_falacias = [embed(f) for f in FALACIAS_PROTOTIPO]
        ic(f" Mente Crítica lista — {len(FALACIAS_PROTOTIPO)} falacias prototipo")

    # ---------- VALIDACIÓN ----------
    def evaluar(self, tema: str, descripcion: str) -> Dict[str, Any]:
        """
        Devuelve:
          {
            'aceptado': bool,
            'razon': str,
            'calidad': float (0..1),
            'confianza': float (0..1)
          }
        """
        tema = (tema or "").strip()
        descripcion = (descripcion or "").strip()
        afirmacion = f"{tema}: {descripcion}"

        # 0) Filtro de mensajes basura conocidos (bot-blocks, errores)
        BASURA = [
            "trouble accessing google",
            "send feedback",
            "captcha",
            "tener problemas para acceder",
            "javascript is required",
            "tráfico inusual",
            "unusual traffic",
            "página no encontrada",
            "404 not found",
            "500 internal server"
        ]
        d_low = descripcion.lower()
        for b in BASURA:
            if b in d_low:
                return {"aceptado": False,
                        "razon": f"Mensaje basura/bot-block: '{b}'",
                        "calidad": 0.0, "confianza": 1.0}

        # 1) Reglas duras
        if len(descripcion) < 5:
            return {"aceptado": False,
                    "razon": "Descripción demasiado corta",
                    "calidad": 0.0, "confianza": 1.0}

        if not re.search(r"[a-záéíóúñ]", descripcion.lower()):
            return {"aceptado": False,
                    "razon": "Sin contenido textual válido",
                    "calidad": 0.0, "confianza": 1.0}

        # 2) Incompatibilidades léxicas
        tokens_afirm = _tokens(afirmacion)
        for grupo_a, grupo_b in INCOMPATIBILIDADES:
            if grupo_a & tokens_afirm and grupo_b & tokens_afirm:
                return {
                    "aceptado": False,
                    "razon": f"Incompatibilidad léxica: {grupo_a & tokens_afirm} ↔ {grupo_b & tokens_afirm}",
                    "calidad": 0.0, "confianza": 0.95
                }

        # 3) Similitud con falacias prototipo
        emb_afirm = embed(afirmacion)
        max_sim_falacia = 0.0
        for ef in self._embeds_falacias:
            s = _cosine(emb_afirm, ef)
            if s > max_sim_falacia:
                max_sim_falacia = s

        if max_sim_falacia >= UMBRAL_FALACIA:
            return {
                "aceptado": False,
                "razon": f"Similitud {max_sim_falacia:.2f} con falacia conocida",
                "calidad": 0.0, "confianza": 0.9
            }

        # 4) Contradicción con concepto consolidado existente
        existente = base_global.mejor_concepto(tema)
        if existente:
            sim_emb = _cosine(
                emb_afirm,
                embed(f"{existente['tema']}: {existente['descripcion']}")
            )
            # Si misma área pero negaciones opuestas detectadas → contradicción
            negs_a = bool(re.search(r"\b(no|nunca|jamás|never)\b",
                                     descripcion.lower()))
            negs_b = bool(re.search(r"\b(no|nunca|jamás|never)\b",
                                     existente["descripcion"].lower()))
            if sim_emb >= UMBRAL_CONTRADICCION and (negs_a != negs_b):
                if existente["calidad"] >= 0.7 and existente["confirmaciones"] >= 2:
                    return {
                        "aceptado": False,
                        "razon": "Contradice concepto consolidado",
                        "calidad": 0.1, "confianza": 0.85
                    }

        # 5) Calcular calidad inicial
        calidad = self._calidad_inicial(tema, descripcion)

        return {
            "aceptado": True,
            "razon":    "OK",
            "calidad":  calidad,
            "confianza": 0.7 + 0.2 * (1 - max_sim_falacia)
        }

    def _calidad_inicial(self, tema: str, descripcion: str) -> float:
        """Heurística de calidad inicial (0..1)."""
        score = 0.5

        n_palabras = len(descripcion.split())
        if 8 <= n_palabras <= 60:    score += 0.15
        elif n_palabras > 60:         score += 0.10

        if descripcion.endswith("."): score += 0.05
        if re.search(r"[A-ZÁÉÍÓÚÑ]", descripcion): score += 0.05
        if re.search(r"\d", descripcion):        score += 0.05  # menciona datos

        # Vocabulario técnico (más calidad si el tema es técnico)
        TECNICO = {"python", "javascript", "algoritmo", "función", "clase",
                   "variable", "html", "css", "memoria", "cpu", "objeto",
                   "embedding", "vector", "modelo", "neural", "api"}
        if _tokens(tema) & TECNICO:
            score += 0.15

        return max(0.0, min(1.0, score))

    # ---------- CONSOLIDACIÓN ----------
    def consolidar(self, tema: str) -> Dict[str, Any]:
        """
        Recorre todas las versiones de un concepto y selecciona la mejor.
        Devuelve {'mejor': dict, 'descartadas': int}.
        """
        candidatos = base_global.buscar_concepto(tema, n=15)
        if not candidatos:
            return {"mejor": None, "descartadas": 0}

        for c in candidatos:
            # Score de consolidación (ponderado)
            c["_score"] = (
                0.40 * c["similitud"]
                + 0.40 * c["calidad"]
                + 0.20 * min(1.0, c["confirmaciones"] / 5.0)
            )
        candidatos.sort(key=lambda x: x["_score"], reverse=True)
        mejor = candidatos[0]

        ic(f" Consolidación tema='{tema}': mejor calidad={mejor['calidad']:.2f} "
           f"conf={mejor['confirmaciones']}")
        return {
            "mejor": mejor,
            "descartadas": max(0, len(candidatos) - 1)
        }


# ============================== INSTANCIA ==============================
mente_critica = MenteCritica()
