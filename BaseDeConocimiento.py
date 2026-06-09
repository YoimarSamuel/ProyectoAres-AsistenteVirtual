"""
================================================================================
        ARES v2.0 — Base de Conocimiento Híbrida (Global + Privada)
================================================================================
Arquitectura:
  GLOBAL  → ChromaDB compartido en `data/conocimiento_global/`
            Almacena: conceptos técnicos, hechos, conocimiento académico.
            Lo aporta CADA usuario y se valida con MenteCritica.
            Cada concepto guarda múltiples versiones; la mejor se elige
            por consenso (calidad + número de confirmaciones).

  PRIVADA → ChromaDB por-usuario en `data/usuarios/<u>/conocimiento/`
            Almacena: rostros, perfiles cercanos, historial conversacional,
            preferencias, datos personales. CIFRADA con Fernet del usuario.
================================================================================
"""

from __future__ import annotations
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

import chromadb
from sentence_transformers import SentenceTransformer
from icecream import ic

from Auth import auth, USUARIOS_DIR

BASE_DIR = Path(__file__).parent
GLOBAL_DIR = BASE_DIR / "data" / "conocimiento_global"
GLOBAL_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDINGS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# ============================== EMBEDDER COMPARTIDO ==============================
_embedder: Optional[SentenceTransformer] = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        ic("Cargando modelo de embeddings…")
        _embedder = SentenceTransformer(EMBEDDINGS_MODEL)
    return _embedder


def embed(text: str) -> List[float]:
    emb = get_embedder().encode(text)
    return emb.tolist() if hasattr(emb, "tolist") else list(emb)


