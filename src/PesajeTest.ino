/*
  PesajeTest.ino
  Sketch de prueba AISLADO para el módulo de Pesaje (PORTUS - Fase 1).

  Sirve para:
   - Verificar que las lecturas de Sensor A, B y C llegan correctamente.
   - Calibrar factores de escala y tara con un peso conocido.
   - Ver en el Monitor Serial cuándo se detecta la meseta y qué peso calcula.

  No depende de ningún otro módulo del equipo (garita, grúa, patio, etc.).
  Cuando ya esté calibrado y probado, este archivo NO se sube al main
  final -> ahí solo se usan Pesaje.h / Pesaje.cpp como se mostró antes.

  Requiere en la misma carpeta del sketch (o como librería local):
    Pesaje.h
    Pesaje.cpp
*/

#include "Pesaje.h"

// Modo de prueba
// 1 = solo ver lecturas crudas de A y B (para calibrar factor y tara)
// 2 = probar la detección de meseta / pesaje dinámico completo
// 3 = probar la lectura estática (Sensor C) bajo demanda
// 4 = DIAGNOSTICO: imprime valores crudos de A y B en cada lectura exitosa
//     (usa este modo primero si el peso siempre te da 0)
// 5 = CALIBRACION: imprime un PROMEDIO de las ultimas N lecturas crudas,
//     cada 1 segundo. Usa este modo para sacar el factor real:
//       1) Deja la plataforma VACIA, anota el promedio (base_vacio).
//       2) Pon el peso conocido, anota el nuevo promedio (base_cargado).
//       3) factor = (base_cargado - base_vacio) / peso_en_gramos
#define MODO_PRUEBA 5

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

#if MODO_PRUEBA == 5
  // Modo 5: calibración con promedio móvil (reduce el ruido para comparar)
  static long sumaA = 0, sumaB = 0;
  static uint16_t contador = 0;
  sumaA += Pesaje_debugCrudoA();
  sumaB += Pesaje_debugCrudoB();
  contador++;

  if (millis() - ultimoPrintMs >= 1000) {
    ultimoPrintMs = millis();
    if (contador > 0) {
      Serial.print(F("Promedio A = "));
      Serial.print(sumaA / (long)contador);
      Serial.print(F("   Promedio B = "));
      Serial.print(sumaB / (long)contador);
      Serial.print(F("   (n=")); Serial.print(contador); Serial.println(F(" muestras))"));
    }
    sumaA = 0;
    sumaB = 0;
    contador = 0;
  }
#endif

#if MODO_PRUEBA == 4
  // Modo 4: diagnóstico crudo. Imprime cada vez que Pesaje_actualizar()
  // logra una lectura sincronizada nueva de A y B (aunque no haya meseta).
  static long ultimoImpresoA = -999999;
  static long ultimoImpresoB = -999999;
  long crudoA = Pesaje_debugCrudoA();
  long crudoB = Pesaje_debugCrudoB();
  if (crudoA != ultimoImpresoA || crudoB != ultimoImpresoB) {
    ultimoImpresoA = crudoA;
    ultimoImpresoB = crudoB;
    Serial.print(F("crudoA=")); Serial.print(crudoA);
    Serial.print(F(" (offsetA=")); Serial.print(Pesaje_debugOffsetA()); Serial.print(F(")"));
    Serial.print(F("  |  crudoB=")); Serial.print(crudoB);
    Serial.print(F(" (offsetB=")); Serial.print(Pesaje_debugOffsetB()); Serial.println(F(")"));
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
