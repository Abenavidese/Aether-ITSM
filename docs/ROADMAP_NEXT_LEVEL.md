# Aether ITSM — Roadmap "next level"

Análisis del 2026-09-25, hecho leyendo el código real y corriendo el stack local
(uvicorn + Ollama + Supabase), después de cerrar la Fase 11 (seguridad del LLM).
Nada de este documento está implementado todavía. Cada ítem tiene un **CHECK**
de aceptación para darlo por hecho.

Estado de partida:
- Fases 0–11 cerradas.
- 193/193 tests en pytest.
- `scripts/e2e_ollama.py` en verde.
- `scripts/redteam_ollama.py` con 0 brechas.
- Pendiente fuera de este documento: Fase 10.0 (credenciales de Render) y el
  commit de la Fase 11.

---

## 1. Credibilidad: lo que un reviewer detecta rápido

Son arreglos baratos que evitan que una revisión de código encuentre promesas vacías.

### 1.1 La imagen del chat no se envía
En el portal del empleado se puede adjuntar una imagen y el UI la muestra en la
burbuja, pero `frontend/src/features/portal/hooks/useChat.ts` solo manda
`{ message }`. `ChatPayload` (`src/api/routes.py`) ni siquiera tiene el campo.
El backend nunca la recibe.

- Opción A: enviarla (`image_base64` en `ChatPayload`, con la misma validación
  de data-URI que `TicketPayload`) y pasarla al modelo como parte multimodal.
- Opción B: quitar el botón hasta tener un modelo con visión.

**CHECK:** o el backend recibe la imagen y se ve en el prompt (test), o el botón
no existe.

### 1.2 Configuración que no hace nada
`llm_engine`, `webhook_url` y `mcp_server_url` se guardan en `Company` y se
muestran en Settings (`src/tenant/router.py`), pero ningún código los usa.

**CHECK:** cada campo de Settings tiene efecto real o se elimina (modelo, API y UI).

### 1.3 Documentación que promete más de lo que hay
- `docs/specs/evaluation_metrics.md` promete:
  - 30 tickets de evaluación (`tests/data/tickets.json` tiene 4);
  - un contador de tokens y costo;
  - tracing con LangSmith;
  - WebSockets.

  Nada de eso existe.
- `docs/adrs/004-system-resilience.md` promete:
  - un `SummarizerNode` (lo que existe es `context_budget.py`, que recorta el
    historial);
  - avisar al ITSM cuando el agente termina (no existe).

**CHECK:** cada documento marca cada afirmación como *Implemented* o *Planned*,
igual que ya se hizo con `security_guardrails.md`.

### 1.4 Lo básico de un repo profesional
Hoy faltan:
- CI;
- Dockerfile y docker-compose;
- README en la raíz (solo existe el de `frontend/`);
- linters (ruff/mypy);
- migraciones versionadas: se hacen con `ALTER TABLE` a mano en
  `_ensure_schema_migrations` de `src/main.py`.

Además sigue el error de TypeScript en `OnboardingPage.tsx` (`navigate` sin usar).

Tareas:
- GitHub Actions con `pytest`, `ruff`, `mypy` (al menos sobre `src/agent` y
  `src/security`), `tsc -b` y `npm run build`.
- `Dockerfile` para la API y `docker-compose.yml` (API + Postgres/pgvector + Ollama
  opcional) para levantar la demo con un solo comando.
- README en la raíz: qué es, arquitectura, cómo correrlo, cómo probarlo y
  enlaces a los docs.
- Alembic, con una migración inicial que reemplace `_ensure_schema_migrations`.

**CHECK:**
- Un PR de prueba corre el CI en verde.
- `docker compose up` deja la app accesible.
- `alembic upgrade head` sobre una BD vacía crea el esquema completo.

---

## 2. Robustez y arquitectura senior

