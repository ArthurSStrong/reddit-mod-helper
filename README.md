# reddit-mod-helper

**Selecciona idioma / Select language:** [Español](#español) | [English](#english)

---

## Español

Herramienta en Python que evalúa los posts nuevos de un subreddit contra sus reglas, usando un modelo de lenguaje corriendo en local (Ollama), y **remueve automáticamente los que rompen una regla**. Todo el procesamiento del contenido ocurre en tu máquina — no se manda nada a una API externa de LLM.

> **Coautoría:** este repositorio fue desarrollado en colaboración con [Claude Code](https://claude.com/claude-code) (Anthropic) — gran parte del código, la arquitectura y esta documentación se escribieron junto con un asistente de IA.
>
> **Antes de usarlo, audítalo tú mismo.** Este bot remueve posts reales de un subreddit sin revisión humana caso por caso. Que el código haya sido escrito con asistencia de IA no significa que esté libre de errores — léelo completo, entiende cada decisión de moderación (`lib/rules.MD`, `lib/prompt.md`), pruébalo primero contra un subreddit de pruebas (`REDDIT_SUBREDDIT=test`) y solo después considera correrlo contra una comunidad real. Eres responsable de las acciones que este bot tome en tu nombre.

### Qué hace

1. Trae los posts más recientes del subreddit configurado (título + cuerpo) vía PRAW.
2. Si el post es solo un link a imagen/video/URL externa (sin texto propio), lo salta — no hay contenido real que evaluar más allá del título.
3. A cada post con texto le pasa las reglas del subreddit (`lib/rules.MD`) junto con su título y contenido, usando la plantilla de prompt en `lib/prompt.md`, a un modelo local en Ollama (`gemma4:12b`), que devuelve un veredicto en JSON: si rompe reglas, cuáles, y por qué.
4. Si el veredicto dice que rompe una regla, **remueve el post de verdad y publica el comentario de remoción** usando el mecanismo nativo de "removal reasons" de Reddit — el comentario sale de la cuenta oficial del equipo de moderación (u/&lt;subreddit&gt;-ModTeam), no de la cuenta del bot. La razón de remoción específica se deriva de qué regla(s) rompió (ver [Razones de remoción](#razones-de-remoción-removal-reasons) más abajo).
5. Guarda cada post ya evaluado (incluyendo los omitidos) en `data/estado.db` (SQLite local). Si vuelves a correr la herramienta, no vuelve a evaluar los posts que ya vio — solo los nuevos desde la corrida anterior. Los registros de más de 3 días se purgan automáticamente al inicio de cada corrida para no acumular disco.
6. Si Reddit o Ollama fallan a medio camino (timeout, servicio caído, respuesta rara), no se cae toda la corrida: un fallo fatal (no se pudo ni siquiera traer los posts) aborta con un mensaje claro; un fallo puntual (un solo post) se loguea y se salta, y ese post se reintenta solo en la siguiente corrida.

Además, un **script aparte** (`reddit-mod-helper-imagenes`) usa la capacidad de visión del mismo modelo para describir en detalle las imágenes de los posts — ver la sección [Descripción de imágenes](#descripción-de-imágenes-script-aparte) más abajo.

### Sobre el modelo: Ollama y Gemma

**[Ollama](https://ollama.com/)** es una herramienta open source para correr modelos de lenguaje grandes (LLMs) en tu propia máquina, sin depender de una API externa. Expone una API HTTP local (`http://localhost:11434`) que cualquier programa puede usar — así es como este proyecto le habla al modelo.

**[Gemma](https://ai.google.dev/gemma)** es la familia de modelos abiertos de Google. Este proyecto usa `gemma4:12b` — confirmado con `ollama show gemma4:12b` que soporta texto, **visión**, herramientas y "thinking" — un modelo de 12 mil millones de parámetros que corre completo en tu máquina, sin mandar nada a servidores externos.

Cómo lo obtuvimos (macOS, vía Homebrew):

```
brew install ollama
ollama serve              # deja el servicio corriendo (puerto 11434 por defecto)
ollama pull gemma4:12b    # descarga el modelo
ollama list                # verifica qué se descargó
ollama show gemma4:12b    # confirma sus capacidades (texto, visión, etc.)
```

El tag exacto puede variar según cuándo/cómo lo descargues (podría ser `gemma3:12b` en vez de `gemma4:12b`, por ejemplo) — siempre verifica con `ollama list` antes de asumir el nombre, y actualiza `MODEL_NAME` en `src/reddit_mod_helper/moderation.py` si difiere del tuyo.

### Requisitos

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) para manejar dependencias y el entorno virtual
- Ollama corriendo en local con `gemma4:12b` descargado (ver arriba)
- Una app de Reddit tipo **"script"**, registrada en [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps):
  1. "create app" → tipo `script`.
  2. `redirect uri`: cualquier valor sirve (no se usa en modo script), por ejemplo `http://localhost:8080`.
  3. Al crearla, copia el string corto bajo el nombre de la app (`client_id`) y el campo "secret" (`client_secret`).
- Una cuenta de Reddit que ya sea **moderador del subreddit** con permiso `posts` (para poder remover posts y ver la cola de reportes). Sus credenciales van en `REDDIT_USERNAME`/`REDDIT_PASSWORD`.

### Instalación

```
uv sync
```

Esto crea el entorno virtual en `.venv` e instala todas las dependencias (`praw`, `requests`, `python-dotenv`, `rich`).

### Configuración

Copia el archivo de ejemplo y completa tus credenciales:

```
cp .env.example .env
```

Edita `.env`:

```
REDDIT_CLIENT_ID=<el client_id de tu app>
REDDIT_CLIENT_SECRET=<el secret de tu app>
REDDIT_USER_AGENT=reddit-mod-helper/0.1 (by u/tu-usuario-real-de-reddit)
REDDIT_SUBREDDIT=<el subreddit a moderar, sin "r/">
REDDIT_TIMEZONE=<zona horaria IANA de la comunidad, ej. America/Mexico_City>
REDDIT_USERNAME=<usuario de la cuenta moderadora>
REDDIT_PASSWORD=<contraseña de esa cuenta>
```

- `REDDIT_USER_AGENT` debe incluir tu username real de Reddit — Reddit lo usa para identificar quién hace las peticiones y limita/bloquea user agents genéricos.
- `REDDIT_SUBREDDIT` no tiene un valor hardcodeado en el código — si no lo configuras, cae en `test` por seguridad, no en un subreddit real.
- `REDDIT_TIMEZONE` afecta reglas que dependen del día de la semana (ver más abajo). Si no la configuras, cae en `UTC`.
- `REDDIT_USERNAME`/`REDDIT_PASSWORD` son necesarias para que la herramienta remueva posts de verdad — sin ellas, el cliente queda en modo solo lectura (sirve para probar el fetch y la evaluación, pero no puede actuar). Es la contraseña real de una cuenta con privilegios de moderador; trátala con el mismo cuidado que cualquier credencial sensible (`.env` ya está en `.gitignore`).

### Configuración de contenido (no versionada)

Estos archivos contienen el nombre y las reglas reales de la comunidad que moderas — **no se versionan** (están en `.gitignore`). Copia cada `*.example.*` sin la parte `.example` y edítalo:

```
cp lib/rules.example.MD lib/rules.MD
cp lib/prompt.example.md lib/prompt.md
cp lib/prompt_imagen.example.md lib/prompt_imagen.md
cp lib/removal_reasons.example.json lib/removal_reasons.json
```

Ver [Ajustar las reglas o el criterio del modelo](#ajustar-las-reglas-o-el-criterio-del-modelo) y [Razones de remoción](#razones-de-remoción-removal-reasons) para el detalle de cada uno.

### Uso

Con Ollama corriendo (`ollama serve`) y el `.env` configurado:

```
uv run reddit-mod-helper
```

El log usa [`rich`](https://github.com/Textualize/rich) para colorear la salida por nivel y por estado, con timestamps compactos. Se ve algo así (colores: `OK` en verde, `ROMPE REGLAS`/`REMOVIDO` en rojo sobre fondo de warning, el resto en el color por defecto del nivel INFO):

```
[hh:mm:ss] INFO     Respuesta cruda de Ollama para el post abc123: {"rompe_reglas": true, "reglas": [7], ...}
           WARNING  ROMPE REGLAS <título del post> (id=abc123) — reglas [7] — <razón del modelo>
[hh:mm:ss] WARNING  REMOVIDO post id=abc123 — comentario publicado: <permalink del comentario>
           INFO     OK <título de otro post> (id=def456) — <razón del modelo>
```

Cada post pasa por una de tres rutas:

- **Omitido** (gris/dim) — es un post de link/imagen/video sin texto propio, no se evalúa.
- **OK** (verde) — el modelo determinó que no rompe ninguna regla.
- **ROMPE REGLAS** (rojo, nivel `WARNING`) — el modelo detectó una o más violaciones; dispara la remoción real (`REMOVIDO`) + comentario del post.

Si corres la herramienta de nuevo poco después, vas a ver en su lugar `ya evaluado en una corrida anterior, se omite` para cualquier post que ya haya pasado por alguna de las tres rutas de arriba — no se vuelve a llamar a Ollama para él.

### Recordar qué ya se evaluó (entre corridas)

Cada post que se procesa (evaluado o solo omitido por ser video/imagen) se registra en `data/estado.db`, una base SQLite local con una sola tabla (`posts_evaluados`: `id`, `procesado_en`). Al inicio de cada corrida:

1. Se purgan los registros con más de 3 días de antigüedad, para no acumular contenido en disco indefinidamente (aunque en la práctica el tamaño es mínimo — son solo IDs cortos).
2. Se consulta esa tabla antes de evaluar cada post; si ya está, se salta sin llamar a Ollama.
3. Un post solo se marca como evaluado **después** de terminar de procesarlo con éxito — si algo falla a medio camino (por ejemplo, Ollama no responde), ese post no queda marcado y se vuelve a intentar en la siguiente corrida.

Esto pensado para correr la herramienta repetidamente (por ejemplo, con un cron o un LaunchAgent) sin re-evaluar los mismos posts cada vez ni gastar disco de forma ilimitada. `data/` no está versionado (ver `.gitignore`) porque es estado local que se regenera solo.

### Qué pasa si Reddit o Ollama fallan

La herramienta está pensada para correr sola y repetidamente (cron/LaunchAgent), así que un servicio caído en una corrida no debería dejarla en mal estado ni tumbar el proceso a medias:

- **No se pudo ni traer los posts** (Reddit no respondió, credenciales inválidas, subreddit no existe) — se aborta toda la corrida con un `CRITICAL` en el log y código de salida `1`. No hay nada que hacer sin posts, así que no tiene sentido seguir.
- **Ollama no respondió a tiempo, está caído, o devolvió algo que no se pudo interpretar** (le pasó de verdad en pruebas: el modelo a veces "degenera" y devuelve texto basura en vez de JSON) — se loguea el error para ese post puntual y se sigue con el siguiente. Como el post no se marca como procesado en `data/estado.db`, se reintenta solo en la próxima corrida.
- **Un problema con el estado local (SQLite)** — mismo tratamiento: se loguea y se sigue con el siguiente post.
- Al final de cada corrida, pase lo que pase, se loguea un resumen: `Corrida terminada: N post(s) procesados, M fallido(s) de TOTAL totales`.

`requests` (la librería que habla con Ollama) no tiene timeout por defecto — a diferencia de PRAW, que sí trae uno (16s) para las llamadas a Reddit —, así que se le pasa uno explícito (300s) para no quedarse esperando indefinidamente si el modelo se cuelga.

### Razones de remoción (removal reasons)

Cuando se remueve un post, no se usa un comentario genérico: se usa el mecanismo nativo de "removal reasons" de Reddit (`submission.mod.send_removal_message(type="public_as_subreddit")`). Esto tiene dos efectos importantes:

- El comentario de remoción se publica como la cuenta oficial del equipo de moderación (u/&lt;subreddit&gt;-ModTeam), no como la cuenta del bot — se ve exactamente igual que cuando remueve un moderador humano.
- Se categoriza con un `reason_id` de las razones que los moderadores humanos ya tienen preconfiguradas en el subreddit (`subreddit.mod.removal_reasons`).

`actions.reason_id_para_reglas()` lee el mapeo regla→`reason_id` desde `lib/removal_reasons.json` (no versionado). No hay por qué esperar una correspondencia perfecta 1:1 — un subreddit puede tener categorías más granulares que las tuyas — así que solo tiene sentido mapear las reglas con una razón claramente equivalente. Cualquier regla sin mapeo, o si el archivo no existe, cae en la entrada `"default"` de ese archivo (o directamente sin categorizar), para que la remoción nunca falle por esto.

Para armar tu `lib/removal_reasons.json` real, copia `lib/removal_reasons.example.json` y obtén los `reason_id` de tu subreddit así:

```python
from reddit_mod_helper.reddit_client import build_reddit_client

reddit = build_reddit_client()
for r in reddit.subreddit("tu_subreddit").mod.removal_reasons:
    print(r.id, r.title)
```

### Descripción de imágenes (script aparte)

`gemma4:12b` no solo lee texto — también soporta visión (confirmado con `ollama show gemma4:12b`, capability `vision`). `reddit-mod-helper-imagenes` es un script independiente que aprovecha eso: busca posts con imagen y le pide al modelo una descripción detallada, como paso previo para eventualmente decidir si la imagen rompe una regla (esa decisión todavía no está implementada — hoy solo describe).

```
uv run reddit-mod-helper-imagenes
```

Qué hace:

1. Trae los posts más recientes (igual que `reddit-mod-helper`) y se queda solo con los que Reddit clasificó como imagen (`post_hint == "image"`). Los posts de galería (varias imágenes en un post) no se detectan todavía.
2. Descarga cada imagen y la manda en base64 a Ollama junto con el prompt de `lib/prompt_imagen.md`, que le pide al modelo describir el contenido y señalar explícitamente si hay algo sensible (contenido sexual, violencia, información personal, spam, símbolos de odio).
3. Guarda la descripción en `data/estado.db` (tabla `imagenes_descritas`, separada de la de texto) para no volver a describir la misma imagen en la siguiente corrida — mismo mecanismo de dedupe y purga de 3 días que el resto de la herramienta.
4. Igual que el pipeline de texto: un fallo por imagen (descarga que falla, Ollama caído, timeout) se loguea y se salta esa imagen sin tumbar el resto; un fallo fatal (no se pudieron traer los posts) aborta con código de salida `1`.

**La visión es lenta** — en pruebas reales tomó ~150 segundos por imagen (carga del modelo de visión + una imagen de tamaño normal), bastante más que evaluar solo texto. El timeout hacia Ollama para este script es más generoso (`DESCRIPCION_TIMEOUT_SEGUNDOS = 400` en `image_moderation.py`) por esta razón. Si vas a correr esto sobre muchos posts con imagen, calcula el tiempo total con ese orden de magnitud.

### Ajustar las reglas o el criterio del modelo

Todos son archivos de texto plano, editables sin tocar código Python (y no versionados — ver [Configuración de contenido](#configuración-de-contenido-no-versionada)):

- **`lib/rules.MD`** — las reglas reales de tu subreddit, tal como aparecen en su página de reglas. Edítalo cuando los moderadores cambien una regla.
- **`lib/prompt.md`** — las instrucciones que recibe el modelo para moderar texto, incluyendo qué tan estricto o laxo debe ser. Usa los placeholders `$rules`, `$title`, `$body` y `$dia_semana` (no toques esos cuatro nombres, se sustituyen desde el código); todo lo demás es texto libre que puedes ajustar.
- **`lib/prompt_imagen.md`** — las instrucciones para describir imágenes (usado por `reddit-mod-helper-imagenes`). Usa el placeholder `$title` (el título del post, como contexto). Ajusta aquí qué tipo de contenido sensible quieres que el modelo señale explícitamente en la descripción.

#### Reglas que dependen del día de la semana

Una regla del tipo "offtopic solo un día específico" necesita saber qué día era cuando se publicó el post — no qué día es hoy, ni en qué zona horaria corre el servidor. Por eso el prompt recibe `$dia_semana` (en español: lunes, martes, ..., domingo), calculado a partir de la fecha real de publicación del post (`created_utc`) convertida a la zona horaria de `REDDIT_TIMEZONE`. Si agregas una nueva regla que dependa del día, ya tienes ese dato disponible en el prompt — solo agrégalo a las instrucciones en `lib/prompt.md`.

### Estructura del proyecto

```
src/reddit_mod_helper/
├── __init__.py           # punto de entrada de texto: encadena fetch -> dedupe -> evaluación -> acción -> estado
├── image_moderation.py   # script aparte: describe imágenes de posts con la visión de Ollama
├── reddit_client.py      # obtención de posts vía PRAW
├── moderation.py         # arma el prompt de texto con las reglas y llama a Ollama
├── actions.py            # acciones de moderación: remoción real + mapeo a removal reasons
└── state.py              # deduplicación entre corridas (SQLite, dos tablas) + purga de más de 3 días
lib/
├── rules.MD                       # reglas reales de tu subreddit (no versionado)
├── rules.example.MD               # ejemplo genérico (versionado)
├── prompt.md                      # prompt de moderación de texto real (no versionado)
├── prompt.example.md              # ejemplo genérico (versionado)
├── prompt_imagen.md               # prompt de descripción de imágenes real (no versionado)
├── prompt_imagen.example.md       # ejemplo genérico (versionado)
├── removal_reasons.json           # mapeo real regla→reason_id (no versionado)
└── removal_reasons.example.json   # ejemplo genérico (versionado)
data/
└── estado.db              # generado en la primera corrida, no versionado
docs/private/
└── ...                     # notas operativas reales de tu despliegue, no versionado
```

`CLAUDE.md` (guía para trabajar en este repo con Claude Code) existe localmente pero no se versiona — ver `.gitignore`.

---

## English

Python tool that evaluates new posts on a subreddit against its rules, using a language model running locally (Ollama), and **automatically removes the ones that break a rule**. All content processing happens on your machine — nothing is sent to an external LLM API.

> **Co-authorship:** this repository was developed in collaboration with [Claude Code](https://claude.com/claude-code) (Anthropic) — most of the code, the architecture, and this documentation were written together with an AI assistant.
>
> **Audit it yourself before using it.** This bot removes real posts from a subreddit with no case-by-case human review. Code being written with AI assistance does not mean it is free of mistakes — read it in full, understand every moderation decision (`lib/rules.MD`, `lib/prompt.md`), test it against a test subreddit first (`REDDIT_SUBREDDIT=test`), and only then consider running it against a real community. You are responsible for the actions this bot takes on your behalf.

### What it does

1. Fetches the most recent posts from the configured subreddit (title + body) via PRAW.
2. If the post is just a link to an image/video/external URL (no text of its own), it's skipped — there's no real content to evaluate beyond the title.
3. For each text post, it passes the subreddit's rules (`lib/rules.MD`) along with the post's title and body, using the prompt template in `lib/prompt.md`, to a local model in Ollama (`gemma4:12b`), which returns a JSON verdict: whether it breaks any rules, which ones, and why.
4. If the verdict says it breaks a rule, **it actually removes the post and posts the removal comment** using Reddit's native "removal reasons" mechanism — the comment is posted from the official moderation team account (u/&lt;subreddit&gt;-ModTeam), not from the bot's own account. The specific removal reason is derived from which rule(s) were broken (see [Removal reasons](#removal-reasons) below).
5. Records every post it already evaluated (including skipped ones) in `data/estado.db` (local SQLite). If you run the tool again, it won't re-evaluate posts it already saw — only new ones since the last run. Records older than 3 days are purged automatically at the start of each run so disk usage stays bounded.
6. If Reddit or Ollama fail partway through (timeout, service down, weird response), the whole run doesn't crash: a fatal failure (couldn't even fetch the posts) aborts with a clear message; a one-off failure (a single post) is logged and skipped, and that post is retried on the next run.

There's also a **separate script** (`reddit-mod-helper-imagenes`) that uses the same model's vision capability to describe post images in detail — see [Image descriptions](#image-descriptions-separate-script) below.

### About the model: Ollama and Gemma

**[Ollama](https://ollama.com/)** is an open source tool for running large language models (LLMs) on your own machine, without depending on an external API. It exposes a local HTTP API (`http://localhost:11434`) that any program can use — that's how this project talks to the model.

**[Gemma](https://ai.google.dev/gemma)** is Google's family of open models. This project uses `gemma4:12b` — confirmed via `ollama show gemma4:12b` to support text, **vision**, tools, and "thinking" — a 12-billion-parameter model that runs entirely on your machine, without sending anything to external servers.

How we obtained it (macOS, via Homebrew):

```
brew install ollama
ollama serve              # leaves the service running (port 11434 by default)
ollama pull gemma4:12b    # downloads the model
ollama list                # check what got downloaded
ollama show gemma4:12b    # confirm its capabilities (text, vision, etc.)
```

The exact tag can vary depending on when/how you download it (it could be `gemma3:12b` instead of `gemma4:12b`, for example) — always check with `ollama list` before assuming the name, and update `MODEL_NAME` in `src/reddit_mod_helper/moderation.py` if it differs from yours.

### Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) to manage dependencies and the virtual environment
- Ollama running locally with `gemma4:12b` downloaded (see above)
- A Reddit app of type **"script"**, registered at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps):
  1. "create app" → type `script`.
  2. `redirect uri`: any value works (not used in script mode), e.g. `http://localhost:8080`.
  3. Once created, copy the short string under the app's name (`client_id`) and the "secret" field (`client_secret`).
- A Reddit account that's already a **moderator of the subreddit** with `posts` permission (needed to remove posts and see the report queue). Its credentials go in `REDDIT_USERNAME`/`REDDIT_PASSWORD`.

### Installation

```
uv sync
```

This creates the virtual environment in `.venv` and installs all dependencies (`praw`, `requests`, `python-dotenv`, `rich`).

### Configuration

Copy the example file and fill in your credentials:

```
cp .env.example .env
```

Edit `.env`:

```
REDDIT_CLIENT_ID=<your app's client_id>
REDDIT_CLIENT_SECRET=<your app's secret>
REDDIT_USER_AGENT=reddit-mod-helper/0.1 (by u/your-real-reddit-username)
REDDIT_SUBREDDIT=<the subreddit to moderate, without "r/">
REDDIT_TIMEZONE=<the community's IANA timezone, e.g. America/Mexico_City>
REDDIT_USERNAME=<the moderator account's username>
REDDIT_PASSWORD=<that account's password>
```

- `REDDIT_USER_AGENT` must include your real Reddit username — Reddit uses this to identify who's making requests and rate-limits/blocks generic user agents.
- `REDDIT_SUBREDDIT` has no hardcoded value in the code — if you don't set it, it falls back to `test`, not a real subreddit.
- `REDDIT_TIMEZONE` affects rules that depend on the day of the week (see below). Falls back to `UTC` if unset.
- `REDDIT_USERNAME`/`REDDIT_PASSWORD` are required for the tool to actually remove posts — without them, the client stays in read-only mode (good for testing the fetch and evaluation, but it can't act). This is the real password of an account with moderator privileges; treat it with the same care as any sensitive credential (`.env` is already in `.gitignore`).

### Content configuration (not version-controlled)

These files contain the real name and rules of the community you moderate — **they are not version-controlled** (they're in `.gitignore`). Copy each `*.example.*` without the `.example` part and edit it:

```
cp lib/rules.example.MD lib/rules.MD
cp lib/prompt.example.md lib/prompt.md
cp lib/prompt_imagen.example.md lib/prompt_imagen.md
cp lib/removal_reasons.example.json lib/removal_reasons.json
```

See [Adjusting the rules or the model's judgment](#adjusting-the-rules-or-the-models-judgment) and [Removal reasons](#removal-reasons) for details on each one.

### Usage

With Ollama running (`ollama serve`) and `.env` configured:

```
uv run reddit-mod-helper
```

The log uses [`rich`](https://github.com/Textualize/rich) to color output by level and status, with compact timestamps. It looks something like this (colors: `OK` in green, `ROMPE REGLAS`/`REMOVIDO` in red on a warning background, everything else in the INFO level's default color):

```
[hh:mm:ss] INFO     Raw Ollama response for post abc123: {"rompe_reglas": true, "reglas": [7], ...}
           WARNING  ROMPE REGLAS <post title> (id=abc123) — reglas [7] — <model's reasoning>
[hh:mm:ss] WARNING  REMOVIDO post id=abc123 — comment posted: <comment permalink>
           INFO     OK <another post's title> (id=def456) — <model's reasoning>
```

Each post goes through one of three paths:

- **Skipped** (gray/dim) — it's a link/image/video post with no text of its own, not evaluated.
- **OK** (green) — the model determined it doesn't break any rule.
- **ROMPE REGLAS** (red, `WARNING` level) — the model detected one or more violations; triggers the real removal (`REMOVIDO`) + post comment.

If you run the tool again shortly after, you'll instead see `ya evaluado en una corrida anterior, se omite` for any post that already went through one of the three paths above — Ollama isn't called for it again.

### Remembering what's already been evaluated (across runs)

Every post that gets processed (evaluated or just skipped for being video/image) is recorded in `data/estado.db`, a local SQLite database with a single table (`posts_evaluados`: `id`, `procesado_en`). At the start of each run:

1. Records older than 3 days are purged, so disk content doesn't accumulate indefinitely (though in practice the size is tiny — they're just short IDs).
2. That table is checked before evaluating each post; if it's already there, it's skipped without calling Ollama.
3. A post is only marked as evaluated **after** it finishes processing successfully — if something fails partway through (e.g. Ollama doesn't respond), that post isn't marked and gets retried on the next run.

This is meant for running the tool repeatedly (e.g. via a cron job or a LaunchAgent) without re-evaluating the same posts every time or using unbounded disk space. `data/` isn't version-controlled (see `.gitignore`) because it's local state that regenerates itself.

### What happens if Reddit or Ollama fail

The tool is meant to run on its own, repeatedly (cron/LaunchAgent), so a service going down during a run shouldn't leave it in a bad state or crash the process halfway:

- **Couldn't even fetch the posts** (Reddit didn't respond, invalid credentials, subreddit doesn't exist) — the whole run aborts with a `CRITICAL` log entry and exit code `1`. There's nothing to do without posts, so there's no point continuing.
- **Ollama didn't respond in time, is down, or returned something uninterpretable** (this genuinely happened in testing: the model sometimes "degenerates" and returns garbage text instead of JSON) — the error is logged for that specific post and the run continues with the next one. Since the post isn't marked as processed in `data/estado.db`, it's retried on the next run.
- **A problem with local state (SQLite)** — same handling: logged, and the run continues with the next post.
- At the end of every run, no matter what happened, a summary is logged: `Corrida terminada: N post(s) procesados, M fallido(s) de TOTAL totales`.

`requests` (the library used to talk to Ollama) has no default timeout — unlike PRAW, which does have one (16s) for Reddit calls — so an explicit one (300s) is passed so it doesn't wait indefinitely if the model hangs.

### Removal reasons

When a post is removed, it doesn't use a generic comment: it uses Reddit's native "removal reasons" mechanism (`submission.mod.send_removal_message(type="public_as_subreddit")`). This has two important effects:

- The removal comment is posted from the official moderation team account (u/&lt;subreddit&gt;-ModTeam), not from the bot's account — it looks exactly like when a human moderator removes something.
- It's categorized with a `reason_id` from the reasons human moderators have already preconfigured on the subreddit (`subreddit.mod.removal_reasons`).

`actions.reason_id_para_reglas()` reads the rule→`reason_id` mapping from `lib/removal_reasons.json` (not version-controlled). Don't expect a perfect 1:1 correspondence — a subreddit may have more granular categories than yours — so only map the rules that have a clearly equivalent reason. Any unmapped rule, or if the file doesn't exist, falls back to that file's `"default"` entry (or no categorization at all), so removal never fails because of this.

To build your real `lib/removal_reasons.json`, copy `lib/removal_reasons.example.json` and get your subreddit's `reason_id`s like this:

```python
from reddit_mod_helper.reddit_client import build_reddit_client

reddit = build_reddit_client()
for r in reddit.subreddit("your_subreddit").mod.removal_reasons:
    print(r.id, r.title)
```

### Image descriptions (separate script)

`gemma4:12b` doesn't just read text — it also supports vision (confirmed with `ollama show gemma4:12b`, capability `vision`). `reddit-mod-helper-imagenes` is an independent script that takes advantage of that: it looks for posts with images and asks the model for a detailed description, as a preliminary step toward eventually deciding whether the image breaks a rule (that decision isn't implemented yet — today it only describes).

```
uv run reddit-mod-helper-imagenes
```

What it does:

1. Fetches the most recent posts (same as `reddit-mod-helper`) and keeps only the ones Reddit classified as images (`post_hint == "image"`). Gallery posts (multiple images in one post) aren't detected yet.
2. Downloads each image and sends it as base64 to Ollama along with the prompt in `lib/prompt_imagen.md`, which asks the model to describe the content and explicitly flag anything sensitive (sexual content, violence, personal information, spam, hate symbols).
3. Saves the description in `data/estado.db` (table `imagenes_descritas`, separate from the text one) so the same image isn't described again on the next run — same dedupe and 3-day purge mechanism as the rest of the tool.
4. Same as the text pipeline: a per-image failure (download fails, Ollama down, timeout) is logged and that image is skipped without crashing the rest; a fatal failure (couldn't fetch the posts) aborts with exit code `1`.

**Vision is slow** — in real testing it took ~150 seconds per image (loading the vision model + a normal-sized image), much more than text-only evaluation. This script's Ollama timeout is more generous (`DESCRIPCION_TIMEOUT_SEGUNDOS = 400` in `image_moderation.py`) for this reason. If you're going to run this over many posts with images, plan for that order of magnitude.

### Adjusting the rules or the model's judgment

All plain text files, editable without touching Python code (and not version-controlled — see [Content configuration](#content-configuration-not-version-controlled)):

- **`lib/rules.MD`** — your subreddit's real rules, as they appear on its rules page. Edit it when the moderators change a rule.
- **`lib/prompt.md`** — the instructions the model receives to moderate text, including how strict or lenient it should be. Uses the placeholders `$rules`, `$title`, `$body`, and `$dia_semana` (don't touch these four names, they're substituted from the code); everything else is free text you can adjust.
- **`lib/prompt_imagen.md`** — the instructions for describing images (used by `reddit-mod-helper-imagenes`). Uses the `$title` placeholder (the post's title, as context). Adjust here what kind of sensitive content you want the model to explicitly flag in the description.

#### Rules that depend on the day of the week

A rule like "offtopic only on a specific day" needs to know what day it was when the post was published — not what day it is today, or what timezone the server is running in. That's why the prompt receives `$dia_semana` (in Spanish: lunes, martes, ..., domingo), calculated from the post's real publication date (`created_utc`) converted to the `REDDIT_TIMEZONE` timezone. If you add a new rule that depends on the day, that data is already available in the prompt — just add it to the instructions in `lib/prompt.md`.

### Project structure

```
src/reddit_mod_helper/
├── __init__.py           # text entry point: chains fetch -> dedupe -> evaluation -> action -> state
├── image_moderation.py   # separate script: describes post images with Ollama's vision
├── reddit_client.py      # fetching posts via PRAW
├── moderation.py         # builds the text prompt with the rules and calls Ollama
├── actions.py            # moderation actions: real removal + removal reason mapping
└── state.py              # deduplication across runs (SQLite, two tables) + purge older than 3 days
lib/
├── rules.MD                       # your subreddit's real rules (not version-controlled)
├── rules.example.MD               # generic example (version-controlled)
├── prompt.md                      # real text moderation prompt (not version-controlled)
├── prompt.example.md              # generic example (version-controlled)
├── prompt_imagen.md               # real image description prompt (not version-controlled)
├── prompt_imagen.example.md       # generic example (version-controlled)
├── removal_reasons.json           # real rule→reason_id mapping (not version-controlled)
└── removal_reasons.example.json   # generic example (version-controlled)
data/
└── estado.db              # generated on first run, not version-controlled
docs/private/
└── ...                     # real operational notes for your deployment, not version-controlled
```

`CLAUDE.md` (guidance for working in this repo with Claude Code) exists locally but isn't version-controlled — see `.gitignore`.
