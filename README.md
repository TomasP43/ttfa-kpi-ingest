# ttfa-kpi-ingest

Servicio que ingesta los reportes de daños/arribos que llegan por mail a un
buzón M365, deduplica, y deja archivos `.xlsx` planos listos para alimentar el
libro **KPI Diario de Exportación** de TTFA.

## Qué resuelve

Hoy las hojas "Pegar Chile" y "Brasil Impo DB" del KPI se llenan **a mano**
copiando y pegando datos de mails. Es lento, error-prone y se duplican filas.
Este servicio:

- Lee Outlook/M365 vía Microsoft Graph (app-only, sin la contraseña del usuario).
- Detecta los mails de Furlong (uno por país) por remitente + asunto.
- Descarga el adjunto correcto y lo parsea.
- Filtra por compañía cuando hace falta (caso Brasil).
- Dedupea (clave fuerte en Chile, fingerprint en Brasil).
- Agrega solo lo nuevo a un `.xlsx` por país; el usuario copia y pega esas filas
  al KPI cuando quiere.

## Fuentes

| País   | Remitente                          | Asunto empieza con          | Adjunto                                  | Hoja origen | Clave de dedup           |
|--------|------------------------------------|-----------------------------|------------------------------------------|-------------|--------------------------|
| Chile  | `Alexis.yanez@furlong.cl`          | `Reporte tasa`              | `REPORTE DE ARRIBOS.xlsx`                | `ARRIBOS`   | `ID_Inspection`          |
| Brasil | `ailen.deretich@furlong.com.ar`    | `REPORTE DAÑOS DESCARGAS`   | regex `Reporte de Da.os.*\.xlsx$`        | `DAÑOS`     | sha1(fecha + VIN + daño) |

## Cómo funciona

```
            ┌──────────────────────────┐
            │ Outlook M365 (buzón TTFA)│
            └──────────┬───────────────┘
                       │ Microsoft Graph (Mail.Read app-only)
                       ▼
        ┌─────────────────────────────┐
        │ find_messages por remitente │
        │ + asunto + lookback días    │
        └──────────┬──────────────────┘
                   │
       ┌───────────┴───────────┐
       ▼                       ▼
 parser CHILE             parser BRASIL
 (hoja ARRIBOS,           (hoja DAÑOS,
  19 columnas)            bloques por compañía)
       │                       │
       ▼                       ▼
 dedup ID_Inspection     dedup row_key (sha1)
       │                       │
       ▼                       ▼
 output/pegar_chile.xlsx   output/brasil_impo_db.xlsx
                                ▲
                                │
                  state/state.json (claves + message_ids ya procesados)
```

### Decisiones de deduplicación

- **Chile**: el archivo es acumulado y trae `ID_Inspection` único por daño.
  Es la clave fuerte. Un VIN con dos daños distintos tiene dos `ID_Inspection`
  distintos → se conservan; las filas idénticas (mismo daño) comparten ID y se
  colapsan.
- **Brasil**: no hay ID confiable y el VIN no es clave (puede repetirse o venir
  vacío). Doble red:
  1. `processed_messages`: cada `message_id` se procesa una sola vez.
  2. `row_key = sha1(fecha + VIN + texto del daño)[:16]`: aunque el mismo mail
     reaparezca o llegue reenviado, no se vuelve a pegar la misma fila.

### Estado

`state/state.json`:

```json
{
  "processed_keys": {
    "chile":  ["<ID_Inspection>", "..."],
    "brasil": ["<row_key>", "..."]
  },
  "processed_messages": ["<graph-message-id>", "..."]
}
```

Si querés re-procesar todo desde cero, borrá el archivo (se va a regenerar
y volver a pegar todo lo histórico del buzón hasta `LOOKBACK_DAYS` atrás).

## Configuración

Toda la config va por variables de entorno (.env). Copiá `.env.example` a `.env`
y completá. Nico (deploy) **solo edita .env**, no hace falta tocar código:

- Credenciales Graph: `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_MAILBOX`.
- Remitentes / asuntos / nombres de adjunto (uno por fuente).
- `BRASIL_COMPANY`: TTFA por default; podés ponerlo en `AUTOPORT` o
  `TRANSPORTE FURLONG` para mirar otros bloques.
- `LOOKBACK_DAYS`: cuántos días atrás revisar mails (default 14).
- `MARK_AS_READ`: si los mails procesados se marcan como leídos (requiere
  `Mail.ReadWrite`).
- `RUN_MODE`: `once` (corre y sale) o `cron` (scheduler interno con
  `CRON_SCHEDULE`).

## Despliegue en un VPS

```bash
git clone <url-del-repo>
cd ttfa-kpi-ingest
cp .env.example .env
$EDITOR .env                     # completar credenciales + buzón
docker compose build
docker compose up -d
docker compose logs -f ingest
```

Salidas:
- `./output/pegar_chile.xlsx`     — hoja **Pegar Chile**, lista para copiar/pegar.
- `./output/brasil_impo_db.xlsx`  — hoja **Brasil Impo DB**.
- `./state/state.json`            — estado persistente (no borrar).

Para forzar una corrida manual sin esperar al cron:

```bash
docker compose run --rm -e RUN_MODE=once ingest
```

## Estructura del proyecto

```
app/
  config.py            — Settings desde .env, validación de credenciales.
  graph_client.py      — Cliente Graph (token client-credentials + adjuntos).
  state.py             — StateStore (carga/guarda state.json).
  writer.py            — append_rows: agrega filas nuevas a un .xlsx/hoja.
  main.py              — Orquestador: run_chile, run_brasil, main().
  parsers/
    chile.py           — parser ARRIBOS + COLUMNS + DEDUP_KEY.
    brasil.py          — parser por bloques + IMPO_COLUMNS + row_key + date_from_filename.
tests/
  test_chile_offline.py
  test_brasil_offline.py
samples/               — opcional, .xlsx anonimizados para tests reproducibles.
docs/SETUP_AZURE.md    — alta de la app en Azure AD / Entra.
Dockerfile, entrypoint.sh, docker-compose.yml
.env.example, .gitignore, requirements.txt
```

## Tests offline

```bash
pip install -r requirements.txt
python -m unittest discover -v tests
```

- No requieren red ni credenciales Graph.
- Si `samples/chile_sample.xlsx` y `samples/brasil_sample.xlsx` existen, se
  usan ésos. Si no, los tests generan una muestra sintética con la misma forma
  e informan en consola qué fuente están usando.
- Brasil verifica como control que `TTFA=0` y `AUTOPORT=2` daños en el sample
  típico.

## Pendientes / próximos pasos

- Subir a `samples/` un par de adjuntos anonimizados reales para que los tests
  los usen automáticamente.
- Pegar las filas nuevas directamente en el libro KPI (hoy se queda en un xlsx
  intermedio para auditar antes de pegar).
- Aplicar **Application Access Policy** en M365 para limitar la app a un solo
  buzón (ver `docs/SETUP_AZURE.md`).
- Alertas (email/Slack) cuando el formato del adjunto cambia y el parser falla.
