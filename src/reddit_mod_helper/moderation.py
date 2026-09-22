"""Evaluación de posts contra las reglas del subreddit, vía un modelo local en Ollama."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

import requests
from rich.markup import escape

from reddit_mod_helper.reddit_client import Post

logger = logging.getLogger(__name__)

LIB_DIR = Path(__file__).resolve().parent.parent.parent / "lib"
RULES_PATH = LIB_DIR / "rules.MD"
PROMPT_PATH = LIB_DIR / "prompt.md"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gemma4:12b"
OLLAMA_TIMEOUT_SEGUNDOS = 300

# Reglas que dependen del día en que se publicó el post (ej. "offtopic solo
# los viernes") no del día en que corre este script. Se calcula en la zona
# horaria local del subreddit (REDDIT_TIMEZONE en .env, formato IANA), no
# UTC — un post publicado tarde en la noche en esa zona podría caer ya en
# el día siguiente si se calculara en UTC.
ZONA_HORARIA_LOCAL = ZoneInfo(os.environ.get("REDDIT_TIMEZONE", "UTC"))
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def dia_semana_de(created_utc: float) -> str:
    fecha = datetime.fromtimestamp(created_utc, tz=ZONA_HORARIA_LOCAL)
    return DIAS_ES[fecha.weekday()]


class OllamaError(Exception):
    """Ollama no respondió a tiempo, respondió con error, o devolvió algo inutilizable."""


def load_rules() -> str:
    return RULES_PATH.read_text(encoding="utf-8")


def load_prompt_template() -> Template:
    """Carga la plantilla del prompt desde lib/prompt.md.

    Usa $rules/$title/$body (string.Template) en vez de {rules}/{title}/{body}
    (str.format) para que el JSON de ejemplo dentro del archivo no necesite
    escapar sus llaves — así se puede editar el prompt sin tocar código ni
    preocuparse por sintaxis de Python.
    """
    return Template(PROMPT_PATH.read_text(encoding="utf-8"))


def build_prompt(rules: str, post: Post, prompt_template: Template) -> str:
    body = post.body if post.body else "(sin contenido de texto, el post es un link/imagen/video)"
    return prompt_template.substitute(
        rules=rules,
        title=post.title,
        body=body,
        dia_semana=dia_semana_de(post.created_utc),
    )


def evaluate_post(post: Post, rules: str, prompt_template: Template) -> dict:
    """Evalúa un post contra las reglas usando Ollama.

    prawcore ya trae su propio timeout por defecto (16s, ver
    prawcore.const.TIMEOUT) para las llamadas a Reddit, pero la librería
    `requests` que usamos aquí para hablar con Ollama no tiene ninguno por
    defecto — sin `timeout` explícito, una respuesta colgada (modelo
    trabado, VRAM saturada, etc.) bloquearía el proceso indefinidamente.
    """
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": build_prompt(rules, post, prompt_template),
                "stream": False,
                "format": "json",
            },
            timeout=OLLAMA_TIMEOUT_SEGUNDOS,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise OllamaError(
            f"Ollama no respondió en {OLLAMA_TIMEOUT_SEGUNDOS}s para el post {post.id} "
            "(¿el modelo está trabado o la máquina está saturada?)"
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(
            f"No se pudo conectar a Ollama en {OLLAMA_URL} (¿está corriendo 'ollama serve'?)"
        ) from e
    except requests.exceptions.RequestException as e:
        raise OllamaError(f"Ollama respondió con un error para el post {post.id}: {e}") from e

    try:
        raw = response.json()["response"]
    except (ValueError, KeyError) as e:
        raise OllamaError(
            f"La respuesta de Ollama para el post {post.id} no tiene la forma esperada"
        ) from e

    logger.info("[dim]Respuesta cruda de Ollama para el post %s: %s[/dim]", post.id, escape(raw))

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama devolvió un JSON inválido para el post {post.id}: {raw!r}") from e
