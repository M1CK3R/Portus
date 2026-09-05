/*
  Pesaje.cpp

  Diseño:
  - Timer1 en modo CTC genera una interrupción periódica (por defecto
    cada 20 ms) que solo levanta una bandera ("tick"). Toda la lectura
    real de los HX711 ocurre en Pesaje_actualizar(), llamada desde
    loop() -> nunca se bloquea el resto del sistema dentro de una ISR.
  - La lectura de Sensor A y Sensor B se hace por manipulación directa
    de puertos, pulsando UNA sola vez el reloj compartido (pin 2) y
    leyendo ambos DOUT en cada pulso -> ambas conversiones corresponden
    exactamente al mismo instante, como pide la especificación.
  - Se acumulan muestras de peso total (A+B) mientras el valor se
    mantenga estable (delta pequeño entre muestras consecutivas) durante
    al menos MUESTRAS_MESETA_MIN muestras. Al terminar la meseta se
    calcula la mediana de esas muestras -> ese es el peso reportado.
  - Sensor C (estático) se lee con el mismo esquema de bit-banging pero
    en un solo canal, bajo demanda (Pesaje_solicitarLecturaEstatica()).
*/

#include "Pesaje.h"

// Configuración ajustable
static const uint16_t INTERVALO_MUESTREO_MS   = 20;   // periodo del timer
static const uint8_t  MUESTRAS_MESETA_MIN     = 20;   // ~0.4s a 20ms; súbelo si tu meseta real es de 1.4s
static const float    DELTA_ESTABLE_GRAMOS    = 300.0; // tolerancia entre muestras consecutivas para considerarlas "meseta"
static const uint8_t  MAX_MUESTRAS_BUFFER     = 80;    // suficiente para ~1.6s a 20ms

// Estado interno: dinámico (A+B)
static volatile bool  tickTimer = false;

static float factorCalA = 1.0, factorCalB = 1.0, factorCalC = 1.0;
static long  offsetA = 0, offsetB = 0, offsetC = 0;

static float bufferMuestras[MAX_MUESTRAS_BUFFER];
static uint8_t indiceBuffer = 0;
static uint8_t muestrasEstablesSeguidas = 0;
static float ultimaMuestraSuma = 0;
static bool  enMeseta = false;
static bool  resultadoListo = false;
static float pesoDinamicoFinal = 0;

static long  ultimoCrudoA = 0;
static long  ultimoCrudoB = 0;

// Estado interno: estático (C)
static bool  lecturaEstaticaPendiente = false;
static bool  lecturaEstaticaLista = false;
static float pesoEstaticoFinal = 0;

// Utilidades de bajo nivel HX711

// Lee 24 bits de UN canal HX711 (uso para el sensor estático).
// Bit-banging simple; no es time-critical porque el vehículo está detenido.
static long hx711_leerCanal(uint8_t pinDT, uint8_t pinSCK) {
  while (digitalRead(pinDT) == HIGH) {
    // esperar a que el HX711 tenga datos listos (DOUT baja)
    // (en un diseño más estricto esto se controlaría con timeout)
  }

  long valor = 0;
  for (uint8_t i = 0; i < 24; i++) {
    digitalWrite(pinSCK, HIGH);
    delayMicroseconds(1);
    valor = (valor << 1) | digitalRead(pinDT);
    digitalWrite(pinSCK, LOW);
    delayMicroseconds(1);
  }
  // 25° pulso: fija ganancia 128 para el próximo ciclo (canal A por defecto)
  digitalWrite(pinSCK, HIGH);
  delayMicroseconds(1);
  digitalWrite(pinSCK, LOW);

  // Extender el signo (complemento a 2 de 24 bits)
  if (valor & 0x800000) {
    valor |= 0xFF000000;
  }
  return valor;
}

