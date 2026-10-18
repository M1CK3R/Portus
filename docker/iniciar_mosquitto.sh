#!/bin/sh
# Arranque del broker en Docker: genera el archivo de contraseñas a partir de
# config/portus.env y luego ejecuta mosquitto. Así las claves de los servicios
# y las del broker siempre coinciden (README §3.4 hace este paso a mano).
set -eu

ENV_PORTUS=/portus/portus.env
DIR=/run/portus

if [ ! -f "$ENV_PORTUS" ]; then
    echo "iniciar_mosquitto: falta config/portus.env (cp config/portus.env.ejemplo config/portus.env)" >&2
    exit 1
fi

# Mismo criterio que los servicios de Python: KEY=valor, se ignoran comentarios,
# se recortan espacios y gana la última aparición.
leer() {
    valor=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$ENV_PORTUS" | tail -n 1 | tr -d '\r' \
        | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    echo "${valor:-$2}"
}

agregar_usuario() {
    if [ -z "$1" ] || [ -z "$2" ]; then
        echo "iniciar_mosquitto: usuario '$1' sin contraseña en portus.env; no podrá conectarse" >&2
        return 0
    fi
    mosquitto_passwd -b "$DIR/passwd_mosquitto" "$1" "$2"
    echo "iniciar_mosquitto: usuario MQTT '$1' listo"
}

umask 077
mkdir -p "$DIR"
: > "$DIR/passwd_mosquitto"

# Mismos usuarios y valores por omisión que leen puente, web y mensajería.
agregar_usuario "$(leer MQTT_USUARIO portus-puente)" "$(leer MQTT_CONTRASENA portus)"
agregar_usuario "$(leer MQTT_TABLERO_USUARIO portus-tablero)" "$(leer MQTT_TABLERO_CONTRASENA portus)"
agregar_usuario "$(leer MSG_MQTT_USUARIO portus-msg)" "$(leer MSG_MQTT_CONTRASENA '')"

cp /portus/acl_portus "$DIR/acl_portus"
# El broker suelta privilegios y lee estos archivos como «mosquitto».
chown -R mosquitto:mosquitto "$DIR"

exec mosquitto -c /portus/mosquitto.conf