### 2.1 El servidor se bloquea mientras atiende un chat
`/chat`, `/webhook/ticket` y `/approve` son `async def`, pero usan una sesión de
SQLAlchemy síncrona. Además, el Concierge y los nodos llaman de forma síncrona a:
- `retrieve_context` (embeddings por HTTP + consulta a pgvector);
- `_get_github_config`;
- `get_monitored_services`.

Mientras una request espera esas llamadas, el event loop de uvicorn se congela
para **todos** los usuarios.

- Mínimo: envolver esas llamadas con `run_in_threadpool` / `asyncio.to_thread`.
- Ideal: SQLAlchemy async (asyncpg) y embeddings asíncronos.

**CHECK:** test de concurrencia: mientras un chat espera un embedding lento
(mockeado a 3 s), `GET /health` responde en menos de 100 ms.

### 2.2 Cola de trabajos en vez de `BackgroundTasks`
Hoy el agente corre en `BackgroundTasks` dentro del proceso de la API. Si el
server se reinicia o se redespliega, esos tickets se pierden. Tampoco hay
reintentos ni límite de concurrencia (30 webhooks por minuto pueden lanzar 30
corridas del 8B al mismo tiempo).

- Cola persistente: arq + Redis, o una cola sobre Postgres (procrastinate, o
  `SELECT … FOR UPDATE SKIP LOCKED`), para no sumar infraestructura.
- Workers aparte, con reintentos con backoff e idempotencia por
  `(tenant_id, external_id)`.
- Patrón outbox para los issues de GitHub: se guarda la intención en la misma
  transacción y un worker la entrega con reintentos.

**CHECK:**
- Matar el worker a mitad de un ticket y relanzarlo: el ticket termina.
- Una caída temporal de GitHub no pierde el issue.

### 2.3 Evaluación del LLM
Es lo que más distingue un proyecto de IA serio: medir en vez de adivinar.

- Dataset "golden" versionado (`evals/`) con más de 50 casos:
  - tickets por nivel de riesgo, en español e inglés;
  - chats sobre el repo real;
  - ataques del red-team.
- Métricas:
  - precisión al clasificar riesgo (matriz de confusión);
  - tool y argumentos correctos;
  - tasa de respuestas fundamentadas (validador de grounding);
  - tasa de rechazos correctos;
  - latencia y tokens por caso.
- Dos modos:
  - LLM guionado en CI, rápido y determinista;
  - nocturno o a mano con Ollama real (o Nebius), con un reporte comparable
    entre versiones de prompt o modelo.

**CHECK:**
- `python -m evals.run --model real` genera un reporte (JSON + markdown) con las
  métricas.
- CI falla si la precisión de riesgo baja del umbral acordado.

### 2.4 Observabilidad y costo
- Trazas por ticket y por turno de chat (OpenTelemetry o LangSmith), con un span
  por nodo del grafo.
- Tokens y costo por tenant y por modelo, a partir de `usage_metadata` de
  LangChain, guardados en una tabla `llm_usage`.
- Latencia p95 por nodo.
- Logs en JSON con `request_id` / `ticket_id` de correlación.
- Dashboard de costo real, que reemplace la heurística fija de ahorro (ítem 8.4
  del plan).

**CHECK:**
- Un ticket muestra su traza completa (supervisor → policy → …).
- El dashboard muestra tokens y costo del mes por tenant a partir de datos reales.

### 2.5 Row-Level Security en Postgres
Hoy el aislamiento entre tenants depende solo de filtrar por `tenant_id` en
cada consulta. RLS lo agrega como segunda capa a nivel de base de datos, así un
filtro olvidado no expone datos de otra empresa.

**CHECK:** una consulta sin filtro de tenant, ejecutada con el rol de la app y
el `tenant_id` de sesión fijado, no devuelve filas de otro tenant (test contra
Postgres).

### 2.6 Refactor de `src/agent/concierge.py` (747 líneas)
Separar en módulos con responsabilidades claras:
- navegación del repo (árbol, rutas, lectura de archivos);
- diagnóstico de servicios;
- armado del prompt;
- post-procesado (grounding, footers, redacción).

