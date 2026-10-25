#include <Motors.h>

//motor base constructor
Motor::Motor(uint8_t pin1, uint8_t pin2)  {
    this->pin1=pin1;
    this->pin2=pin2;
  pinMode(this->pin1, OUTPUT);
  pinMode(this->pin2, OUTPUT);
}

CytronMDD10A::CytronMDD10A(uint8_t pwmPin, uint8_t dirPin)
  : Motor(pwmPin, dirPin) {
  stop();
}

void CytronMDD10A::move(uint8_t dir, uint8_t speed) {
  if (dir!=cur_dir){
   unsigned long t=millis();
   stop();
   while(millis()-t < 10);
   cur_dir=dir;
  }
  uint8_t written=0.1*cur_spd+0.9*speed;
  cur_spd=written;
  digitalWrite(pin2, dir == FORWARD ? HIGH : LOW);  // DIR
  analogWrite(pin1, written);                         // PWM
}

void CytronMDD10A::stop() {
  analogWrite(pin1, 0);
}


CytronSmallDriver::CytronSmallDriver(uint8_t pinA, uint8_t pinB): Motor(pinA, pinB) {
  stop();
}

void CytronSmallDriver::move(uint8_t dir, uint8_t speed) {
    if (dir!=cur_dir){
   unsigned long t=millis();
   stop();
   while(millis()-t < 10);
   cur_dir=dir;
  }
  uint8_t written=0.1*cur_spd+0.9*speed;
  cur_spd=written;
  
  if (dir == FORWARD) {
    analogWrite(pin1, written);
    analogWrite(pin2, 0);
  } else {
    analogWrite(pin1, 0);
    analogWrite(pin2, written);
  }
}

void CytronSmallDriver::stop() {
  analogWrite(pin1, 0);
  analogWrite(pin2, 0);
}