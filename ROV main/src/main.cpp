#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>
#include<Motors.h>

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
int heartbeat=-1;
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
//the convention used here is that the pwm first then dir pin


#define TL_IN1 PB0   // pwm1
#define TL_IN2 PB1   // pwm2

#define TR_IN1 PA6   // pwm3
#define TR_IN2 PA7   // pwm4

#define BR_IN1 PA2   // pwm5
#define BR_IN2 PA3   // pwm6

#define BL_IN1 PA0   // pwm7
#define BL_IN2 PA1   // pwm8

#define UP1_PWM PB6  // pwm9
#define UP1_DIR PB7  // pwm10
#define UP2_PWM PB8  // pwm11
#define UP2_DIR PB9  // pwm12
CytronMDD10A v1(UP1_PWM,UP1_DIR);
CytronMDD10A v2(UP2_PWM,UP2_DIR);
CytronMDD10A tl(TL_IN1,TL_IN2);
CytronMDD10A tr(TR_IN1,TR_IN2);
CytronSmallDriver bl(BR_IN1,BR_IN2);
CytronSmallDriver br(BL_IN1,BL_IN2);

// this array aims to achieve runtime polymorphism so when an action is applied to all no need to specify the exact class
Motor* motors[] = { &tl,&tr,&bl,&br,&v1, &v2 };

#define FAILSAFE_TIMEOUT 1000  // stop motors if no packet arrives within this window (ms)

unsigned long lastPacketTime = 0;
bool motorsStopped = false;



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



    lastPacketTime = millis();   // don't trip the failsafe at boot
    LOGLN("UDP Motor Controller Ready");
}

void updateMotors(uint8_t* data) {
    // ===== 4 main motors (PWM + DIR via dual-input driver) =====
    for (uint8_t i = 0; i < 4; i++) {
        uint8_t speed = data[i];
        uint8_t dir   = data[6 + i];   // 0 or 1
        motors[i]->move(dir,speed);
}

    v1.move(data[10],data[4]);
    v2.move(data[10],data[5]);
}

void stopMotors() {
    for (Motor* m: motors){
        m->stop();

    }}




void loop() {
    Ethernet.maintain();

    int packetSize;
    while ((packetSize = Udp.parsePacket()) > 0) {
        if (packetSize == 12) {
            Udp.read(Packet, 12);
            uint8_t hb = Packet[11];
            // i am thinking about making the heartt beat be a counter from 0 to 255 (i+=1;i%=256) to be able to detect more drops or know if the packets are old
            if (heartbeat != -1 && hb != heartbeat) {
                stopMotors();                
                motorsStopped = true;
            } else {
                updateMotors(Packet);
                lastPacketTime = millis();
                motorsStopped = false;
            }
            heartbeat = hb ^ 1;             
        } else {
            Udp.flush();                      
        }
    }

    if (!motorsStopped &&
        (millis() - lastPacketTime > FAILSAFE_TIMEOUT ||
         Ethernet.linkStatus() == LinkOFF)) {
        stopMotors();
        motorsStopped = true;
        heartbeat=-1;
    }
}