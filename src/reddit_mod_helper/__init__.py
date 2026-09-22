import logging
import sqlite3
from contextlib import closing
from string import Template

import praw
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape

from reddit_mod_helper.actions import remove_post_and_comment
from reddit_mod_helper.moderation import (
    OllamaError,
    evaluate_post,
    load_prompt_template,
    load_rules,
)
from reddit_mod_helper.reddit_client import Post, RedditFetchError, build_reddit_client, fetch_new_posts
from reddit_mod_helper.state import connect, marcar_procesado, purgar_antiguos, ya_procesado

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(console=Console(stderr=True), show_path=False, markup=True)
        ],
    )


def _procesar_post(
    reddit: praw.Reddit, conn: sqlite3.Connection, post: Post, rules: str, prompt_template: Template
) -> None:
    """Evalúa un post y actúa según el veredicto. Deja que OllamaError y cualquier
    otra excepción se propaguen — el llamador decide si reintentar o abortar."""
    titulo = escape(post.title)

    if ya_procesado(conn, post.id):
        logger.info("[dim]ya evaluado en una corrida anterior, se omite — %s (id=%s)[/dim]", titulo, post.id)
        return

    if not post.is_self and not post.body:
        logger.info("[dim]omitido (video/imagen, sin texto) — %s (id=%s)[/dim]", titulo, post.id)
        marcar_procesado(conn, post.id)
        return

    veredicto = evaluate_post(post, rules, prompt_template)
    razon = veredicto.get("razon", "")
    reglas = veredicto.get("reglas", [])

    if veredicto.get("rompe_reglas"):
        logger.warning(
            "[bold red]ROMPE REGLAS[/bold red] %s (id=%s) — reglas %s — %s",
            titulo,
            post.id,
            escape(str(reglas)),
            escape(razon),
        )
        remove_post_and_comment(reddit, post.id, razon, reglas)
    else:
        logger.info("[green]OK[/green] %s (id=%s) — %s", titulo, post.id, escape(razon))

    marcar_procesado(conn, post.id)


def main() -> None:
    _configure_logging()

    try:
        rules = load_rules()
        prompt_template = load_prompt_template()
    except OSError as e:
        logger.critical("[bold red]No se pudo leer lib/rules.MD o lib/prompt.md, se aborta la corrida:[/bold red] %s", escape(str(e)))
        raise SystemExit(1) from e

    try:
        posts = fetch_new_posts(limit=20)
    except RedditFetchError as e:
        logger.critical("[bold red]%s — se aborta la corrida[/bold red]", escape(str(e)))
        raise SystemExit(1) from e

    reddit = build_reddit_client()
    procesados = 0
    fallidos = 0

    try:
        with closing(connect()) as conn:
            purgados = purgar_antiguos(conn)
            if purgados:
                logger.info("[dim]estado: %d registro(s) de más de 3 días purgados[/dim]", purgados)

            for post in posts:
                try:
                    _procesar_post(reddit, conn, post, rules, prompt_template)
                    procesados += 1
                except OllamaError as e:
                    fallidos += 1
                    logger.error("[red]%s[/red] — se reintentará en la próxima corrida", escape(str(e)))
                except sqlite3.Error as e:
                    fallidos += 1
                    logger.error(
                        "[red]Fallo de estado (SQLite) procesando el post id=%s: %s — se reintentará en la próxima corrida[/red]",
                        post.id,
                        escape(str(e)),
                    )
                except Exception:
                    fallidos += 1
                    logger.exception(
                        "Error inesperado procesando el post (id=%s), se reintentará en la próxima corrida",
                        post.id,
                    )
    finally:
        logger.info("Corrida terminada: %d post(s) procesados, %d fallido(s) de %d totales", procesados, fallidos, len(posts))
