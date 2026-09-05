#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>
#include "HX711.h"

// ==================================================================
//  SEMAFOROS DE ESTADO (Garita y Pesaje)
// ==================================================================
//
//  Garita:  Rojo = no se permite el ingreso (default / rechazado)
//           Verde = ingreso permitido (talanquera abierta)
//           Azul  = instalaciones ocupadas (no se permite ingreso aunque
//                    el camion sea valido, porque ya hay un vehiculo
//                    usando la garita/talanquera)
//
//  NOTA: solo se indicaron los pines de rojo (14) y verde (15) para la
//  garita. Se asume el pin 16 para el azul, siguiendo la secuencia
//  antes de los pines de pesaje (17,18,19). Confirmar/ajustar si el
//  pin real es otro.
#define PIN_GARITA_ROJO   14
#define PIN_GARITA_VERDE  15
#define PIN_GARITA_AZUL   16  // TODO: confirmar numero de pin real

enum ColorSemaforo { SEM_ROJO, SEM_VERDE, SEM_AZUL, SEM_APAGADO };

void setSemaforoGarita(ColorSemaforo color) {
  digitalWrite(PIN_GARITA_ROJO,  color == SEM_ROJO);
  digitalWrite(PIN_GARITA_VERDE, color == SEM_VERDE);
  digitalWrite(PIN_GARITA_AZUL,  color == SEM_AZUL);
}

//  Pesaje:  Rojo = peso invalido / rechazado
//           Verde = peso valido / aceptado
//           Azul  = en espera (estabilizando, tarando, o sin lectura aun)
#define PIN_PESAJE_ROJO   17
#define PIN_PESAJE_VERDE  18
#define PIN_PESAJE_AZUL   19

void setSemaforoPesaje(ColorSemaforo color) {
  digitalWrite(PIN_PESAJE_ROJO,  color == SEM_ROJO);
  digitalWrite(PIN_PESAJE_VERDE, color == SEM_VERDE);
  digitalWrite(PIN_PESAJE_AZUL,  color == SEM_AZUL);
}

// ==================================================================
//  ESTACION 1: GARITA (RFID + Talanquera + Proximidad)
// ==================================================================

//  RC522 
#define SS_PIN 53
#define RST_PIN 49
MFRC522 mfrc522(SS_PIN, RST_PIN);

//  Servo (talanquera) 
Servo servoGarita;
#define SERVO_PIN 8
#define ESTADO_ABIERTO 0
#define ESTADO_CERRADO 80

//  HC-SR04 
#define TRIG_PIN 11
#define ECHO_PIN 12
unsigned long ultimaLecturaHC = 0;
const unsigned long INTERVALO_HC = 200;

//  Estado del sistema
bool talanqueraAbierta = false;
bool camionDetectadoEnfrente = false;
unsigned long tiempoApertura = 0;
const unsigned long TIEMPO_MAXIMO_ABIERTO = 4000;

const float UMBRAL_CERCA = 5.0;
const float UMBRAL_LEJOS = 7.0;
const int LECTURAS_NECESARIAS = 3;
int contador = 0;

float leerDistancia() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duracion = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duracion == 0) return -1;
  return duracion * 0.034 / 2;
}