// Lee A y B EN EL MISMO PULSO DE RELOJ (pin 2 compartido).
// Devuelve true si ambos sensores tenían datos listos y se leyeron.
static bool hx711_leerParSincronizado(long &valorA, long &valorB) {
  // Ambos DOUT deben estar en LOW (datos listos) antes de empezar
  if (digitalRead(PIN_DT_A) == HIGH || digitalRead(PIN_DT_B) == HIGH) {
    return false; // todavía no hay datos nuevos en alguno de los dos
  }

  valorA = 0;
  valorB = 0;
  for (uint8_t i = 0; i < 24; i++) {
    digitalWrite(PIN_SCK_DINAMICO, HIGH);
    delayMicroseconds(1);
    // Se leen ambos DOUT en el mismo flanco -> misma "foto" de instante
    valorA = (valorA << 1) | digitalRead(PIN_DT_A);
    valorB = (valorB << 1) | digitalRead(PIN_DT_B);
    digitalWrite(PIN_SCK_DINAMICO, LOW);
    delayMicroseconds(1);
  }
  // 25° pulso: ganancia 128, canal A, para ambos módulos
  digitalWrite(PIN_SCK_DINAMICO, HIGH);
  delayMicroseconds(1);
  digitalWrite(PIN_SCK_DINAMICO, LOW);

  if (valorA & 0x800000) valorA |= 0xFF000000;
  if (valorB & 0x800000) valorB |= 0xFF000000;
  return true;
}

// Timer1 (Mega) en modo CTC
// Genera una interrupción cada INTERVALO_MUESTREO_MS.
static void timer1_configurar(uint16_t intervaloMs) {
  noInterrupts();
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1  = 0;

  // Prescaler 256 -> 16MHz/256 = 62500 ticks/seg -> 1 tick = 16us
  uint32_t ticks = (uint32_t)intervaloMs * 1000UL / 16UL;
  OCR1A = (uint16_t)(ticks - 1);

  TCCR1B |= (1 << WGM12);              // modo CTC
  TCCR1B |= (1 << CS12);               // prescaler 256
  TIMSK1 |= (1 << OCIE1A);             // habilita interrupción por comparación
  interrupts();
}

ISR(TIMER1_COMPA_vect) {
  tickTimer = true; // la ISR solo señaliza; nada de lógica pesada aquí
}

// Mediana
static float calcularMediana(float *datos, uint8_t n) {
  // Ordenamiento simple (n es pequeño, ~20-80 muestras: suficiente)
  for (uint8_t i = 0; i < n - 1; i++) {
    for (uint8_t j = 0; j < n - i - 1; j++) {
      if (datos[j] > datos[j + 1]) {
        float tmp = datos[j];
        datos[j] = datos[j + 1];
        datos[j + 1] = tmp;
      }
    }
  }
  if (n % 2 == 1) {
    return datos[n / 2];
  } else {
    return (datos[n / 2 - 1] + datos[n / 2]) / 2.0;
  }
}

// API pública

void Pesaje_init() {
  pinMode(PIN_SCK_DINAMICO, OUTPUT);
  pinMode(PIN_DT_A, INPUT);
  pinMode(PIN_DT_B, INPUT);
  digitalWrite(PIN_SCK_DINAMICO, LOW);

  pinMode(PIN_SCK_ESTATICO, OUTPUT);
  pinMode(PIN_DT_C, INPUT);
  digitalWrite(PIN_SCK_ESTATICO, LOW);

  indiceBuffer = 0;
  muestrasEstablesSeguidas = 0;
  enMeseta = false;
  resultadoListo = false;

  timer1_configurar(INTERVALO_MUESTREO_MS);
}

void Pesaje_setFactorCalibracion(float factorA, float factorB, float factorC) {
  factorCalA = factorA;
  factorCalB = factorB;
  factorCalC = factorC;
}

void Pesaje_tararDinamico() {
  long a, b;
  // Se descartan lecturas hasta obtener un par válido
  while (!hx711_leerParSincronizado(a, b)) { /* esperar */ }
  offsetA = a;
  offsetB = b;
}

