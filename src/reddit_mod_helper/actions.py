"""Acciones de moderación.

`simulate_removal()` es el mockup, ya no usado por el pipeline automático
por defecto pero se deja disponible — no toca Reddit, solo loguea qué se
haría.

`remove_post_and_comment()` es la acción real, conectada al loop automático
de `__init__.py`: requiere que la cuenta autenticada
(REDDIT_USERNAME/REDDIT_PASSWORD en .env) sea moderador del subreddit con
permiso "posts".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import praw
from rich.markup import escape

from reddit_mod_helper.reddit_client import Post

logger = logging.getLogger(__name__)

# Mapeo de nuestras reglas (lib/rules.MD) a las razones de remoción
# preconfiguradas del subreddit (subreddit.mod.removal_reasons). Vive en un
# archivo aparte, no hardcodeado aquí, porque son IDs reales específicos del
# subreddit configurado — ver lib/removal_reasons.example.json para el
# formato. Sin ese archivo (o sin una regla mapeada dentro), se usa "default"
# si existe, o ninguna categorización.
REMOVAL_REASONS_PATH = Path(__file__).resolve().parent.parent.parent / "lib" / "removal_reasons.json"


def _load_removal_reasons() -> dict:
    if not REMOVAL_REASONS_PATH.exists():
        return {}
    return json.loads(REMOVAL_REASONS_PATH.read_text(encoding="utf-8"))


def reason_id_para_reglas(reglas: list[int]) -> str | None:
    """Devuelve el reason_id de la primera regla mapeada, el "default" configurado, o None."""
    mapeo = _load_removal_reasons()
    reglas_mapeadas = mapeo.get("reglas", {})

    for regla in reglas:
        reason_id = reglas_mapeadas.get(str(regla))
        if reason_id:
            return reason_id

    return mapeo.get("default") or None


def simulate_removal(post: Post, razon: str, reglas: list[int]) -> None:
    titulo = escape(post.title)
    razon_escapada = escape(razon)
    reglas_escapadas = escape(str(reglas))

    logger.warning(
        "[bold yellow]MOCKUP[/bold yellow] Se removería el post %s (id=%s) por romper regla(s) %s",
        titulo,
        post.id,
        reglas_escapadas,
    )
    logger.warning(
        "[bold yellow]MOCKUP[/bold yellow] Se publicaría este comentario como moderador en %s: %s",
        post.permalink,
        razon_escapada,
    )


def remove_post_and_comment(reddit: praw.Reddit, post_id: str, razon: str, reglas: list[int]) -> None:
    """Remueve un post real y publica el comentario de remoción con la razón.

    Usa el mecanismo nativo de "removal reasons" de Reddit en vez de un
    `submission.reply()` manual: `send_removal_message(type="public_as_subreddit")`
    publica el comentario como **u/<subreddit>-ModTeam** (la cuenta oficial
    del equipo de moderación), no como la cuenta del bot — así se ve igual
    que cuando remueve un moderador humano. El `reason_id` se deriva de
    `reglas` vía `reason_id_para_reglas()` (ver `lib/removal_reasons.json`).

    Acción real e irreversible desde el punto de vista de la comunidad — el
    post desaparece del listado público. Requiere que la cuenta autenticada
    sea moderador del subreddit con permiso "posts".
    """
    reason_id = reason_id_para_reglas(reglas)
    submission = reddit.submission(id=post_id)
    submission.mod.remove(mod_note=razon[:100], reason_id=reason_id)
    comentario = submission.mod.send_removal_message(message=razon, type="public_as_subreddit")

    logger.warning(
        "[bold red]REMOVIDO[/bold red] post id=%s — comentario publicado: %s",
        post_id,
        escape(comentario.permalink) if comentario else "(sin comentario)",
    )