void actualizarGarita() {
  if (!talanqueraAbierta && mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    String uid = "";
    for (byte i = 0; i < mfrc522.uid.size; i++) {
      if (mfrc522.uid.uidByte[i] < 0x10) uid += "0";
      uid += String(mfrc522.uid.uidByte[i], HEX);
    }
    uid.toLowerCase();

    bool esValido = (uid == "0437ec98c92a81" || uid == "043cec98c92a81" || uid == "043dec98c92a81");

    Serial.print("UID leido: ");
    Serial.println(uid);

    if (esValido) {
      Serial.println("-> Camion valido. Abriendo talanquera.");
      servoGarita.write(ESTADO_ABIERTO);
      talanqueraAbierta = true;
      camionDetectadoEnfrente = false;
      tiempoApertura = millis();
      contador = 0;
      setSemaforoGarita(SEM_VERDE);
    } else {
      Serial.println("-> ERROR: codigo invalido, camion no autorizado.");
      setSemaforoGarita(SEM_ROJO);
    }

    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
  }

  // Si la talanquera ya esta abierta/en uso y se detecta otro camion
  // intentando ingresar, se le indica con azul que las instalaciones
  // estan ocupadas (no se procesa su tarjeta todavia).
  else if (talanqueraAbierta && mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    Serial.println("-> Instalaciones ocupadas. No se permite el ingreso todavia.");
    setSemaforoGarita(SEM_AZUL);
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
  }

  if (talanqueraAbierta) {
    if (millis() - tiempoApertura >= TIEMPO_MAXIMO_ABIERTO) {
      servoGarita.write(ESTADO_CERRADO);
      talanqueraAbierta = false;
      camionDetectadoEnfrente = false;
      contador = 0;
      setSemaforoGarita(SEM_ROJO);
      Serial.println("-> Tiempo maximo alcanzado. Cerrando talanquera.");
    }
    else if (millis() - ultimaLecturaHC >= INTERVALO_HC) {
      ultimaLecturaHC = millis();

      float distancia = leerDistancia();
      if (distancia > 0) {
        Serial.print("Distancia: ");
        Serial.print(distancia);
        Serial.println(" cm");

        if (!camionDetectadoEnfrente) {
          if (distancia <= UMBRAL_CERCA) {
            contador++;
            Serial.print("-> Camion enfrente, confirmacion ");
            Serial.print(contador);
            Serial.print("/");
            Serial.println(LECTURAS_NECESARIAS);
            if (contador >= LECTURAS_NECESARIAS) {
              camionDetectadoEnfrente = true;
              contador = 0;
              Serial.println("-> Camion confirmado enfrente. Esperando que se aleje...");
            }
          } else {
            contador = 0;
          }
        } else {
          if (distancia >= UMBRAL_LEJOS) {
            contador++;
            Serial.print("-> Camion alejado, confirmacion ");
            Serial.print(contador);
            Serial.print("/");
            Serial.println(LECTURAS_NECESARIAS);
            if (contador >= LECTURAS_NECESARIAS) {
              Serial.println("-> Confirmado. Cerrando talanquera.");
              servoGarita.write(ESTADO_CERRADO);
              talanqueraAbierta = false;
              camionDetectadoEnfrente = false;
              contador = 0;
              setSemaforoGarita(SEM_ROJO);
            }
          } else {
            contador = 0;
          }
        }
      }
    }
  }
}

// ==================================================================
//  ESTACION 2: PESAJE (Sensor A + Sensor B dinamico, Sensor C estatico)
// ==================================================================
//
//  Sensor A y Sensor B COMPARTEN el pin de reloj (pin 2), tal como
//  ya esta el hardware -> se leen con una funcion manual que pulsa
//  el reloj UNA sola vez y lee ambos DOUT en el mismo pulso (misma
//  foto de instante para A y B).
//  Sensor C tiene sus propios pines (5 y 6) -> usa la libreria
//  nativa HX711.h normalmente, sin conflicto.
//
//  Requiere la libreria "HX711" (bogde) SOLO para el Sensor C.
//  A y B no la usan.

// ---------- Pines ----------
// Base 1 - Pesaje dinamico (A y B comparten reloj, como ya esta cableado)
#define PIN_SCK_AB   2
#define PIN_DT_A     3
#define PIN_DT_B     4

// Base 2 - Pesaje estatico (pines propios, sin conflicto)
#define PIN_SCK_C    5
#define PIN_DT_C     6

HX711 sensorC;

// ---------- Calibracion (AJUSTAR con la protoboard de 70g) ----------
float FACTOR_A = 812.0;   // validado con el metodo de suma constante
float FACTOR_B = 812.0;   // validado con el metodo de suma constante
float FACTOR_C = 2280.0;  // pendiente de calibrar

