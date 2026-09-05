/*
  PesajeTest_Combinado.ino

  Sin necesidad de recablear nada:
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
float FACTOR_A = 812.0;   // validado con el metodo de suma constante (mas confiable que el ajuste puntual anterior)
float FACTOR_B = 812.0;  // validado con el metodo de suma constante
float FACTOR_C = 2280.0;  // pendiente de calibrar

long offsetA = 0;
long offsetB = 0;

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

// Espera bloqueante SOLO para la tara inicial (una sola vez, no afecta
// el resto del sistema porque se hace antes de operar).
// Promedia varias muestras para que el offset no dependa de una sola
// lectura ruidosa (eso era lo que causaba el drift que veiamos).
void tararAB() {
  const uint8_t N_TARA = 30;
  long sumaA = 0, sumaB = 0;
  long a, b;

  Serial.println(F("Tarando A y B... no toques la plataforma"));
  delay(500);

  uint8_t obtenidas = 0;
  while (obtenidas < N_TARA) {
    if (leerParSincronizado(a, b)) {
      sumaA += a;
      sumaB += b;
      obtenidas++;
    }
  }

  offsetA = sumaA / N_TARA;
  offsetB = sumaB / N_TARA;
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

  Serial.println(F("Esperando 15s a que el HX711 y las celdas se estabilicen..."));
  delay(15000);

  tararAB();

  sensorC.begin(PIN_DT_C, PIN_SCK_C);
  sensorC.set_scale(FACTOR_C);
  Serial.print(F("Sensor C listo? "));
  Serial.println(sensorC.is_ready() ? F("SI") : F("NO - revisar cableado C"));
  if (sensorC.is_ready()) {
    sensorC.tare(5);
  }

  Serial.println(F("Listo. Empezando lecturas..."));
  Serial.println(F("(Envia 't' por el Monitor Serie para volver a tarar en cualquier momento, sin peso encima)"));
  Serial.println();
}

void loop() {
  // Re-tara bajo demanda: manda 't' por el Monitor Serie para tarar
  // justo antes de medir, sin tener que resetear el Arduino.
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 't' || c == 'T') {
      tararAB();
    }
  }

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
  }
}