# ============================== BASE GLOBAL ==============================
class BaseGlobal:
    """
    Conocimiento técnico/académico compartido entre TODOS los usuarios.
    Cada concepto es un cluster: múltiples 'versiones' coexisten y la
    fusión + ranking se hace en `MenteCritica.consolidar()`.
    """

    def __init__(self):
        ic("Inicializando Base Global…")
        self.client = chromadb.PersistentClient(path=str(GLOBAL_DIR))

        # Conceptos: cada item = una afirmación sobre un tema
        self.conceptos = self.client.get_or_create_collection(
            name="conceptos_globales",
            metadata={"hnsw:space": "cosine"}
        )

        # Conceptos rechazados (auditoría de mente crítica)
        self.rechazados = self.client.get_or_create_collection(
            name="conceptos_rechazados",
            metadata={"hnsw:space": "cosine"}
        )

        ic(f" Base Global lista — {self.conceptos.count()} conceptos")

    # ---------- API: añadir hecho ----------
    def agregar_hecho(self, tema: str, descripcion: str,
                      autor_username: str,
                      calidad: float = 0.5,
                      fuente: str = "usuario",
                      tono: str = "balanceado") -> str:
        """
        Inserta un hecho candidato. La validación previa la hace MenteCritica.

        El parámetro `tono` indica con qué configuración de respuesta se
        aprendió este hecho. Permite que la BD devuelva la variante más
        adecuada al tono activo del usuario que pregunta.
        """
        doc_id = f"{tema.lower().strip().replace(' ', '_')}_" \
                 f"{int(time.time() * 1000)}"

        texto = f"{tema}: {descripcion}"
        emb = embed(texto)

        # Generar variantes pre-adaptadas a cada tono. Así, al recuperar,
        # podemos devolver la versión más natural sin recortar en caliente.
        try:
            from Cognicion import adaptar_respuesta_a_tono
            variantes = {
                "balanceado": adaptar_respuesta_a_tono(descripcion, "balanceado"),
                "tranquilo":  adaptar_respuesta_a_tono(descripcion, "tranquilo"),
                "analitico":  adaptar_respuesta_a_tono(descripcion, "analitico"),
                "directo":    adaptar_respuesta_a_tono(descripcion, "directo"),
            }
        except Exception:
            variantes = {}

        metadata = {
            "tema":         tema.lower().strip(),
            "descripcion":  descripcion,
            "autor":        autor_username,
            "calidad":      float(calidad),
            "confirmaciones": 1,
            "fuente":       fuente,
            "tono_origen":  tono if tono in {"balanceado", "tranquilo",
                                              "analitico", "directo"}
                            else "balanceado",
            # Chroma sólo acepta tipos primitivos en metadatos: serializamos
            # las variantes como JSON para preservar la estructura.
            "variantes_tono": json.dumps(variantes, ensure_ascii=False)
                              if variantes else "",
            "timestamp":    datetime.now().isoformat()
        }

        self.conceptos.add(
            ids=[doc_id],
            embeddings=[emb],
            metadatas=[metadata],
            documents=[texto]
        )
        ic(f" Hecho global añadido: {tema} (autor={autor_username}, tono={tono})")
        return doc_id

    def registrar_rechazo(self, tema: str, descripcion: str,
                          autor_username: str, razon: str) -> None:
        """Auditar conocimiento rechazado por la mente crítica."""
        doc_id = f"rechazo_{int(time.time() * 1000)}"
        emb = embed(f"{tema}: {descripcion}")

        self.rechazados.add(
            ids=[doc_id],
            embeddings=[emb],
            metadatas=[{
                "tema":        tema.lower().strip(),
                "descripcion": descripcion,
                "autor":       autor_username,
                "razon":       razon,
                "timestamp":   datetime.now().isoformat()
            }],
            documents=[f"RECHAZADO {tema}: {descripcion}"]
        )
        ic(f" Conocimiento rechazado: {tema} (razón: {razon})")

    # ---------- API: consultar concepto ----------
    def buscar_concepto(self, query: str, n: int = 5) -> List[Dict[str, Any]]:
        """Recupera hechos similares al query, ordenados por relevancia."""
        try:
            emb = embed(query)
            res = self.conceptos.query(query_embeddings=[emb], n_results=n)
            out = []
            if res["metadatas"]:
                for meta, doc, dist in zip(res["metadatas"][0],
                                            res["documents"][0],
                                            res.get("distances", [[0]])[0]):
                    out.append({
                        "tema":          meta.get("tema"),
                        "descripcion":   meta.get("descripcion"),
                        "autor":         meta.get("autor"),
                        "calidad":       meta.get("calidad", 0.5),
                        "confirmaciones": meta.get("confirmaciones", 1),
                        "fuente":        meta.get("fuente"),
                        "tono_origen":   meta.get("tono_origen", "balanceado"),
                        "variantes_tono": meta.get("variantes_tono", ""),
                        "similitud":     1 - float(dist)
                    })
            return out
        except Exception as e:
            ic(f"Error buscar_concepto: {e}")
            return []

    def mejor_concepto(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Devuelve el MEJOR hecho conocido sobre un tema.

        Estrategia (en orden de prioridad):
          1. Coincidencia EXACTA por tema (insensible a may/min). Esto evita
             que "html" devuelva un concepto guardado de "css" solo porque
             ambos hablan de webs.
          2. Si no hay match exacto, usa similitud vectorial pero EXIGE que
             la descripción mencione el término clave de la consulta.

        Score (cuando hay candidatos): similitud + calidad + confirmaciones.
        """
        import math
        import re

        consulta = (query or "").strip().lower()
        if not consulta:
            return None

        # 1) Lookup por tema exacto (rápido y preciso). Usa el normalizador
        # centralizado para que todas las variantes ("dime qué es X",
        # "explícame X", "cuéntame de X", "qué significa X"...) colapsen
        # al mismo tema y matcheen la fila guardada.
        try:
            from PLNOptimizado import normalizar_consulta
            tema_clave = normalizar_consulta(consulta)
        except Exception:
            tema_clave = re.sub(
                r"^(qué\s+es|que\s+es|qué|que|busca|investiga|dime\s+sobre|"
                r"explícame|explicame|quién\s+es|quien\s+es|cuál\s+es|cual\s+es|"
                r"averigua|definición\s+de|definicion\s+de|significado\s+de)\s+",
                "", consulta, flags=re.IGNORECASE
            ).strip(" ¿?¡!.,;:")
            tema_clave = re.sub(r"^(un|una|el|la|los|las)\s+", "",
                                 tema_clave, flags=re.IGNORECASE)

        if tema_clave:
            try:
                exactos = self.conceptos.get(where={"tema": tema_clave})
                metas = exactos.get("metadatas") or []
                if metas:
                    # Elegir el de mayor calidad·confirmaciones
                    metas.sort(
                        key=lambda m: (m.get("calidad", 0.5)
                                       * (1 + m.get("confirmaciones", 1))),
                        reverse=True
                    )
                    m = metas[0]
                    return {
                        "tema":          m.get("tema"),
                        "descripcion":   m.get("descripcion"),
                        "autor":         m.get("autor"),
                        "calidad":       m.get("calidad", 0.5),
                        "confirmaciones": m.get("confirmaciones", 1),
                        "fuente":        m.get("fuente"),
                        "tono_origen":   m.get("tono_origen", "balanceado"),
                        "variantes_tono": m.get("variantes_tono", ""),
                        "similitud":     1.0,
                        "_match":        "tema_exacto"
                    }
            except Exception as e:
                ic(f" lookup exacto: {e}")

        # 2) Recuperación vectorial con validación de pertinencia.
        # Solo aceptamos un candidato si sus tokens significativos son
        # iguales a los del query, o si el candidato CONTIENE todos los del
        # query (caso "django" preguntado con guardado "django python").
        # NUNCA aceptamos al revés ("listas en python" → "python").
        candidatos = self.buscar_concepto(query, n=8)
        if not candidatos:
            return None

        STOPWORDS = {"en", "de", "del", "la", "el", "los", "las", "un",
                      "una", "y", "o", "para", "con", "por", "que", "es",
                      "son", "como", "cómo"}

        def _signif(tokens):
            return {t for t in tokens if t not in STOPWORDS}

        tokens_q = _signif(set(re.findall(r"[a-záéíóúñ0-9]{2,}",
                                            tema_clave or consulta)))
        if tokens_q:
            filtrados = []
            for c in candidatos:
                tema_c = (c.get("tema") or "").lower()
                tokens_c = _signif(set(re.findall(r"[a-záéíóúñ0-9]{2,}", tema_c)))
                if not tokens_c:
                    continue
                # OK si tokens del query están todos en el candidato.
                # Esto cubre: tokens_q == tokens_c y tokens_q ⊂ tokens_c.
                if tokens_q.issubset(tokens_c):
                    filtrados.append(c)
            if filtrados:
                candidatos = filtrados
            else:
                # Sin match estructural → mejor decir "no sé".
                return None

        for c in candidatos:
            c["_score"] = (
                0.45 * c["similitud"]
                + 0.35 * c["calidad"]
                + 0.20 * (math.log1p(c["confirmaciones"]) / 3.0)
            )
        candidatos.sort(key=lambda x: x["_score"], reverse=True)
        return candidatos[0]

    @staticmethod
    def descripcion_para_tono(concepto: Dict[str, Any], tono: str) -> str:
        """
        Devuelve la versión de la descripción más adecuada al tono pedido.

        Estrategia:
          1. Si el concepto trae `variantes_tono` (JSON con balanceado/
             tranquilo/analitico/directo) y existe la del tono pedido,
             se usa esa.
          2. Si no, se adapta la descripción principal en caliente.
          3. Como último recurso se devuelve la descripción tal cual.
        """
        if not concepto:
            return ""
        descripcion = concepto.get("descripcion") or ""
        variantes_raw = concepto.get("variantes_tono") or ""
        variantes: Dict[str, str] = {}
        if variantes_raw:
            try:
                variantes = json.loads(variantes_raw)
            except Exception:
                variantes = {}
        tono_norm = tono if tono in {"balanceado", "tranquilo",
                                       "analitico", "directo"} else "balanceado"
        if variantes.get(tono_norm):
            return variantes[tono_norm]
        try:
            from Cognicion import adaptar_respuesta_a_tono
            return adaptar_respuesta_a_tono(descripcion, tono_norm)
        except Exception:
            return descripcion

    def confirmar_concepto(self, tema: str, descripcion: str) -> None:
        """Incrementa el contador de confirmaciones para un hecho existente."""
        try:
            res = self.conceptos.get(where={"tema": tema.lower().strip()})
            if not res["ids"]:
                return
            for cid, meta in zip(res["ids"], res["metadatas"]):
                if meta.get("descripcion") == descripcion:
                    meta["confirmaciones"] = meta.get("confirmaciones", 1) + 1
                    meta["calidad"] = min(
                        1.0, meta.get("calidad", 0.5) + 0.05
                    )
                    self.conceptos.update(ids=[cid], metadatas=[meta])
                    ic(f" Confirmado: {tema} (+1)")
                    return
        except Exception as e:
            ic(f"Error confirmar_concepto: {e}")

    def estadisticas(self) -> Dict[str, int]:
        return {
            "total_conceptos":  self.conceptos.count(),
            "total_rechazados": self.rechazados.count()
        }


# ============================== BASE PRIVADA ==============================
class BasePrivada:
    """
    Conocimiento privado por usuario (CIFRADO).
    Almacena: rostros, contactos cercanos, historial, preferencias.
    Sólo accesible cuando el usuario está autenticado.
    """

    def __init__(self):
        self._client = None
        self._username = None
        ic(" BasePrivada inicializada (multitenant lazy)")

    def _ensure(self):
        """Conecta perezosamente al ChromaDB del usuario activo."""
        if not auth.autenticado:
            raise PermissionError("Usuario no autenticado")

        if self._username == auth.usuario_actual and self._client is not None:
            return

        self._username = auth.usuario_actual
        path = USUARIOS_DIR / self._username / "conocimiento"
        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(path))

        self.interacciones = self._client.get_or_create_collection(
            name="interacciones_privadas",
            metadata={"hnsw:space": "cosine"}
        )
        self.personas = self._client.get_or_create_collection(
            name="personas_privadas",
            metadata={"hnsw:space": "cosine"}
        )
        self.preferencias = self._client.get_or_create_collection(
            name="preferencias",
            metadata={"hnsw:space": "cosine"}
        )

    # ---------- INTERACCIONES PRIVADAS (cifradas) ----------
    def guardar_interaccion(self, entrada: str, respuesta: str,
                            metadatos: Dict[str, Any] = None) -> str:
        self._ensure()

        # Cifrar contenido sensible
        entrada_cif    = auth.cifrar(entrada)    or entrada
        respuesta_cif  = auth.cifrar(respuesta) or respuesta

        # Embedding sobre TEXTO CLARO (en RAM) para que la búsqueda funcione
        emb = embed(f"{entrada} | {respuesta}")

        doc_id = f"int_{int(time.time() * 1000)}_" \
                 f"{hashlib.md5(entrada.encode()).hexdigest()[:6]}"

        meta = {
            "entrada_cif":   entrada_cif,
            "respuesta_cif": respuesta_cif,
            "timestamp":     datetime.now().isoformat(),
            **(metadatos or {})
        }

        self.interacciones.add(
            ids=[doc_id],
            embeddings=[emb],
            metadatas=[meta],
            documents=[doc_id]  # documento opaco
        )
        ic(f" Interacción privada guardada: {doc_id}")
        return doc_id

    def buscar_interacciones(self, query: str, n: int = 3) -> List[Dict[str, Any]]:
        """Recupera interacciones privadas y las descifra en memoria."""
        self._ensure()
        try:
            emb = embed(query)
            res = self.interacciones.query(query_embeddings=[emb], n_results=n)
            out = []
            if res["metadatas"]:
                for meta in res["metadatas"][0]:
                    out.append({
                        "entrada":   auth.descifrar(meta.get("entrada_cif", "")) or "[cifrado]",
                        "respuesta": auth.descifrar(meta.get("respuesta_cif", "")) or "[cifrado]",
                        "timestamp": meta.get("timestamp")
                    })
            return out
        except Exception as e:
            ic(f"Error buscar_interacciones: {e}")
            return []

    # ---------- PERSONAS PRIVADAS ----------
    def guardar_persona(self, nombre: str, datos: Dict[str, Any]) -> None:
        self._ensure()
        descripcion_clara = f"{nombre}: " + " · ".join(
            f"{k}={v}" for k, v in datos.items()
        )
        descripcion_cif = auth.cifrar(descripcion_clara) or descripcion_clara

        emb = embed(descripcion_clara)
        self.personas.upsert(
            ids=[nombre.lower().strip()],
            embeddings=[emb],
            metadatas=[{
                "nombre":     nombre,
                "datos_cif":  descripcion_cif,
                "timestamp":  datetime.now().isoformat()
            }],
            documents=[nombre]
        )
        ic(f" Persona guardada: {nombre}")

    def buscar_persona(self, query: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        try:
            emb = embed(query)
            res = self.personas.query(query_embeddings=[emb], n_results=1)
            if res["metadatas"] and res["metadatas"][0]:
                meta = res["metadatas"][0][0]
                return {
                    "nombre": meta.get("nombre"),
                    "datos":  auth.descifrar(meta.get("datos_cif", "")) or "[cifrado]"
                }
        except Exception as e:
            ic(f"Error buscar_persona: {e}")
        return None

    # ---------- ATRIBUTOS PERSONALES (clave-valor cifrado) ----------
    def set_atributo(self, clave: str, valor: str) -> bool:
        """
        Guarda un dato personal cifrado por clave (gustos, hobbies,
        alergias, color favorito...). Reemplaza si ya existía.
        """
        self._ensure()
        clave = (clave or "").strip().lower()
        if not clave or not valor:
            return False
        try:
            valor_cif = auth.cifrar(valor) or valor
            emb = embed(f"{clave}: {valor}")
            self.preferencias.upsert(
                ids=[clave],
                embeddings=[emb],
                metadatas=[{
                    "clave":     clave,
                    "valor_cif": valor_cif,
                    "timestamp": datetime.now().isoformat()
                }],
                documents=[clave]
            )
            ic(f" Atributo guardado: {clave}")
            return True
        except Exception as e:
            ic(f"Error set_atributo: {e}")
            return False

    def get_atributo(self, clave: str) -> Optional[str]:
        """Recupera un atributo personal por clave (lo descifra)."""
        self._ensure()
        clave = (clave or "").strip().lower()
        if not clave:
            return None
        try:
            res = self.preferencias.get(ids=[clave])
            if res and res.get("metadatas"):
                meta = res["metadatas"][0]
                return auth.descifrar(meta.get("valor_cif", "")) or None
        except Exception as e:
            ic(f"Error get_atributo: {e}")
        return None

    def listar_atributos(self) -> Dict[str, str]:
        """Devuelve un dict con todos los atributos personales descifrados."""
        self._ensure()
        out: Dict[str, str] = {}
        try:
            res = self.preferencias.get()
            for meta in (res.get("metadatas") or []):
                clave = meta.get("clave")
                if clave:
                    out[clave] = auth.descifrar(meta.get("valor_cif", "")) or ""
        except Exception as e:
            ic(f"Error listar_atributos: {e}")
        return out

    # ---------- ESTADÍSTICAS ----------
    def estadisticas(self) -> Dict[str, int]:
        if not auth.autenticado:
            return {"total_interacciones": 0, "total_personas": 0}
        self._ensure()
        return {
            "total_interacciones": self.interacciones.count(),
            "total_personas":      self.personas.count(),
            "total_atributos":     self.preferencias.count()
        }


# ============================== INSTANCIAS ==============================
base_global  = BaseGlobal()
base_privada = BasePrivada()