**CHECK:** ningún módulo supera ~300 líneas y los tests existentes pasan sin
cambios de comportamiento.

---

## 3. Experiencia de usuario y producto

### 3.1 Respuestas en streaming (SSE)
Hoy el 8B deja la pantalla quieta de 30 a 60 s. Con SSE se pueden mostrar los
pasos ("buscando en el repo…", "revisando logs…", "consultando políticas…") y
luego la respuesta.

**CHECK:** el primer evento llega en menos de 1 s y el UI muestra al menos un
paso intermedio antes de la respuesta final.

### 3.2 Historial y conversaciones
El historial se pierde al recargar la página, aunque el servidor lo guarda en el
checkpointer. Tampoco existe un botón de "nueva conversación".

- `GET /api/chat/history` y un botón "Nueva conversación" (nuevo `thread_id`).

**CHECK:** recargar la página muestra la conversación previa, y "Nueva
conversación" empieza con el contexto vacío.

### 3.3 Citas de las fuentes
Cada respuesta debería indicar qué documento, archivo o línea la respaldó. Los
datos ya existen: los chunks del RAG tienen un encabezado "Documento / Sección"
y los archivos del repo tienen ruta y número de línea.

**CHECK:** una respuesta basada en el RAG o en el repo muestra sus fuentes, y
estas pasan el validador de grounding.

### 3.4 Seguimiento del ticket y errores legibles
- El polling de `useChat.ts` se detiene al minuto (`POLL_MAX_ATTEMPTS = 12`),
  aunque el 8B pueda tardar más, así que el usuario nunca se entera del
  resultado. Hay que reemplazarlo por SSE/notificaciones o por un polling con
  backoff sin tope corto.
- Un error 422 de FastAPI (`detail` es una lista) se muestra como
  `[object Object]`.

**CHECK:**
- Un ticket que tarda 3 minutos igual notifica su resultado en el chat.
- Un mensaje demasiado largo muestra un error legible.

### 3.5 Feedback del usuario
Pulgar arriba/abajo en cada respuesta, guardado con el turno correspondiente,
para alimentar el dataset de evaluación (2.3) y un panel de calidad para el admin.

**CHECK:** el voto se guarda con referencia al turno, y el admin ve la tasa de
satisfacción por semana.

### 3.6 Integraciones que venden
- Bot de Slack/Teams: el mismo Concierge, otro canal.
- Aviso al ITSM (Jira/ServiceNow) cuando el ticket se resuelve o escala. Es lo
  que prometía ADR-004 y le daría uso real a `webhook_url`.

**CHECK:** un ticket creado por webhook recibe el resultado en el `webhook_url`
del tenant (firmado con HMAC).

### 3.7 Optimización de costo
- Enviar las preguntas simples o FAQ al modelo chico y solo las que lo necesitan
  al grande.
- Cache semántico de respuestas a preguntas frecuentes de políticas, invalidado
  cuando se re-sube el documento.

**CHECK:** en el set de evaluación, el costo por caso baja sin que la precisión
caiga por debajo del umbral.

---

## Orden recomendado

| Paso | Qué | Por qué primero |
| :-- | :-- | :-- |
| 1 | Sección 1 (1.1–1.4) | Barato; elimina lo que un reviewer marcaría de inmediato. |
| 2 | 2.1 y 2.2 | Hoy un solo usuario puede congelar el servidor y un reinicio pierde tickets. |
| 3 | 2.3 y 2.4 | Evaluación y observabilidad: la mayor señal de nivel senior; además dan los datos para 3.7 y 8.4. |
| 4 | 3.1–3.5 | La experiencia que se nota en una demo. |
| 5 | 2.5, 2.6, 3.6, 3.7 | Profundidad adicional una vez que lo anterior está firme. |
