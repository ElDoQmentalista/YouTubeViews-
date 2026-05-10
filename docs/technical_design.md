# Diseño Técnico — Radar DoQ

**Documento:** Technical Design (TDD)
**Producto:** Radar DoQ — Sistema de Rastreo de Competidores en IG/FB
**Basado en:** PRD v0.1 (10/05/2026)
**Versión:** 0.1 — Borrador inicial
**Autor:** Equipo técnico
**Fecha:** 10 de mayo de 2026

---

## 1. Objetivo del documento

Traducir el PRD a una arquitectura concreta, ejecutable y dimensionada al presupuesto declarado (< USD 80/mes MVP, < USD 200/mes a 30 cuentas). Define componentes, contratos de datos, integraciones externas, decisiones de stack y plan de rollout.

No define: lista final de competidores, copy de notificaciones, política legal de uso de adaptaciones (queda en manos de Inri).

---

## 2. Resumen de la arquitectura

```
┌──────────────────────────────────────────────────────────────────┐
│                         RADAR DOQ                                │
│                                                                  │
│   ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│   │  Scheduler  │───▶│  Poller      │───▶│  Detector /      │    │
│   │  (Inngest / │    │  Workers     │    │  Deduper         │    │
│   │   Cron)     │    │  (Apify)     │    │  (Postgres)      │    │
│   └─────────────┘    └──────────────┘    └────────┬─────────┘    │
│                                                   │              │
│                                                   ▼              │
│   ┌──────────────────────────┐         ┌────────────────────┐    │
│   │  Notifier                │◀────────│  Asset Pipeline    │    │
│   │  (Telegram bot)          │         │  download → ASR    │    │
│   └──────────────────────────┘         │  → metadata        │    │
│                                        └─────────┬──────────┘    │
│                                                  │               │
│                                                  ▼               │
│                                        ┌────────────────────┐    │
│                                        │  Replication Pack  │    │
│                                        │  (LLM analysis)    │    │
│                                        └─────────┬──────────┘    │
│                                                  │               │
│                                                  ▼               │
│   ┌──────────────────────────┐         ┌────────────────────┐    │
│   │  Web Dashboard           │◀────────│  Postgres + S3     │    │
│   │  (Next.js)               │         │                    │    │
│   └──────────────────────────┘         └────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

Flujo principal (happy path):

1. **Scheduler** dispara cada 5–10 min jobs de polling por cuenta.
2. **Poller** invoca actor de Apify (IG / FB) → recibe lista de últimos N posts/reels.
3. **Detector** compara contra DB; si hay items nuevos, los inserta como `detection` con estado `new`.
4. **Notifier** envía mensaje Telegram inmediato (caption truncado + thumbnail + link + botón).
5. **Asset Pipeline** (asíncrono) descarga el video, lanza Whisper, extrae metadata.
6. **Replication Pack** (asíncrono, on-demand o auto si la cuenta es `high_priority`) llama LLM para producir el análisis estructural y la sugerencia de adaptación por canal.
7. **Dashboard** muestra detecciones con filtros y vista detalle.

---

## 3. Componentes

### 3.1 Scheduler

- **Implementación:** Inngest (preferido por reintentos nativos, observabilidad, cuotas free generosas) o cron de la plataforma (Railway cron / GitHub Actions).
- **Trigger:** función `poll_account(account_id)` por cada cuenta activa, cada N minutos según `account.poll_interval_minutes`.
- **Concurrencia:** límite global de 5 polls simultáneos (evita estallar rate limits del proveedor).
- **Idempotencia:** el job no produce efectos secundarios si no hay nuevas detecciones.

### 3.2 Poller / Adapters

Capa de abstracción `SourceAdapter` con dos implementaciones MVP:

```python
class SourceAdapter(Protocol):
    def fetch_recent(self, account: Account, limit: int = 20) -> list[RawPost]: ...
