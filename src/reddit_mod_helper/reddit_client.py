"""Cliente de lectura (y, opcionalmente, de moderador) para un subreddit, vía PRAW.

Requiere credenciales de una app tipo "script" registrada en
https://www.reddit.com/prefs/apps, leídas desde variables de entorno
(ver .env.example). Sin REDDIT_USERNAME/REDDIT_PASSWORD, PRAW opera en modo
solo lectura — suficiente para fetch y moderación simulada (mockup). Con
esas dos variables presentes, se autentica como esa cuenta y quedan
disponibles las acciones reales de moderador (remover posts, comentar) que
esa cuenta tenga permitidas en el subreddit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import praw
import prawcore
from dotenv import load_dotenv

load_dotenv()

# Subreddit objetivo, leído de REDDIT_SUBREDDIT (.env). No se hardcodea un
# subreddit real aquí a propósito — este código es público, y el nombre del
# subreddit + la cuenta moderadora identifican quién opera el bot.
DEFAULT_SUBREDDIT = os.environ.get("REDDIT_SUBREDDIT", "test")


class RedditFetchError(Exception):
    """Reddit no respondió, respondió con error, o las credenciales fallaron."""


@dataclass
class Post:
    id: str
    title: str
    body: str
    author: str
    permalink: str
    created_utc: float
    is_self: bool
    url: str
    is_image: bool


def build_reddit_client() -> praw.Reddit:
    kwargs: dict[str, str] = {
        "client_id": os.environ["REDDIT_CLIENT_ID"],
        "client_secret": os.environ["REDDIT_CLIENT_SECRET"],
        "user_agent": os.environ["REDDIT_USER_AGENT"],
    }

    username = os.environ.get("REDDIT_USERNAME")
    password = os.environ.get("REDDIT_PASSWORD")
    if username and password:
        kwargs["username"] = username
        kwargs["password"] = password

    return praw.Reddit(**kwargs)


def fetch_new_posts(subreddit: str = DEFAULT_SUBREDDIT, limit: int = 25) -> list[Post]:
    """Obtiene los posts más recientes de un subreddit.

    PRAW/prawcore ya traen un timeout por defecto (16s, ver
    prawcore.const.TIMEOUT) para no colgarse indefinidamente si Reddit deja
    de responder, pero eso se traduce en una excepción de prawcore que hay
    que capturar explícitamente — si no, un solo timeout tumba todo el
    proceso.

    `is_image` usa `post_hint == "image"` (lo que Reddit ya clasificó), no
    la extensión de la URL — es más confiable y distingue bien de videos
    (`hosted:video`) y de posts sin link. Los posts de galería (múltiples
    imágenes, `reddit.com/gallery/...`) no traen `post_hint == "image"` y
    quedan fuera de esto por ahora — no soportado todavía.
    """
    reddit = build_reddit_client()

    try:
        return [
            Post(
                id=submission.id,
                title=submission.title,
                body=submission.selftext,
                author=str(submission.author),
                permalink=submission.permalink,
                created_utc=submission.created_utc,
                is_self=submission.is_self,
                url=submission.url,
                is_image=getattr(submission, "post_hint", None) == "image",
            )
            for submission in reddit.subreddit(subreddit).new(limit=limit)
        ]
    except prawcore.exceptions.PrawcoreException as e:
        raise RedditFetchError(f"Reddit no respondió o devolvió un error al pedir r/{subreddit}: {e}") from e
