// Cliente MQTT 3.1.1 mínimo sobre WebSocket (CODESTYLE JS-2: el sinóptico se
// actualiza solo por suscripción MQTT sobre WebSocket; prohibido el polling).
// Implementa lo justo para conectar, suscribirse a `portus/#` y recibir
// PUBLISH entrantes (QoS 0/1) que el sinóptico interpreta. Sin dependencias
// externas (A-8: sin frameworks).

const REINTENTO_MIN_MS = 1000;
const REINTENTO_MAX_MS = 15000;

export class ClienteMqtt {
  constructor({ url, idCliente, usuario = "", contrasena = "", alMensaje, alConectar, alPerder }) {
    this._url = url;
    // Id único por pestaña: con uno fijo, dos navegadores abiertos se
    // expulsan mutuamente del broker (toma de sesión de MQTT 3.1.1).
    this._idCliente = idCliente || `portus-navegador-${Math.random().toString(36).slice(2, 10)}`;
    this._usuario = usuario;
    this._contrasena = contrasena;
    this._alMensaje = alMensaje || (() => {});
    this._alConectar = alConectar || (() => {});
    this._alPerder = alPerder || (() => {});
    this._ws = null;
    this._paqueteId = 1;
    this._latido = null;
    this._pendiente = new Uint8Array(0);
    this._detenido = false;
    this._esperaReintento = REINTENTO_MIN_MS;
    this._temporizadorReintento = null;
  }

  iniciar() {
    this._detenido = false;
    this._abrir();
  }

  detener() {
    this._detenido = true;
    clearTimeout(this._temporizadorReintento);
    this._pararLatido();
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
      this._programarReintento();
      return;
    }
    ws.binaryType = "arraybuffer";
    this._ws = ws;
    this._pendiente = new Uint8Array(0);
    ws.onopen = () => this._conectar();
    ws.onmessage = (evento) => this._recibir(evento);
    ws.onclose = (evento) => {
      console.warn("[mqtt] WebSocket cerrado:", evento.code, evento.reason);
      this._pararLatido();
      this._alPerder("desconectado");
      this._programarReintento();
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

  _programarReintento() {
    // Reconexión con espera creciente: si el broker o la red caen, el
    // sinóptico vuelve solo sin recargar la página (JS-5).
    if (this._detenido) {
      return;
    }
    clearTimeout(this._temporizadorReintento);
    this._temporizadorReintento = setTimeout(() => this._abrir(), this._esperaReintento);
    this._esperaReintento = Math.min(this._esperaReintento * 2, REINTENTO_MAX_MS);
  }

  _pararLatido() {
    if (this._latido) {
      clearInterval(this._latido);
      this._latido = null;
    }
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
    // WebSocket no respeta los límites de paquete MQTT: un frame puede traer
    // varios paquetes o solo un pedazo de uno. Se acumula y se corta aquí.
    const nuevos = new Uint8Array(evento.data);
    const flujo = new Uint8Array(this._pendiente.length + nuevos.length);
    flujo.set(this._pendiente, 0);
    flujo.set(nuevos, this._pendiente.length);
    let i = 0;
    while (flujo.length - i >= 2) {
      const largo = this._leerLongitudRestante(flujo, i + 1);
      if (largo === null) {
        break; // longitud restante incompleta: esperar el siguiente frame
      }
      const total = 1 + largo.leidos + largo.valor;
      if (flujo.length - i < total) {
        break;
      }
      this._procesarPaquete(flujo.slice(i, i + total));
      i += total;
    }
    this._pendiente = flujo.slice(i);
  }

  _procesarPaquete(bytes) {
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
      this._esperaReintento = REINTENTO_MIN_MS;
      this.suscribir("portus/#");
      this._alConectar();
      return;
    }
    if (tipo === 0x30) {
      // PUBLISH entrante. Los eventos viajan con QoS 1 (§5.5): sin PUBACK el
      // broker deja de entregarlos al llenar su ventana de vuelo
      // (max_inflight_messages = 20) y solo sigue llegando el latido (QoS 0).
      const { topico, carga, qos, paqueteId } = this._parsearPublicar(bytes);
      if (qos === 1) {
        this._enviar(0x40, [(paqueteId >> 8) & 0xff, paqueteId & 0xff]); // PUBACK
      }
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
    // Bits 1-2 de la cabecera = QoS (los bits DUP y RETAIN no la alteran).
    const qos = (bytes[0] >> 1) & 0x03;
    let paqueteId = 0;
    if (qos > 0) {
      paqueteId = (bytes[i] << 8) | bytes[i + 1];
      i += 2;
    }
    const fin = 1 + leidos + longitudRestante;
    const carga = new TextDecoder().decode(bytes.slice(i, fin));
    return { topico, carga, qos, paqueteId };
  }

  _leerLongitudRestante(bytes, desde) {
    // Devuelve null si los bytes de la longitud aún no llegaron completos.
    let valor = 0;
    let multiplicador = 1;
    for (let k = 0; k < 4; k += 1) {
      if (desde + k >= bytes.length) {
        return null;
      }
      const b = bytes[desde + k];
      valor += (b & 0x7f) * multiplicador;
      if ((b & 0x80) === 0) {
        return { valor, leidos: k + 1 };
      }
      multiplicador *= 128;
    }
    return null;
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
