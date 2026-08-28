/*
  Pesaje.h
  Módulo de pesaje dinámico (Base 1: Sensor A + Sensor B) y
  pesaje estático (Base 2: Sensor C)

  Uso desde main.ino:

    #include "Pesaje.h"

    void setup() {
      Pesaje_init();
    }

    void loop() {
      Pesaje_actualizar();

      if (Pesaje_hayResultadoDinamico()) {
        float peso = Pesaje_obtenerPesoDinamico();
        // ... el main decide qué hacer con el peso (comparar
        // contra el manifiesto, mover la aguja desviadora, etc.)
        Pesaje_resetDinamico(); // listo para el siguiente vehículo
      }
    }
*/

#ifndef PESAJE_H
#define PESAJE_H

#include <Arduino.h>

// Pines (Arduino Mega)
// Base 1 - Pesaje dinámico (Sensor A + Sensor B)
#define PIN_SCK_DINAMICO   2   // compartido entre A y B
#define PIN_DT_A           3
#define PIN_DT_B           4

// Base 2 - Pesaje estático (Sensor C)
#define PIN_SCK_ESTATICO   5
#define PIN_DT_C           6

// API del módulo

// Configura pines, timer y variables internas. Llamar una vez en setup().
void Pesaje_init();

// Debe llamarse en cada iteración de loop(). No bloqueante.
// Internamente decide, según el temporizador, si toca tomar una
// nueva muestra de A+B y actualizar el estado de la meseta.
void Pesaje_actualizar();

// Pesaje dinámico (A + B)

// true cuando ya se detectó una meseta estable y se calculó el peso.
bool Pesaje_hayResultadoDinamico();

// Peso total del vehículo (mediana de las muestras de la meseta), en gramos.
// Solo válido si Pesaje_hayResultadoDinamico() es true.
float Pesaje_obtenerPesoDinamico();

// Limpia el resultado y reinicia la detección de meseta para el próximo vehículo.
void Pesaje_resetDinamico();

// Pesaje estático (C)

// Pide una lectura puntual de la celda estática (no requiere meseta,
// asume vehículo detenido). El resultado queda disponible unos ciclos después.
void Pesaje_solicitarLecturaEstatica();

// true cuando la lectura estática solicitada ya está lista.
bool Pesaje_hayLecturaEstatica();

// Último peso estático calculado, en gramos.
float Pesaje_obtenerPesoEstatico();

// Calibración
// Ajusta el factor de escala (cuentas HX711 -> gramos) de cada celda.
// Deben calibrarse físicamente con un peso conocido antes de usar el sistema.
void Pesaje_setFactorCalibracion(float factorA, float factorB, float factorC);

// Ajusta el offset (lectura con la plataforma vacía / tara del sensor).
void Pesaje_tararDinamico();
void Pesaje_tararEstatico();

#endif