```

- `InstagramApifyAdapter` — usa actor `apify/instagram-scraper`.
- `FacebookApifyAdapter` — usa actor `apify/facebook-pages-scraper`.

Ventaja del patrón: cuando Meta rompa un actor, sustituimos sin tocar el detector. Adaptador secundario (de respaldo) se agrega como `InstagramRapidAPIAdapter` en Fase 3.

**Resiliencia:**
- Reintentos con backoff exponencial (2s, 4s, 8s, 16s) ante 5xx / timeouts.
- Circuit breaker por adaptador: si fallan > 3 polls consecutivos, se silencia 30 min y notifica a Inri.

### 3.3 Detector / Deduper

- Para cada `RawPost` recibido:
  - Clave de deduplicación: `(platform, native_id)`.
  - Hash secundario: `sha256(caption_normalized + media_url_signature)` (cubre re-publicaciones con nuevo ID).
  - Si no existe → insertar `detections` con `state='new'` y emitir evento `detection.created`.
- Clasificación de tipo: `reel | video | image_post | carousel` derivado del payload del actor.

### 3.4 Notifier (Telegram)

- Bot único (`@radardoq_bot`), chat privado de Inri (chat_id en env).
- Mensaje plantilla:
  ```
  🆕 [{canal}] {cuenta} publicó un {tipo}
  📝 {caption_truncado}
  🔗 {link_original}
  [Generar paquete] [Marcar replicado] [Descartar]
  ```
- Botones inline → callback queries → endpoint webhook que actualiza `detection.state`.
- Modo silencio: tabla `quiet_hours(start, end, timezone)`. Si cae dentro, los mensajes se encolan y se envían al final de la ventana en un digest.

### 3.5 Asset Pipeline

Orquestado como cadena de jobs por `detection_id`:

1. `download_media` → descarga video al bucket S3 en `s3://radardoq/competidores/{canal}/{cuenta}/{YYYY-MM-DD}_{tipo}_{native_id}/original.mp4`.
2. `extract_audio` → `ffmpeg -vn -acodec libmp3lame audio.mp3`.
3. `transcribe_audio` → Whisper API (`whisper-1`, idioma `es`). Output: texto + timestamps por segmento.
4. `extract_metadata` → parsea caption en hashtags (`#`), menciones (`@`), música (campo nativo del actor cuando exista), duración, métricas snapshot.
5. `mark_pipeline_done` → setea `detection.state='enriched'`.

Cada paso es idempotente y reintentable; el estado se persiste en `detection.pipeline_status` (JSON con flags por etapa).

### 3.6 Replication Pack (LLM)

- Trigger: automático si `account.priority='high'`, manual si no (botón Telegram o dashboard).
- Modelo: Claude Sonnet 4.6 (default) o GPT-4-class (fallback). Configurable.
- Prompt estructurado en bloques: `{transcripción}`, `{caption}`, `{hashtags}`, `{canal_destino}`, `{guía_estilo_canal}`.
- Salida JSON validada con esquema:
  ```json
  {
    "gancho": "string (primeros 3s)",
    "estructura": { "intro": "...", "desarrollo": "...", "payoff": "..." },
    "tono": "string",
    "elementos_visuales": ["..."],
    "adaptacion_canal": {
      "canal": "doqmentalista|oraculo|soydedios",
      "propuesta": "...",
      "advertencias_yt": ["palabra1", "palabra2"]
    }
  }
  ```
- Las "guías de estilo" de cada canal se mantienen como assets versionados en `prompts/styles/{canal}.md` para que Inri pueda iterarlas sin tocar código.

### 3.7 Dashboard (Next.js)

- Páginas:
  - `/` — lista de detecciones, filtros (canal, cuenta, tipo, estado, rango), búsqueda full-text.
  - `/detection/{id}` — vista detalle (video embebido desde S3 firmado, transcripción, metadata, paquete de replicación).
  - `/accounts` — CRUD de cuentas vigiladas.
  - `/settings` — quiet hours, integraciones, presupuestos.
- Auth: usuario único; magic link por email o sesión persistente con password (Lucia / NextAuth).
- Búsqueda full-text: índice GIN de Postgres sobre `transcript_tsv`.

---

## 4. Modelo de datos (Postgres)

