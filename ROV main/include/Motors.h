#ifndef MOTORS_H
#define MOTORS_H

#include <Arduino.h>

#define FORWARD 0
#define BACKWARD 1

class Motor {
public:

  Motor(uint8_t pin1, uint8_t pin2);
  virtual ~Motor() {}

  virtual void move(uint8_t dir, uint8_t speed) = 0;
  virtual void stop() = 0;

protected:
  uint8_t pin1;
  uint8_t pin2;
};


class CytronMDD10A : public Motor {
public:
  CytronMDD10A(uint8_t pwmPin, uint8_t dirPin);

  void move(uint8_t dir, uint8_t speed) override;
  void stop() override;
};

class CytronSmallDriver : public Motor {
public:
  CytronSmallDriver(uint8_t pinA, uint8_t pinB);

  void move(uint8_t dir, uint8_t speed) override;
  void stop() override;
};

#endif