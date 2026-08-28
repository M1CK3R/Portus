/*
  PesajeTest.ino
  Sketch de prueba AISLADO para el módulo de Pesaje

  Sirve para:
   - Verificar que las lecturas de Sensor A, B y C llegan correctamente.
   - Calibrar factores de escala y tara con un peso conocido.
   - Ver en el Monitor Serial cuándo se detecta la meseta y qué peso calcula.

  No depende de ningún otro módulo del equipo (garita, grúa, patio, etc.).
  Cuando ya esté calibrado y probado, este archivo NO se sube al main
  final -> ahí solo se usan Pesaje.h / Pesaje.cpp

  Requiere en la misma carpeta del sketch (o como librería local):
    Pesaje.h
    Pesaje.cpp
*/

#include "Pesaje.h"

// Modo de prueba
// 1 = solo ver lecturas crudas de A y B (para calibrar factor y tara)
// 2 = probar la detección de meseta / pesaje dinámico completo
// 3 = probar la lectura estática (Sensor C) bajo demanda
#define MODO_PRUEBA 2

// Factores de calibración iniciales (AJUSTAR con un peso conocido)
float FACTOR_A = 2280.0;
float FACTOR_B = 2280.0;
float FACTOR_C = 2280.0;

unsigned long ultimoPrintMs = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }

  Serial.println(F("=== PORTUS - Prueba de modulo de Pesaje ==="));

  Pesaje_init();
  Pesaje_setFactorCalibracion(FACTOR_A, FACTOR_B, FACTOR_C);

  Serial.println(F("Coloca la plataforma dinamica VACIA y no la toques..."));
  delay(2000);
  Pesaje_tararDinamico();
  Serial.println(F("Tara dinamica (A+B) lista."));

  Serial.println(F("Coloca la base estatica (C) VACIA y no la toques..."));
  delay(2000);
  Pesaje_tararEstatico();
  Serial.println(F("Tara estatica (C) lista."));

  Serial.println(F("Listo. Empezando pruebas..."));
  Serial.println();

#if MODO_PRUEBA == 3
  Pesaje_solicitarLecturaEstatica();
#endif
}

void loop() {
  Pesaje_actualizar();

#if MODO_PRUEBA == 2
  // Modo 2: pesaje dinámico completo
  if (Pesaje_hayResultadoDinamico()) {
    float peso = Pesaje_obtenerPesoDinamico();
    Serial.print(F(">> MESETA DETECTADA. Peso dinamico (A+B): "));
    Serial.print(peso, 1);
    Serial.println(F(" g"));

    Pesaje_resetDinamico();
    Serial.println(F("Listo para el siguiente vehiculo..."));
  }
#endif

#if MODO_PRUEBA == 3
  // Modo 3: pesaje estático puntual
  if (Pesaje_hayLecturaEstatica()) {
    float pesoC = Pesaje_obtenerPesoEstatico();
    Serial.print(F(">> Lectura estatica (C): "));
    Serial.print(pesoC, 1);
    Serial.println(F(" g"));

    delay(2000); // espera antes de pedir otra lectura
    Pesaje_solicitarLecturaEstatica();
  }
#endif

  // Reporte periódico simple (util en modo 1 para ver que los sensores respondan)
  if (millis() - ultimoPrintMs >= 500) {
    ultimoPrintMs = millis();
#if MODO_PRUEBA == 1
    Serial.print(F("Esperando ciclos del timer... (deberias ver el peso cambiar al poner algo encima)"));
    Serial.println();
#endif
  }
}
