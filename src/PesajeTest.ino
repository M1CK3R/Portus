/*
  PesajeTest.ino

  Version de prueba usando la libreria NATIVA HX711.h (no el modulo
  custom de bit-banging). Sirve para confirmar que el hardware (celdas,
  cableado, alimentacion) responde bien, sin depender de nuestra logica
  de sincronizacion manual.

  Requiere instalar la libreria "HX711" (por ejemplo la de bogde,
  Sketch > Incluir Libreria > Administrar Bibliotecas > buscar "HX711").

  IMPORTANTE: esta version NO cumple el requisito del documento de leer
  A y B en el MISMO pulso de reloj (cada objeto HX711 lee por separado).
  Es solo para diagnostico / calibracion. Cuando confirmemos que el
  hardware funciona, volvemos al modulo Pesaje.h/.cpp para el pesaje
  dinamico real.
*/

#include "HX711.h"

// Base 1 - Pesaje dinamico
#define SCK_A 2
#define DT_A  3
#define SCK_B 2   // mismo pin fisico de reloj que A (aunque cada objeto lo maneje por su cuenta)
#define DT_B  4

// Base 2 - Pesaje estatico
#define SCK_C 5
#define DT_C  6

HX711 sensorA;
HX711 sensorB;
HX711 sensorC;

// Factores ya calculados con la protoboard de 70g (ajusta si vuelves a calibrar)
float FACTOR_A = 363.9;
float FACTOR_B = 354.5;
float FACTOR_C = 2280.0; // pendiente de calibrar

void setup() {
  Serial.begin(9600);
  while (!Serial) { ; }

  Serial.println(F("=== Prueba con libreria nativa HX711 ==="));

  sensorA.begin(DT_A, SCK_A);
  sensorB.begin(DT_B, SCK_B);
  sensorC.begin(DT_C, SCK_C);

  sensorA.set_scale(FACTOR_A);
  sensorB.set_scale(FACTOR_B);
  sensorC.set_scale(FACTOR_C);

  Serial.println(F("Verificando conexion de cada sensor..."));
  Serial.print(F("Sensor A listo? ")); Serial.println(sensorA.is_ready() ? F("SI") : F("NO - revisa cableado"));
  Serial.print(F("Sensor B listo? ")); Serial.println(sensorB.is_ready() ? F("SI") : F("NO - revisa cableado"));
  Serial.print(F("Sensor C listo? ")); Serial.println(sensorC.is_ready() ? F("SI") : F("NO - revisa cableado"));

  Serial.println(F("Deja la plataforma y la base VACIAS, tarando en 3 segundos..."));
  delay(3000);

  sensorA.tare(5);
  sensorB.tare(5);
  sensorC.tare(5);

  Serial.println(F("Tara lista. Empezando lecturas continuas..."));
  Serial.println();
}

void loop() {
  Serial.print(F("A="));
  if (sensorA.is_ready()) {
    Serial.print(sensorA.get_units(1), 1);
  } else {
    Serial.print(F("NO_LISTO"));
  }

  Serial.print(F(" g   B="));
  if (sensorB.is_ready()) {
    Serial.print(sensorB.get_units(1), 1);
  } else {
    Serial.print(F("NO_LISTO"));
  }

  Serial.print(F(" g   A+B="));
  if (sensorA.is_ready() && sensorB.is_ready()) {
    Serial.print(sensorA.get_units(1) + sensorB.get_units(1), 1);
  } else {
    Serial.print(F("--"));
  }

  Serial.print(F(" g   C="));
  if (sensorC.is_ready()) {
    Serial.print(sensorC.get_units(1), 1);
  } else {
    Serial.print(F("NO_LISTO"));
  }
  Serial.println(F(" g"));

  delay(300); // solo para que el Monitor Serial sea legible; no afecta al sensor
}