long offsetA = 0;
long offsetB = 0;

// TODO: reemplazar por la comparacion real contra el peso declarado en el
// manifiesto (con su tolerancia), como pide el enunciado de PORTUS.
// Mientras tanto, solo se considera valida una lectura entre 10g y 40g.
const float PESO_MINIMO_VALIDO = 10.0;
const float PESO_MAXIMO_VALIDO = 40.0;

// ---------- Lectura manual sincronizada de A y B ----------
// Pulsa el reloj compartido UNA vez y lee ambos DOUT en cada pulso,
// asi ambas conversiones corresponden exactamente al mismo instante.
bool leerParSincronizado(long &valorA, long &valorB) {
  if (digitalRead(PIN_DT_A) == HIGH || digitalRead(PIN_DT_B) == HIGH) {
    return false; // alguno de los dos todavia no tiene dato nuevo
  }

  valorA = 0;
  valorB = 0;
  for (uint8_t i = 0; i < 24; i++) {
    digitalWrite(PIN_SCK_AB, HIGH);
    delayMicroseconds(1);
    valorA = (valorA << 1) | digitalRead(PIN_DT_A);
    valorB = (valorB << 1) | digitalRead(PIN_DT_B);
    digitalWrite(PIN_SCK_AB, LOW);
    delayMicroseconds(1);
  }
  // 25er pulso: fija ganancia 128 / canal A para el siguiente ciclo
  digitalWrite(PIN_SCK_AB, HIGH);
  delayMicroseconds(1);
  digitalWrite(PIN_SCK_AB, LOW);

  if (valorA & 0x800000) valorA |= 0xFF000000;
  if (valorB & 0x800000) valorB |= 0xFF000000;
  return true;
}

// ---------- Maquina de estados no bloqueante (estabilizacion + tara) ----------
// Nada de delay() ni de while() de espera: cada estado se revisa una vez
// por vuelta de loop() y avanza solo cuando su condicion de tiempo o de
// muestreo se cumple, comparando contra millis(). Mientras tanto, Garita
// y Grua siguen atendiendose con normalidad.
enum EstadoPesaje {
  PESAJE_ESTABILIZANDO,     // esperando 15s a que HX711 y celdas se asienten
  PESAJE_TARA_ESPERA,       // pausa corta antes de empezar a muestrear la tara
  PESAJE_TARA_MUESTREANDO,  // acumulando N_TARA muestras de A y B
  PESAJE_LISTO              // operando: reporta A, B y C en cada lectura nueva
};

EstadoPesaje estadoPesaje = PESAJE_ESTABILIZANDO;
unsigned long tReferenciaPesaje = 0;

const unsigned long TIEMPO_ESTABILIZACION = 15000; // ms, igual que el delay original
const unsigned long TIEMPO_ESPERA_TARA    = 500;    // ms, igual que el delay original

const uint8_t N_TARA = 30;
uint8_t muestrasTaraObtenidas = 0;
long sumaTaraA = 0;
long sumaTaraB = 0;

// Inicializacion del modulo de pesaje: se llama una vez desde setup().
// Solo configura pines y arranca el cronometro de estabilizacion; el
// resto del proceso (tara, sensor C) ocurre despues, dentro de
// actualizarPesaje(), sin bloquear el arranque del resto del sistema.
void iniciarPesaje() {
  pinMode(PIN_SCK_AB, OUTPUT);
  pinMode(PIN_DT_A, INPUT);
  pinMode(PIN_DT_B, INPUT);
  digitalWrite(PIN_SCK_AB, LOW);

  sensorC.begin(PIN_DT_C, PIN_SCK_C);
  sensorC.set_scale(FACTOR_C);
  Serial.print(F("Sensor C listo? "));
  Serial.println(sensorC.is_ready() ? F("SI") : F("NO - revisar cableado C"));

  Serial.println(F("=== Estacion de pesaje: A+B manual, C con libreria ==="));
  Serial.println(F("Estabilizando HX711 y celdas (15s, sin bloquear el resto del sistema)..."));

  setSemaforoPesaje(SEM_AZUL); // en espera mientras estabiliza y tara

  tReferenciaPesaje = millis();
  estadoPesaje = PESAJE_ESTABILIZANDO;
}