```sql
-- Canales internos del usuario
CREATE TABLE channels (
  id          TEXT PRIMARY KEY,        -- 'doqmentalista' | 'oraculo' | 'soydedios' | 'general'
  name        TEXT NOT NULL,
  style_guide TEXT                      -- referencia al prompt de estilo
);

-- Cuentas de competidores vigiladas
CREATE TABLE accounts (
  id                      UUID PRIMARY KEY,
  platform                TEXT NOT NULL CHECK (platform IN ('instagram','facebook')),
  handle                  TEXT NOT NULL,
  channel_id              TEXT REFERENCES channels(id),
  tags                    TEXT[],
  priority                TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal','high')),
  poll_interval_minutes   INT  NOT NULL DEFAULT 10,
  active                  BOOLEAN NOT NULL DEFAULT TRUE,
  last_polled_at          TIMESTAMPTZ,
  consecutive_failures    INT NOT NULL DEFAULT 0,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (platform, handle)
);

-- Detecciones (un post o reel detectado)
CREATE TABLE detections (
  id              UUID PRIMARY KEY,
  account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  native_id       TEXT NOT NULL,           -- id del proveedor
  content_hash    TEXT NOT NULL,
  type            TEXT NOT NULL CHECK (type IN ('reel','video','image_post','carousel')),
  caption         TEXT,
  hashtags        TEXT[],
  mentions        TEXT[],
  music           JSONB,
  duration_s      INT,
  metrics         JSONB,                   -- views/likes/comments snapshot
  original_url    TEXT NOT NULL,
  published_at    TIMESTAMPTZ,
  detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  state           TEXT NOT NULL DEFAULT 'new'
                  CHECK (state IN ('new','enriched','notified','adapted','archived','irrelevant')),
  user_label      TEXT,                    -- 'replicar_urgente' | 'descartar' | null
  pipeline_status JSONB NOT NULL DEFAULT '{}'::jsonb,
  s3_prefix       TEXT,
  transcript      TEXT,
  transcript_tsv  TSVECTOR,
  UNIQUE (account_id, native_id)
);

CREATE INDEX detections_state_idx        ON detections(state);
CREATE INDEX detections_detected_at_idx  ON detections(detected_at DESC);
CREATE INDEX detections_transcript_gin   ON detections USING GIN (transcript_tsv);

-- Paquete de replicación generado por LLM
CREATE TABLE replication_packs (
  id            UUID PRIMARY KEY,
  detection_id  UUID NOT NULL REFERENCES detections(id) ON DELETE CASCADE,
  channel_id    TEXT NOT NULL REFERENCES channels(id),
  model         TEXT NOT NULL,
  payload       JSONB NOT NULL,
  cost_usd      NUMERIC(10,4),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Notificaciones enviadas
CREATE TABLE notifications (
  id            UUID PRIMARY KEY,
  detection_id  UUID NOT NULL REFERENCES detections(id) ON DELETE CASCADE,
  channel       TEXT NOT NULL DEFAULT 'telegram',
  status        TEXT NOT NULL,              -- 'queued','sent','failed'
  sent_at       TIMESTAMPTZ,
  error         TEXT
);

-- Ventanas de silencio
CREATE TABLE quiet_hours (
  id          SERIAL PRIMARY KEY,
  start_time  TIME NOT NULL,
  end_time    TIME NOT NULL,
  timezone    TEXT NOT NULL DEFAULT 'America/Mexico_City'
);

-- Tracking de costos
CREATE TABLE cost_events (
  id          BIGSERIAL PRIMARY KEY,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source      TEXT NOT NULL,                -- 'apify','whisper','llm','storage'
  units       NUMERIC,
  cost_usd    NUMERIC(10,4) NOT NULL,
  ref         JSONB
);
```

Trigger para mantener `transcript_tsv` sincronizado con `transcript` (`to_tsvector('spanish', ...)`).

---

## 5. Almacenamiento de medios (S3)

- Bucket único `radardoq-media`, region cercana (us-east-1 o eu-central-1).
- Layout:
  ```
  competidores/{canal}/{cuenta}/{YYYY-MM-DD}_{tipo}_{native_id}/
    original.mp4
    audio.mp3
    thumbnail.jpg
    transcript.json
  ```
- **Lifecycle:** mover a Glacier Deep Archive a los 90 días; eliminar a los 365.
- **Acceso:** URLs presignadas con TTL 1h para el dashboard. Bucket privado, CloudFront opcional en v1.
- Alternativa más barata MVP: Cloudflare R2 (sin costos de egress).

---

## 6. APIs internas

API REST en backend (FastAPI), consumida por dashboard y bot:

| Método | Path | Descripción |
|--------|------|-------------|
| GET    | `/api/accounts` | Lista cuentas |
| POST   | `/api/accounts` | Crea cuenta |
| PATCH  | `/api/accounts/{id}` | Actualiza cuenta |
| DELETE | `/api/accounts/{id}` | Elimina cuenta |
| GET    | `/api/detections` | Lista con filtros (`channel`, `state`, `q`, `from`, `to`) |
| GET    | `/api/detections/{id}` | Detalle |
| POST   | `/api/detections/{id}/replicate` | Genera replication pack on-demand |
| PATCH  | `/api/detections/{id}` | Cambia `user_label` / `state` |
| GET    | `/api/detections/{id}/media` | Devuelve URLs presignadas |
| POST   | `/api/webhooks/telegram` | Callback de Telegram (botones inline) |
| POST   | `/api/webhooks/inngest` | Callback de scheduler |
| GET    | `/api/health` | Healthcheck |
| GET    | `/api/costs/current_month` | Gasto acumulado vs presupuesto |

