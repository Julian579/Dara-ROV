#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>

// ===================== DEBUG LOG (USART1 -> J7 "usb ttl": PA9 TX / PA10 RX) =====================
#define DEBUG_LOG 1   // set to 0 for the real run: printing every packet slows the loop
#if DEBUG_LOG
#define LOG(x)   Serial.print(x)
#define LOGLN(x) Serial.println(x)
#else
#define LOG(x)
#define LOGLN(x)
#endif

// ===================== NETWORK CONFIG =====================
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
IPAddress ip(192, 168, 1, 50);
#define PORT 9090

EthernetUDP Udp;

// ===================== W5500 (per PCB) =====================
// SPI1 remapped: SCLK=PB3, MISO=PB4, MOSI=PB5, CS=PA15
// RST is not routed to any MCU pin on this PCB (no trace from PB12).
#define W5500_SCLK PB3
#define W5500_MISO PB4
#define W5500_MOSI PB5
#define W5500_CS   PA15

// ===================== PIN MAP (per PCB) =====================
// J4 cytron1:         pwm1=PB1, pwm2=PB0, pwm3=PA7, pwm4=PA6
// J5 cytron2:         pwm5=PA3, pwm6=PA2, pwm7=PA1, pwm8=PA0
// J6 vertical cytron: pwm9=PB6, pwm10=PB7, pwm11=PB8, pwm12=PB9
#define TL_IN1 PB1   // pwm1
#define TL_IN2 PB0   // pwm2

#define TR_IN1 PA7   // pwm3
#define TR_IN2 PA6   // pwm4

#define BR_IN1 PA3   // pwm5
#define BR_IN2 PA2   // pwm6

#define BL_IN1 PA1   // pwm7
#define BL_IN2 PA0   // pwm8

#define UP1_PWM PB6  // pwm9
#define UP1_DIR PB7  // pwm10
#define UP2_PWM PB8  // pwm11
#define UP2_DIR PB9  // pwm12

#define gripper PC13 // not routed to a connector on the PCB (this is the on-board LED pin)

#define FAILSAFE_TIMEOUT 1000  // stop motors if no packet arrives within this window (ms)

unsigned long lastPacketTime = 0;
bool motorsStopped = false;

const uint8_t IN1_PINS[6] = {TL_IN1, TR_IN1, BR_IN1, BL_IN1, UP1_PWM, UP2_PWM};
const uint8_t IN2_PINS[6] = {TL_IN2, TR_IN2, BR_IN2, BL_IN2, UP1_DIR, UP2_DIR};

uint8_t Packet[12];

void setup() {
#if DEBUG_LOG
    Serial.begin(115200);
    delay(300);
#endif

    // 1. Release PA15/PB3/PB4 from JTAG (SWD stays enabled) before using them
    __HAL_RCC_AFIO_CLK_ENABLE();
    __HAL_AFIO_REMAP_SWJ_NOJTAG();

    // 2. Keep the W5500 deselected
    pinMode(W5500_CS, OUTPUT);
    digitalWrite(W5500_CS, HIGH);

    // 3. Let the W5500 power up (its PLL needs time; no reset pin on this PCB)
    delay(500);

    // 4. Network first, motors after
    SPI.setMISO(W5500_MISO);
    SPI.setMOSI(W5500_MOSI);
    SPI.setSCLK(W5500_SCLK);

    Ethernet.init(W5500_CS);
    Ethernet.begin(mac, ip);
    Udp.begin(PORT);

    LOG("W5500 (4 = found): ");
    LOGLN((int)Ethernet.hardwareStatus());
    LOG("Link (1 = ON): ");
    LOGLN((int)Ethernet.linkStatus());

    // 5. Motor pins last
    for (uint8_t i = 0; i < 6; i++) {
        pinMode(IN1_PINS[i], OUTPUT);
        pinMode(IN2_PINS[i], OUTPUT);
    }
    pinMode(gripper, OUTPUT);

    lastPacketTime = millis();   // don't trip the failsafe at boot
    LOGLN("UDP Motor Controller Ready");
}

inline void updateMotors(uint8_t* data) {
    // ===== 4 main motors (PWM + DIR via dual-input driver) =====
    for (uint8_t i = 0; i < 4; i++) {
        uint8_t speed = data[i];
        uint8_t dir   = data[6 + i];   // 0 or 1

        if (dir == 0) {
            analogWrite(IN1_PINS[i], speed);
            analogWrite(IN2_PINS[i], 0);
        } else {
            analogWrite(IN1_PINS[i], 0);
            analogWrite(IN2_PINS[i], speed);
        }
    }

    // ===== vertical motors: full speed only, no PWM =====
    uint8_t up1_pwm = data[4];
    uint8_t up2_pwm = data[5];
    uint8_t up1_dir = data[10];   // packet has one vertical direction byte; UP2 shares it
    uint8_t grip    = data[11];

    if (up1_pwm == 0) {
        digitalWrite(UP1_PWM, LOW);
        digitalWrite(UP1_DIR, LOW);
    } else {
        digitalWrite(UP1_DIR, up1_dir);
        digitalWrite(UP1_PWM, HIGH);
    }

    if (up2_pwm == 0) {
        digitalWrite(UP2_PWM, LOW);
        digitalWrite(UP2_DIR, LOW);
    } else {
        digitalWrite(UP2_DIR, up1_dir);
        digitalWrite(UP2_PWM, HIGH);
    }

    digitalWrite(gripper, grip);
}

inline void stopMotors() {
    for (uint8_t i = 0; i < 4; i++) {
        analogWrite(IN1_PINS[i], 0);
        analogWrite(IN2_PINS[i], 0);
    }
    digitalWrite(UP1_PWM, LOW);
    digitalWrite(UP1_DIR, LOW);
    digitalWrite(UP2_PWM, LOW);
    digitalWrite(UP2_DIR, LOW);
}

void loop() {
    int packetSize;
    Ethernet.maintain();

    while ((packetSize = Udp.parsePacket()) > 0) {
        if (packetSize == 12) {
            Udp.read(Packet, 12);

#if DEBUG_LOG
            LOG("Packet: ");
            for (uint8_t i = 0; i < 12; i++) {
                LOG(Packet[i]);
                LOG(i < 11 ? "," : "\n");
            }
#endif

            updateMotors(Packet);
            lastPacketTime = millis();
            motorsStopped = false;
        } else {
            LOG("Unexpected packet size: ");
            LOGLN(packetSize);
            Udp.flush();
        }
    }

    // Stop once per timeout, not on every loop pass
    if (!motorsStopped && millis() - lastPacketTime > FAILSAFE_TIMEOUT) {
        stopMotors();
        motorsStopped = true;
    }
}