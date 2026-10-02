void setup() {
  Serial.begin(9600);
  delay(1000);
  Serial.println("VT Bioprinter DFRduino OK");
}

void loop() {
  Serial.println("Controller alive");
  delay(1000);
}
