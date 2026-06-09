#!/bin/sh
# Entrypoint del contenedor.
# - RUN_MODE=once → ejecuta una vez y sale (útil para CI o cron del host).
# - RUN_MODE=cron → programa la corrida con CRON_SCHEDULE dentro del contenedor.

set -eu

RUN_MODE="${RUN_MODE:-once}"
CRON_SCHEDULE="${CRON_SCHEDULE:-*/30 * * * *}"

run_once() {
    echo "[entrypoint] corriendo ingesta una vez ($(date -Iseconds))"
    exec python -m app.main
}

if [ "$RUN_MODE" = "once" ]; then
    run_once
fi

if [ "$RUN_MODE" = "cron" ]; then
    echo "[entrypoint] modo cron — schedule: $CRON_SCHEDULE  TZ=${TZ:-?}"
    LOG=/var/log/ttfa-kpi-ingest.log
    touch "$LOG"

    # Volcar todo el entorno actual a un archivo, para que cron lo herede.
    # (cron arranca con un PATH y env vacíos.)
    ENV_FILE=/etc/ttfa.env
    {
        printenv | sed 's/^\([^=]*\)=\(.*\)$/export \1='\''\2'\''/'
    } > "$ENV_FILE"

    # Crontab: carga el entorno y ejecuta la app.
    CRON_FILE=/etc/cron.d/ttfa-kpi
    cat > "$CRON_FILE" <<EOF
$CRON_SCHEDULE root . $ENV_FILE; cd /app && python -m app.main >> $LOG 2>&1
EOF
    chmod 0644 "$CRON_FILE"
    crontab "$CRON_FILE"

    # Corrida inicial al levantar el contenedor (no esperar al primer tick).
    echo "[entrypoint] corrida inicial al levantar..."
    python -m app.main >> "$LOG" 2>&1 || echo "[entrypoint] la corrida inicial falló, ver $LOG"

    # cron en foreground + tail del log para que docker logs muestre todo.
    cron
    exec tail -F "$LOG"
fi

echo "[entrypoint] RUN_MODE desconocido: $RUN_MODE (esperado: once|cron)" >&2
exit 64
