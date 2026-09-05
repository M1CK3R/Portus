#include <Servo.h>

Servo miServo;

const int pinServo = 9;
const int pinSubida = 22;
const int pinBajada = 23;
const int pinIman = 24;

const int posicion1 = 10;
const int posicion2 = 60;
const int posicion3 = 120;
const int posicionH = 180;

int posicionActual = 180;
int posicionDestino = 180;

bool estadoIman = false;
bool servoMoviendo = false;
bool sistemaOcupado = false;
bool movimientoHome = false;
bool accionRecoger = false;

int direccionServo = 0;

unsigned long ultimoPasoServo = 0;
unsigned long intervaloServo = 0;

unsigned long tiempoInicioVertical = 0;
unsigned long tiempoBajadaActual = 0;
unsigned long tiempoSubidaActual = 0;

enum EstadoVertical {
  VERTICAL_LIBRE,
  VERTICAL_BAJANDO,
  VERTICAL_ESPERANDO,
  VERTICAL_SUBIENDO
};

EstadoVertical estadoVertical = VERTICAL_LIBRE;

enum TipoMovimientoVertical {
  MOVIMIENTO_NINGUNO,
  MOVIMIENTO_D_HOME,
  MOVIMIENTO_D_PUNTO,
  MOVIMIENTO_R,
  MOVIMIENTO_E
};

TipoMovimientoVertical tipoMovimientoVertical = MOVIMIENTO_NINGUNO;

void iniciarMoverSuave(int destino, unsigned long tiempo) {
  int pasos = abs(destino - posicionActual);

  if (pasos == 0) {
    servoMoviendo = false;
    sistemaOcupado = false;

    if (movimientoHome) {
      Serial.println("Llego a home!");
      movimientoHome = false;
    }

    return;
  }

  posicionDestino = destino;
  intervaloServo = tiempo / pasos;

  if (intervaloServo == 0) {
    intervaloServo = 1;
  }

  if (posicionActual < posicionDestino) {
    direccionServo = 1;
  } else {
    direccionServo = -1;
  }

  servoMoviendo = true;
  sistemaOcupado = true;
  ultimoPasoServo = millis();
}

void actualizarServo() {
  if (!servoMoviendo) {
    return;
  }

  unsigned long ahora = millis();

  if (ahora - ultimoPasoServo >= intervaloServo) {
    ultimoPasoServo = ahora;

    posicionActual += direccionServo;
    miServo.write(posicionActual);

    if (posicionActual == posicionDestino) {
      servoMoviendo = false;
      sistemaOcupado = false;

      if (movimientoHome) {
        Serial.println("Llego a home!");
        movimientoHome = false;
      }
    }
  }
}

void iniciarMovimientoVertical(
  TipoMovimientoVertical tipo,
  unsigned long tiempoBajada,
  unsigned long tiempoSubida
) {
  if (sistemaOcupado) {
    return;
  }

  tipoMovimientoVertical = tipo;
  tiempoBajadaActual = tiempoBajada;
  tiempoSubidaActual = tiempoSubida;

  digitalWrite(pinSubida, LOW);
  digitalWrite(pinBajada, HIGH);

  tiempoInicioVertical = millis();
  estadoVertical = VERTICAL_BAJANDO;
  sistemaOcupado = true;
}

void actualizarMovimientoVertical() {
  unsigned long ahora = millis();

  if (estadoVertical == VERTICAL_BAJANDO) {
    if (ahora - tiempoInicioVertical >= tiempoBajadaActual) {
      digitalWrite(pinBajada, LOW);

      if (
        tipoMovimientoVertical == MOVIMIENTO_D_HOME ||
        tipoMovimientoVertical == MOVIMIENTO_D_PUNTO
      ) {
        if (accionRecoger) {
          digitalWrite(pinIman, HIGH);
          estadoIman = true;

          Serial.println("Iman encendido");
          Serial.println("Carga recogida");
        } else {
          digitalWrite(pinIman, LOW);
          estadoIman = false;

          Serial.println("Iman apagado");
          Serial.println("Carga entregada");
        }
      }

      else if (tipoMovimientoVertical == MOVIMIENTO_R) {
        digitalWrite(pinIman, HIGH);
        estadoIman = true;

        Serial.println("Iman encendido");
        Serial.println("Carga recogida");
      }

      else if (tipoMovimientoVertical == MOVIMIENTO_E) {
        digitalWrite(pinIman, LOW);
        estadoIman = false;

        Serial.println("Iman apagado");
        Serial.println("Carga entregada");
      }

      tiempoInicioVertical = ahora;
      estadoVertical = VERTICAL_ESPERANDO;
    }
  }

  else if (estadoVertical == VERTICAL_ESPERANDO) {
    if (ahora - tiempoInicioVertical >= 800) {
      digitalWrite(pinSubida, HIGH);

      tiempoInicioVertical = ahora;
      estadoVertical = VERTICAL_SUBIENDO;
    }
  }

  else if (estadoVertical == VERTICAL_SUBIENDO) {
    if (ahora - tiempoInicioVertical >= tiempoSubidaActual) {
      digitalWrite(pinSubida, LOW);

      estadoVertical = VERTICAL_LIBRE;
      tipoMovimientoVertical = MOVIMIENTO_NINGUNO;
      sistemaOcupado = false;

      if (estadoIman) {
        Serial.println("Movimiento terminado con carga");
      } else {
        Serial.println("Movimiento terminado sin carga");
      }
    }
  }
}