// Reporta A, B (promedio movil) y C. Se llama solo cuando el pesaje
// ya esta tarado y operativo (estado PESAJE_LISTO).
void leerYReportarPesaje() {
  long crudoA, crudoB;
  if (leerParSincronizado(crudoA, crudoB)) {

    // Promedio movil simple de las ultimas N lecturas, para amortiguar
    // el ruido cuando se pesan objetos livianos (unos pocos gramos).
    static const uint8_t N = 8;
    static float histA[N] = {0};
    static float histB[N] = {0};
    static uint8_t idx = 0;
    static uint8_t llenado = 0;

    float pesoA = (crudoA - offsetA) / FACTOR_A;
    float pesoB = (crudoB - offsetB) / FACTOR_B;

    histA[idx] = pesoA;
    histB[idx] = pesoB;
    idx = (idx + 1) % N;
    if (llenado < N) llenado++;

    float promA = 0, promB = 0;
    for (uint8_t i = 0; i < llenado; i++) {
      promA += histA[i];
      promB += histB[i];
    }
    promA /= llenado;
    promB /= llenado;

    Serial.print(F("A="));
    Serial.print(promA, 1);
    Serial.print(F(" g   B="));
    Serial.print(promB, 1);
    Serial.print(F(" g   A+B="));
    Serial.print(promA + promB, 1);
    Serial.print(F(" g"));

    Serial.print(F("   C="));
    if (sensorC.is_ready()) {
      Serial.print(sensorC.get_units(1), 1);
      Serial.println(F(" g"));
    } else {
      Serial.println(F("NO_LISTO"));
    }

    // Semaforo de pesaje: verde si el peso esta dentro del rango
    // valido, rojo si esta fuera (rechazado por peso).
    float pesoTotal = promA + promB;
    if (pesoTotal >= PESO_MINIMO_VALIDO && pesoTotal <= PESO_MAXIMO_VALIDO) {
      setSemaforoPesaje(SEM_VERDE);
    } else {
      setSemaforoPesaje(SEM_ROJO);
    }
  }
}

// Se llama en cada vuelta de loop(). Avanza la maquina de estados del
// pesaje sin detener nunca el ciclo principal.
void actualizarPesaje() {
  unsigned long ahora = millis();

  switch (estadoPesaje) {

    case PESAJE_ESTABILIZANDO:
      if (ahora - tReferenciaPesaje >= TIEMPO_ESTABILIZACION) {
        tReferenciaPesaje = ahora;
        estadoPesaje = PESAJE_TARA_ESPERA;
      }
      break;

    case PESAJE_TARA_ESPERA:
      if (ahora - tReferenciaPesaje >= TIEMPO_ESPERA_TARA) {
        Serial.println(F("Tarando A y B... no toques la plataforma"));
        sumaTaraA = 0;
        sumaTaraB = 0;
        muestrasTaraObtenidas = 0;
        estadoPesaje = PESAJE_TARA_MUESTREANDO;
      }
      break;

    case PESAJE_TARA_MUESTREANDO: {
      long a, b;
      if (leerParSincronizado(a, b)) {
        sumaTaraA += a;
        sumaTaraB += b;
        muestrasTaraObtenidas++;

        if (muestrasTaraObtenidas >= N_TARA) {
          offsetA = sumaTaraA / N_TARA;
          offsetB = sumaTaraB / N_TARA;
          Serial.print(F("offsetA=")); Serial.print(offsetA);
          Serial.print(F("  offsetB=")); Serial.println(offsetB);

          // sensorC.tare() bloquea brevemente por diseno de la libreria
          // HX711 (bogde): espera a que DOUT este listo. En este punto
          // el sensor ya lleva 15s+ energizado, asi que la espera real
          // es de milisegundos, no un delay() nuestro.
          if (sensorC.is_ready()) {
            sensorC.tare(5);
          }

          Serial.println(F("Pesaje listo."));
          Serial.println(F("(Envia 't' por el Monitor Serie para volver a tarar A/B en cualquier momento, sin peso encima)"));
          Serial.println();

          estadoPesaje = PESAJE_LISTO;
        }
      }
      break;
    }

    case PESAJE_LISTO:
      leerYReportarPesaje();
      break;
  }
}

