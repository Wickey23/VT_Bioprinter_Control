/*
  VT Bioprinter - DFRduino command sender proof-of-concept

  Role:
    DFRduino UNO -> host bridge -> Creality V4.2.2 / Marlin

  This first version sends only a read-only M115 query after startup.
  No motion commands are sent.
*/

const unsigned long STARTUP_DELAY_MS = 3000;
bool sentStartupQuery = false;

void setup() {
  Serial.begin(9600);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
}

void loop() {
  if (!sentStartupQuery && millis() >= STARTUP_DELAY_MS) {
    Serial.println("PRINTER:M115");
    sentStartupQuery = true;
  }

  // The host bridge can return response lines over the same USB serial link.
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.startsWith("PRINTER_OK")) {
      digitalWrite(LED_BUILTIN, HIGH);
    }
  }
}