void Pesaje_tararEstatico() {
  offsetC = hx711_leerCanal(PIN_DT_C, PIN_SCK_ESTATICO);
}

void Pesaje_actualizar() {
  if (!tickTimer) return;
  tickTimer = false;

  long crudoA, crudoB;
  if (!hx711_leerParSincronizado(crudoA, crudoB)) {
    return; // todavía no había datos nuevos en este ciclo
  }

  // Los valores crudos SIEMPRE se actualizan, aunque haya un resultado
  // dinámico pendiente de ser leído por el main. Esto es lo que antes
  // se congelaba y obligaba a resetear el Arduino para ver cambios.
  ultimoCrudoA = crudoA;
  ultimoCrudoB = crudoB;

  // La acumulación para detectar la meseta SÍ se pausa mientras el main
  // no confirme que ya leyó el resultado anterior (Pesaje_resetDinamico()).
  if (resultadoListo) {
    // no seguimos acumulando muestras nuevas para la meseta,
    // pero el bloque de abajo (estático) igual puede ejecutarse
  } else {
    float pesoA = (crudoA - offsetA) / factorCalA;
    float pesoB = (crudoB - offsetB) / factorCalB;
    float sumaActual = pesoA + pesoB;

    if (indiceBuffer == 0) {
      // primera muestra del posible nuevo vehículo
      ultimaMuestraSuma = sumaActual;
      muestrasEstablesSeguidas = 1;
    } else {
      float delta = abs(sumaActual - ultimaMuestraSuma);
      if (delta <= DELTA_ESTABLE_GRAMOS) {
        muestrasEstablesSeguidas++;
      } else {
        // el peso cambió bruscamente (vehículo entrando o saliendo de la
        // plataforma) -> reiniciamos la ventana de estabilidad
        muestrasEstablesSeguidas = 1;
        indiceBuffer = 0;
      }
      ultimaMuestraSuma = sumaActual;
    }

    if (indiceBuffer < MAX_MUESTRAS_BUFFER) {
      bufferMuestras[indiceBuffer++] = sumaActual;
    }

    if (muestrasEstablesSeguidas >= MUESTRAS_MESETA_MIN && !resultadoListo) {
      // Tomamos las últimas MUESTRAS_MESETA_MIN muestras (la meseta real)
      uint8_t inicio = indiceBuffer - MUESTRAS_MESETA_MIN;
      pesoDinamicoFinal = calcularMediana(&bufferMuestras[inicio], MUESTRAS_MESETA_MIN);
      resultadoListo = true;
    }
  } // cierra el "else" de (!resultadoListo)

  // Lectura estática solicitada, se atiende cuando toque este mismo tick
  if (lecturaEstaticaPendiente) {
    long crudoC = hx711_leerCanal(PIN_DT_C, PIN_SCK_ESTATICO);
    pesoEstaticoFinal = (crudoC - offsetC) / factorCalC;
    lecturaEstaticaPendiente = false;
    lecturaEstaticaLista = true;
  }
}

bool Pesaje_hayResultadoDinamico() {
  return resultadoListo;
}

float Pesaje_obtenerPesoDinamico() {
  return pesoDinamicoFinal;
}

void Pesaje_resetDinamico() {
  indiceBuffer = 0;
  muestrasEstablesSeguidas = 0;
  enMeseta = false;
  resultadoListo = false;
}

void Pesaje_solicitarLecturaEstatica() {
  lecturaEstaticaLista = false;
  lecturaEstaticaPendiente = true;
}

bool Pesaje_hayLecturaEstatica() {
  return lecturaEstaticaLista;
}

float Pesaje_obtenerPesoEstatico() {
  return pesoEstaticoFinal;
}

long Pesaje_debugCrudoA() { return ultimoCrudoA; }
long Pesaje_debugCrudoB() { return ultimoCrudoB; }
long Pesaje_debugOffsetA() { return offsetA; }
long Pesaje_debugOffsetB() { return offsetB; }