// Revisa el puerto serie SOLO por el comando de re-tara ('t'/'T').
// Usa peek() en vez de read() para no "robarse" bytes que le
// correspondan a los comandos de la grua ('a'-'h'), que se leen
// mas abajo en actualizarComandosGrua().
// Re-tarar ya no llama a una funcion bloqueante: solo reinicia el
// cronometro y regresa la maquina de estados a PESAJE_TARA_ESPERA.
void revisarComandoPesaje() {
  if (Serial.available()) {
    char c = Serial.peek();
    if (c == 't' || c == 'T') {
      Serial.read(); // ahora si se consume, era para nosotros
      Serial.println(F("Re-tara de A/B solicitada..."));
      setSemaforoPesaje(SEM_AZUL); // en espera mientras vuelve a tarar
      tReferenciaPesaje = millis();
      estadoPesaje = PESAJE_TARA_ESPERA;
    }
  }
}

// ==================================================================
//  ESTACION 3: GRUA (servo traslacion + izaje + iman)
// ==================================================================

Servo servoGrua;

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

void iniciarMovimientoVertical(
  TipoMovimientoVertical tipo,
  unsigned long tiempoBajada,
  unsigned long tiempoSubida
);

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

void actualizarServoGrua() {
  if (!servoMoviendo) {
    return;
  }

  unsigned long ahora = millis();

  if (ahora - ultimoPasoServo >= intervaloServo) {
    ultimoPasoServo = ahora;

    posicionActual += direccionServo;
    servoGrua.write(posicionActual);

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

void actualizarComandosGrua() {
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
}

// ==================================================================
//  SETUP / LOOP GENERAL
// ==================================================================

void setup() {
  Serial.begin(9600);

  //  Semaforos 
  pinMode(PIN_GARITA_ROJO, OUTPUT);
  pinMode(PIN_GARITA_VERDE, OUTPUT);
  pinMode(PIN_GARITA_AZUL, OUTPUT);
  setSemaforoGarita(SEM_ROJO); // por defecto no se permite el ingreso

  pinMode(PIN_PESAJE_ROJO, OUTPUT);
  pinMode(PIN_PESAJE_VERDE, OUTPUT);
  pinMode(PIN_PESAJE_AZUL, OUTPUT);
  setSemaforoPesaje(SEM_AZUL); // por defecto en espera

  //  Garita 
  SPI.begin();
  mfrc522.PCD_Init();

  servoGarita.attach(SERVO_PIN);
  servoGarita.write(ESTADO_CERRADO);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  //  Pesaje 
  iniciarPesaje();

  //  Grua 
  pinMode(pinSubida, OUTPUT);
  pinMode(pinBajada, OUTPUT);
  pinMode(pinIman, OUTPUT);

  digitalWrite(pinSubida, LOW);
  digitalWrite(pinBajada, LOW);
  digitalWrite(pinIman, LOW);

  servoGrua.attach(pinServo);
  servoGrua.write(posicionH);
  posicionActual = posicionH;

  Serial.println("Sistema listo. Esperando camion...");
  Serial.println("Grua lista.");
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
  actualizarGarita();

  revisarComandoPesaje();
  actualizarPesaje();

  actualizarServoGrua();
  actualizarMovimientoVertical();
  actualizarComandosGrua();
}


