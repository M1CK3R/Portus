/*
  PesajeTest2.ino

   - Sensor A y Sensor B COMPARTEN el pin de reloj (pin 2), tal como
     ya esta tu hardware -> se leen con una funcion manual que pulsa
     el reloj UNA sola vez y lee ambos DOUT en el mismo pulso (esto es
     lo que exige el documento: misma foto de instante para A y B).
   - Sensor C tiene sus propios pines (5 y 6) -> para el usamos la
     libreria nativa HX711.h normalmente, sin conflicto.

  Requiere tener instalada la libreria "HX711" (bogde) SOLO para el
  Sensor C. A y B no la usan.
*/

#include "HX711.h"

// Pines
// Base 1 - Pesaje dinamico (A y B comparten reloj, como ya esta cableado)
#define PIN_SCK_AB   2
#define PIN_DT_A     3
#define PIN_DT_B     4

// Base 2 - Pesaje estatico (pines propios, sin conflicto)
#define PIN_SCK_C    5
#define PIN_DT_C     6

HX711 sensorC;

// Calibracion
float FACTOR_A = 363.9;   // cambia el signo si el peso te sale negativo
float FACTOR_B = 354.5;   // cambia el signo si el peso te sale negativo
float FACTOR_C = 2280.0;  // pendiente de calibrar

long offsetA = 0;
long offsetB = 0;

// Lectura manual sincronizada de A y B
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

// Espera bloqueante SOLO para la tara inicial (una sola vez, no afecta
// el resto del sistema porque se hace antes de operar).
void tararAB() {
  long a, b;
  Serial.println(F("Tarando A y B... no toques la plataforma"));
  delay(1000);
  while (!leerParSincronizado(a, b)) { /* esperar */ }
  offsetA = a;
  offsetB = b;
  Serial.print(F("offsetA=")); Serial.print(offsetA);
  Serial.print(F("  offsetB=")); Serial.println(offsetB);
}

void setup() {
  Serial.begin(9600);
  while (!Serial) { ; }

  pinMode(PIN_SCK_AB, OUTPUT);
  pinMode(PIN_DT_A, INPUT);
  pinMode(PIN_DT_B, INPUT);
  digitalWrite(PIN_SCK_AB, LOW);

  Serial.println(F("=== Prueba combinada: A+B manual, C con libreria ==="));

  tararAB();

  sensorC.begin(PIN_DT_C, PIN_SCK_C);
  sensorC.set_scale(FACTOR_C);
  Serial.print(F("Sensor C listo? "));
  Serial.println(sensorC.is_ready() ? F("SI") : F("NO - revisar cableado C"));
  if (sensorC.is_ready()) {
    sensorC.tare(5);
  }

  Serial.println(F("Listo. Empezando lecturas..."));
  Serial.println();
}

void loop() {
  long crudoA, crudoB;
  if (leerParSincronizado(crudoA, crudoB)) {
    float pesoA = (crudoA - offsetA) / FACTOR_A;
    float pesoB = (crudoB - offsetB) / FACTOR_B;

    Serial.print(F("A="));
    Serial.print(pesoA, 1);
    Serial.print(F(" g   B="));
    Serial.print(pesoB, 1);
    Serial.print(F(" g   A+B="));
    Serial.print(pesoA + pesoB, 1);
    Serial.print(F(" g"));

    Serial.print(F("   C="));
    if (sensorC.is_ready()) {
      Serial.print(sensorC.get_units(1), 1);
      Serial.println(F(" g"));
    } else {
      Serial.println(F("NO_LISTO"));
    }
  }
}