Auth: token bearer (single-user) en header. CORS restringido al dominio del dashboard.

---

## 7. Decisiones de stack

| Capa | Elección MVP | Razón | Alternativa |
|------|--------------|-------|-------------|
| Lenguaje backend | **Python 3.12** | Mejor SDK Whisper / Apify / async | Node.js |
| Framework API | **FastAPI** | Async, tipos, OpenAPI gratis | Express |
| Scheduler | **Inngest** (free tier) | Reintentos, observabilidad | GitHub Actions cron |
| Scraping | **Apify** | Mantenido, multi-actor | Phantombuster |
| ASR | **Whisper API** (`whisper-1`) | < USD 0.006 / min, español OK | Self-host whisper.cpp |
| LLM análisis | **Claude Sonnet 4.6** | Mejor en estilo/tono en español | GPT-4-class |
| DB | **Postgres 16** (Neon) | Free tier 0.5 GB, FT search | Supabase |
| Object storage | **Cloudflare R2** | Sin egress | AWS S3 |
| Bot | **Telegram Bot API** | Gratis, push nativo | WhatsApp Business |
| Dashboard | **Next.js 15 + Tailwind** | Auth + SSR + UI rápida | Streamlit |
| Hosting | **Railway** (backend) + **Vercel** (dashboard) | Despliegue trivial | Fly.io |
| Observabilidad | **Sentry** + **Logtail** | Free tier suficiente | Better Stack |

---

## 8. Costos estimados (mensual, 30 cuentas, 10 min poll)

| Concepto | Cálculo | USD/mes |
|----------|---------|---------|
| Apify (IG+FB scrapers) | 30 cuentas × 6 polls/h × 24h × 30d ≈ 130k results | ~45 |
| Whisper API | ~150 reels/mes × 60s = 150 min × $0.006 | ~1 |
| Claude Sonnet (replication packs) | ~150 packs × ~3k tokens ≈ 450k tokens | ~2 |
| Postgres (Neon Pro) | DB pequeña | 0–19 |
| R2 storage | 150 reels × 30 MB × 12 meses ≈ 54 GB | ~1 |
| Railway backend | 1 servicio | ~5 |
| Vercel dashboard | hobby | 0 |
| Telegram | gratis | 0 |
| Sentry / Logtail | free tiers | 0 |
| **Total estimado** | | **~55–75** |

Cumple con el target del PRD (< USD 80 MVP, < USD 200 escalado). Caps duros configurables en `cost_events` con alerta al 70%.

---

## 9. Requisitos no funcionales — cómo se cumplen

| Requisito | Solución |
|-----------|----------|
| Latencia detección < 15 min p50 | Polling 10 min + worker side ≤ 30s; notificación push inmediata |
| Latencia paquete < 30 min | Pipeline asíncrono, cada etapa ≤ 5 min; LLM streaming |
| Disponibilidad 99% | Healthcheck cada 5 min → BetterUptime → alerta Telegram. Sin SLA de proveedores garantizado, pero múltiples adaptadores |
| Privacidad | Bucket privado; URLs presignadas; sin redistribución; logs sin PII |
| Costos < USD 80/200 | `cost_events` + cap mensual + degradación de polling cuando se acerca al límite |
| Idioma español | Whisper `language=es`; prompts y UI en español |

---

## 10. Seguridad

- Secretos en variables de entorno gestionadas por Railway / Vercel; nunca en repo.
- Bucket S3/R2 privado; ningún recurso público.
- Rate limit en API pública (slowapi 60 req/min/IP).
- Auth single-user con session cookie HttpOnly + CSRF en mutaciones.
- Webhook de Telegram firmado con secret token; rechazo de payloads no firmados.
- Logs sanitizan tokens y captions sensibles.
- Backups Postgres diarios (retención 7 días).

---

## 11. Observabilidad

- **Métricas clave** (Prometheus push o Logtail):
  - `poll_duration_seconds{platform}`
  - `detections_new_total{channel,platform}`
  - `pipeline_stage_duration_seconds{stage}`
  - `llm_cost_usd_total{model}`
  - `notification_latency_seconds`
