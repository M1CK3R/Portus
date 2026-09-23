// Cliente MQTT 3.1.1 mínimo sobre WebSocket (CODESTYLE JS-2: el sinóptico se
// actualiza solo por suscripción MQTT sobre WebSocket; prohibido el polling).
// Implementa lo justo para conectar, suscribirse a `portus/#` y recibir
// PUBLISH entrantes (QoS 0/1) que el sinóptico interpreta. Sin dependencias
// externas (A-8: sin frameworks).

export class ClienteMqtt {
  constructor({ url, idCliente = "portus-navegador", usuario = "", contrasena = "", alMensaje, alConectar, alPerder }) {
    this._url = url;
    this._idCliente = idCliente;
    this._usuario = usuario;
    this._contrasena = contrasena;
    this._alMensaje = alMensaje || (() => {});
    this._alConectar = alConectar || (() => {});
    this._alPerder = alPerder || (() => {});
    this._ws = null;
    this._paqueteId = 1;
    this._latido = null;
  }

  iniciar() {
    this._abrir();
  }

  detener() {
    if (this._latido) {
      clearInterval(this._latido);
      this._latido = null;
    }
    if (this._ws) {
      this._ws.onclose = null;
      try {
        this._ws.close();
      } catch {
        // ignorar: el socket ya podía estar cerrado (D-6)
      }
      this._ws = null;
    }
  }

  _abrir() {
    let ws;
    try {
      ws = new WebSocket(this._url, ["mqtt"]);
    } catch (error) {
      console.warn("[mqtt] no se pudo construir el WebSocket:", error);
      this._alPerder("no_construible");
      return;
    }
    ws.binaryType = "arraybuffer";
    this._ws = ws;
    ws.onopen = () => this._conectar();
    ws.onmessage = (evento) => this._recibir(evento);
    ws.onclose = (evento) => {
      console.warn("[mqtt] WebSocket cerrado:", evento.code, evento.reason);
      this._alPerder("desconectado");
    };
    ws.onerror = () => {
      console.warn("[mqtt] error de WebSocket (¿broker caído o credenciales malas?)");
      this._alPerder("error");
    };
  }

  _conectar() {
    // CONNECT MQTT 3.1.1: protocolo, sesión limpia, keepalive 60s.
    // Flags 0xC2 = clean session + username + password (el broker rechaza
    // anónimos: mosquitto_dev.conf allow_anonymous false, §5.5).
    const id = new TextEncoder().encode(this._idCliente);
    const usuario = new TextEncoder().encode(this._usuario);
    const contrasena = new TextEncoder().encode(this._contrasena);
    const cuerpo = [
      0x00, 0x04, 0x4d, 0x51, 0x54, 0x54, // "MQTT"
      0x04, // nivel 3.1.1
      0xc2, // flags: clean session | username | password
      0x00, 0x3c, // keepalive 60s
      ...this._longitud(id), // client id
      ...id,
      ...this._longitud(usuario),
      ...usuario,
      ...this._longitud(contrasena),
      ...contrasena,
    ];
    this._enviar(0x10, cuerpo);
    this._latido = setInterval(() => this._ping(), 45000);
  }

  suscribir(filtro) {
    const f = new TextEncoder().encode(filtro);
    const id = this._paqueteId++;
    const cuerpo = [
      (id >> 8) & 0xff, id & 0xff, // packet id
      ...this._longitud(f),
      ...f,
      0x01, // QoS 1
    ];
    this._enviar(0x82, cuerpo);
  }

  _ping() {
    // PINGREQ (0xC0): mantiene viva la conexión WS.
    this._enviar(0xc0, []);
  }

  _enviar(tipo, cuerpo) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
      return;
    }
    const cabecera = this._longitudRestante(cuerpo.length);
    const paquete = new Uint8Array(cabecera.length + cuerpo.length + 1);
    paquete[0] = tipo;
    paquete.set(cabecera, 1);
    paquete.set(cuerpo, 1 + cabecera.length);
    try {
      this._ws.send(paquete);
    } catch {
      // si el envío falla, la reconexión la dispara onclose (D-6)
    }
  }

  _recibir(evento) {
    const bytes = new Uint8Array(evento.data);
    if (bytes.length === 0) {
      return;
    }
    const tipo = bytes[0] & 0xf0;
    if (tipo === 0x20) {
      // CONNACK: el byte 3 (índice 3) es el código de retorno (0 = aceptado).
      const rc = bytes.length > 3 ? bytes[3] : 1;
      if (rc !== 0) {
        console.warn("[mqtt] CONNACK rechazado (rc=" + rc + ", 5=no autorizado). Revisá MQTT_TABLERO_USUARIO/CONTRASENA vs passwd_mosquitto.");
        this._alPerder("no_autorizado");
        return;
      }
      console.info("[mqtt] conectado y suscrito a portus/#");
      this.suscribir("portus/#");
      this._alConectar();
      return;
    }
    if (tipo === 0x30 || tipo === 0x32) {
      // PUBLISH entrante (QoS 0 o 1).
      const { topico, carga } = this._parsearPublicar(bytes);
      this._alMensaje(topico, carga);
    }
  }

  _parsearPublicar(bytes) {
    let i = 1;
    const { valor: longitudRestante, leidos } = this._leerLongitudRestante(bytes, i);
    i += leidos;
    const largoTopico = (bytes[i] << 8) | bytes[i + 1];
    i += 2;
    const topico = new TextDecoder().decode(bytes.slice(i, i + largoTopico));
    i += largoTopico;
    // QoS 1 trae un packet id de 2 bytes antes de la carga.
    if ((bytes[0] & 0x0f) === 0x02) {
      i += 2;
    }
    const fin = 1 + longitudRestante;
    const carga = new TextDecoder().decode(bytes.slice(i, fin));
    return { topico, carga };
  }

  _leerLongitudRestante(bytes, desde) {
    let valor = 0;
    let multiplicador = 1;
    let leidos = 0;
    for (let k = 0; k < 4; k += 1) {
      const b = bytes[desde + k];
      valor += (b & 0x7f) * multiplicador;
      leidos += 1;
      if ((b & 0x80) === 0) {
        break;
      }
      multiplicador *= 128;
    }
    return { valor, leidos };
  }

  _longitud(cadena) {
    return [(cadena.length >> 8) & 0xff, cadena.length & 0xff];
  }

  _longitudRestante(n) {
    const out = [];
    let x = n;
    do {
      let b = x % 128;
      x = Math.floor(x / 128);
      if (x > 0) {
        b += 128;
      }
      out.push(b);
    } while (x > 0);
    return new Uint8Array(out);
  }
}
