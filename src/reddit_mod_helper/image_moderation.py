"""Script aparte: busca posts con imagen en el subreddit configurado
(REDDIT_SUBREDDIT en .env) y le pide a Ollama (`gemma4:12b`, que soporta
visión) una descripción detallada de cada una.

Todavía no decide si la imagen rompe una regla — solo genera y guarda la
descripción, como paso previo para una futura moderación de imágenes (ver
`lib/prompt_imagen.md`, que ya le pide al modelo señalar contenido sensible).
"""

from __future__ import annotations

import base64
import logging
import sqlite3
from contextlib import closing
from string import Template

import requests
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape

from reddit_mod_helper.moderation import LIB_DIR, MODEL_NAME, OLLAMA_URL
from reddit_mod_helper.reddit_client import Post, RedditFetchError, fetch_new_posts
from reddit_mod_helper.state import (
    TABLA_IMAGENES_DESCRITAS,
    connect,
    descripcion_guardada,
    guardar_descripcion,
    purgar_antiguos,
)

logger = logging.getLogger(__name__)

PROMPT_IMAGEN_PATH = LIB_DIR / "prompt_imagen.md"
DESCARGA_TIMEOUT_SEGUNDOS = 30
DESCARGA_MAX_BYTES = 20 * 1024 * 1024  # 20MB, para no descargar algo absurdamente grande
# La visión es mucho más lenta que la moderación de solo texto: ~150s por
# imagen en pruebas reales (carga del proyector visual + una imagen grande).
DESCRIPCION_TIMEOUT_SEGUNDOS = 400


class ImagenError(Exception):
    """No se pudo descargar la imagen o describirla con Ollama."""


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=Console(stderr=True), show_path=False, markup=True)],
    )


def load_prompt_imagen_template() -> Template:
    return Template(PROMPT_IMAGEN_PATH.read_text(encoding="utf-8"))


def _descargar_imagen(url: str) -> bytes:
    try:
        response = requests.get(url, timeout=DESCARGA_TIMEOUT_SEGUNDOS)
        response.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise ImagenError(f"La descarga de la imagen tardó más de {DESCARGA_TIMEOUT_SEGUNDOS}s: {url}") from e
    except requests.exceptions.RequestException as e:
        raise ImagenError(f"No se pudo descargar la imagen ({url}): {e}") from e

    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise ImagenError(f"La URL no devolvió una imagen (Content-Type: {content_type!r}): {url}")

    contenido = response.content
    if len(contenido) > DESCARGA_MAX_BYTES:
        raise ImagenError(f"Imagen demasiado grande ({len(contenido)} bytes), se omite: {url}")

    return contenido


def describir_imagen(post: Post, prompt_template: Template) -> str:
    """Descarga la imagen del post y le pide a Ollama que la describa."""
    imagen_bytes = _descargar_imagen(post.url)
    imagen_b64 = base64.b64encode(imagen_bytes).decode("ascii")
    prompt = prompt_template.substitute(title=post.title)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "images": [imagen_b64],
                "stream": False,
            },
            timeout=DESCRIPCION_TIMEOUT_SEGUNDOS,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise ImagenError(
            f"Ollama no respondió en {DESCRIPCION_TIMEOUT_SEGUNDOS}s describiendo la imagen del post {post.id}"
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise ImagenError(f"No se pudo conectar a Ollama en {OLLAMA_URL} (¿está corriendo 'ollama serve'?)") from e
    except requests.exceptions.RequestException as e:
        raise ImagenError(f"Ollama respondió con un error describiendo la imagen del post {post.id}: {e}") from e

    try:
        return response.json()["response"].strip()
    except (ValueError, KeyError) as e:
        raise ImagenError(
            f"La respuesta de Ollama para la imagen del post {post.id} no tiene la forma esperada"
        ) from e


def main() -> None:
    _configure_logging()

    try:
        prompt_template = load_prompt_imagen_template()
    except OSError as e:
        logger.critical(
            "[bold red]No se pudo leer lib/prompt_imagen.md, se aborta la corrida:[/bold red] %s", escape(str(e))
        )
        raise SystemExit(1) from e

    try:
        posts = fetch_new_posts(limit=30)
    except RedditFetchError as e:
        logger.critical("[bold red]%s — se aborta la corrida[/bold red]", escape(str(e)))
        raise SystemExit(1) from e

    posts_de_imagen = [post for post in posts if post.is_image]
    logger.info("[dim]%d de %d posts tienen imagen[/dim]", len(posts_de_imagen), len(posts))

    procesados = 0
    fallidos = 0

    try:
        with closing(connect()) as conn:
            purgados = purgar_antiguos(conn, tabla=TABLA_IMAGENES_DESCRITAS)
            if purgados:
                logger.info("[dim]estado: %d descripción(es) de más de 3 días purgadas[/dim]", purgados)

            for post in posts_de_imagen:
                titulo = escape(post.title)
                try:
                    if descripcion_guardada(conn, post.id) is not None:
                        logger.info(
                            "[dim]ya descrita en una corrida anterior — %s (id=%s)[/dim]", titulo, post.id
                        )
                        continue

                    descripcion = describir_imagen(post, prompt_template)
                    guardar_descripcion(conn, post.id, descripcion)
                    procesados += 1
                    logger.info("[cyan]%s[/cyan] (id=%s) — %s", titulo, post.id, escape(descripcion))
                except ImagenError as e:
                    fallidos += 1
                    logger.error("[red]%s[/red] — se reintentará en la próxima corrida", escape(str(e)))
                except sqlite3.Error as e:
                    fallidos += 1
                    logger.error(
                        "[red]Fallo de estado (SQLite) con la imagen del post id=%s: %s — se reintentará[/red]",
                        post.id,
                        escape(str(e)),
                    )
                except Exception:
                    fallidos += 1
                    logger.exception(
                        "Error inesperado describiendo la imagen del post (id=%s), se reintentará en la próxima corrida",
                        post.id,
                    )
    finally:
        logger.info(
            "Corrida terminada: %d imagen(es) descrita(s), %d fallida(s) de %d con imagen",
            procesados,
            fallidos,
            len(posts_de_imagen),
        )