- **Alertas:**
  - 0 detecciones globales en 6h → posible bloqueo de scraper.
  - Tasa de fallo de polling > 30% en 1h.
  - Gasto acumulado > 70% del cap.
  - Healthcheck caído > 5 min.
- **Trazas:** un `correlation_id` por detección recorre poll → enrich → notify → pack.

---

## 12. Plan de implementación (mapeo a Roadmap del PRD)

### Fase 0 — Validación (1 semana)
- Repo + CI básico (pytest, ruff, type-check).
- Spike de Apify con 3 cuentas reales (1 por canal).
- Validar tasa de éxito y costo real con muestra de 1 semana.

### Fase 1 — MVP (4–6 semanas)

| Semana | Entregables |
|--------|-------------|
| 1 | Esquema DB, migrations, FastAPI esqueleto, deploy Railway |
| 2 | Adapters Apify (IG+FB), scheduler Inngest, poll job, dedupe |
| 3 | Asset pipeline (download, ffmpeg, Whisper), bucket R2 |
| 4 | Bot Telegram (notify + callbacks), quiet hours |
| 5 | Dashboard Next.js (lista, detalle, CRUD cuentas) |
| 6 | Búsqueda full-text, hardening, observabilidad, 15 cuentas en producción |

### Fase 2 — Replication Pack (3–4 semanas)
- Esquema JSON + validación.
- Prompt engineering por canal (3 guías de estilo).
- Filtro YT de palabras penalizadas (lista mantenida en `prompts/yt_blocklist.txt`).
- Integración con botones Telegram + dashboard.

### Fase 3 — Escalado
- Adaptador secundario (RapidAPI / Playwright) detrás de feature flag.
- Caps de costo dinámicos.
- 30 cuentas activas.
- Métricas de adopción.

---

## 13. Riesgos técnicos y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|--------|--------------|------------|
| Apify cambia/rompe actores | Alta | Patrón Adapter; segundo adaptador en staging |
| Whisper falla con audio ruidoso/musical | Media | `prompt` contextual + reintento con modelo grande |
| LLM produce JSON inválido | Media | `response_format=json_schema` + validador Pydantic + reintento |
| Postgres hits free-tier limit | Media | Mover binarios a R2 (no en DB); paginar listados |
| Costos disparados por polling agresivo | Media | Cap duro + degradación automática a 30 min |
| Telegram bloqueado por volumen | Baja | Digest mode; rate limit 30 msg/seg de la API es suficiente |
| Usuario único = SPOF de adopción | Alta | UX mobile-first del bot; tests de usabilidad con Inri en Fase 1 |

---

## 14. Preguntas abiertas (técnicas)

1. **¿On-demand o auto para replication pack?** Recomendación: auto solo si `priority='high'`; resto on-demand para controlar costo de LLM.
2. **¿Self-host Whisper?** A 150 reels/mes, no compensa. Re-evaluar a 1k+/mes.
3. **¿Cuándo extraer keyframes?** Para "elementos visuales clave" del pack, considerar `ffmpeg -vf select` cada N segundos + Claude Vision en Fase 2.
4. **¿Versionado de guías de estilo?** Sí, Git → cada pack guarda el `style_guide_sha`.
5. **¿Multi-tenant futuro?** No en MVP. Si en algún momento se abre a otros creadores, refactor a `org_id` en todas las tablas.

---

## 15. Anexo — Diagrama de estados de `detection`

```
   [new] ──(asset pipeline ok)──▶ [enriched] ──(notify ok)──▶ [notified]
     │                                  │                          │
     │                                  │                          ├──▶ [adapted]      (Inri publica)
     │                                  │                          ├──▶ [archived]     (Inri archiva)
     │                                  │                          └──▶ [irrelevant]   (Inri descarta)
     │                                  │
     └──(pipeline fail final)──────────▶ [enrich_failed]  (alerta)
```

---

## 16. Definition of Done — MVP

- [ ] 15 cuentas activas en producción (5 por canal).
- [ ] Notificación Telegram en < 15 min p50 medida durante 1 semana.
- [ ] Descarga + transcripción 100% para Reels detectados.
- [ ] Dashboard accesible desde móvil y escritorio.
- [ ] Costos del mes ≤ USD 80.
- [ ] Runbook escrito (qué hacer si Apify cae, si Whisper falla, si la DB se llena).
- [ ] Inri ha usado el bot al menos 7 días seguidos sin intervención del dev.