void setup() {
  Serial.begin(9600);

  pinMode(pinSubida, OUTPUT);
  pinMode(pinBajada, OUTPUT);
  pinMode(pinIman, OUTPUT);

  digitalWrite(pinSubida, LOW);
  digitalWrite(pinBajada, LOW);
  digitalWrite(pinIman, LOW);

  miServo.attach(pinServo);
  miServo.write(posicionH);

  posicionActual = posicionH;

  Serial.println("Servo listo.");
  Serial.println("a = Punto 1");
  Serial.println("b = Punto 2");
  Serial.println("c = Punto 3");
  Serial.println("d = Cargar o descargar");
  Serial.println("i = Activar/Desactivar iman");
  Serial.println("h = Ir a posicion home");
  Serial.println("r = Recoger");
  Serial.println("e = Entregar en camion");
}

void loop() {
  actualizarServo();
  actualizarMovimientoVertical();

  if (Serial.available() > 0) {
    char comando = Serial.read();

    if (comando == '\n' || comando == '\r') {
      return;
    }

    if (sistemaOcupado) {
      return;
    }

    if (comando == 'a') {
      Serial.println("Moviendo a Punto 1");
      iniciarMoverSuave(posicion1, 5000);
    }

    else if (comando == 'b') {
      Serial.println("Moviendo a Punto 2");
      iniciarMoverSuave(posicion2, 4000);
    }

    else if (comando == 'c') {
      Serial.println("Moviendo a Punto 3");
      iniciarMoverSuave(posicion3, 3000);
    }

    else if (comando == 'd') {
      if (!estadoIman) {
        accionRecoger = true;
      } else {
        accionRecoger = false;
      }

      if (posicionActual == posicionH) {
        if (accionRecoger) {
          Serial.println("Bajando en HOME para recoger carga");
        } else {
          Serial.println("Bajando en HOME para dejar carga en camion");
        }

        iniciarMovimientoVertical(
          MOVIMIENTO_D_HOME,
          3400,
          3550
        );
      } else {
        if (accionRecoger) {
          Serial.println("Bajando en punto para recoger carga");
        } else {
          Serial.println("Bajando en punto para dejar carga");
        }

        iniciarMovimientoVertical(
          MOVIMIENTO_D_PUNTO,
          3600,
          3600
        );
      }
    }

    else if (comando == 'i') {
      if (estadoIman == false) {
        Serial.println("Encendiendo el iman");

        digitalWrite(pinIman, HIGH);
        estadoIman = true;
      } else {
        Serial.println("Apagando el iman");

        digitalWrite(pinIman, LOW);
        estadoIman = false;
      }
    }

    else if (comando == 'r') {
      Serial.println("Bajando, recogiendo carga y subiendo");

      iniciarMovimientoVertical(
        MOVIMIENTO_R,
        3600,
        3600
      );
    }

    else if (comando == 'h') {
      Serial.println("Moviendo a HOME");

      movimientoHome = true;

      switch (posicionActual) {
        case posicion1:
          iniciarMoverSuave(posicionH, 5000);
          break;

        case posicion2:
          iniciarMoverSuave(posicionH, 4000);
          break;

        case posicion3:
          iniciarMoverSuave(posicionH, 3000);
          break;

        default:
          Serial.println("Llego a home!");
          movimientoHome = false;
          break;
      }
    }

    else if (comando == 'e') {
      Serial.println("Bajando, dejando carga en camion y subiendo");

      iniciarMovimientoVertical(
        MOVIMIENTO_E,
        3400,
        3500
      );
    }
  }
}`