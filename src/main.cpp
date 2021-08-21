#include <Arduino.h>
#include <Wire.h>
#include <BitBang_I2C.h>
#include <FastLED.h>

constexpr int TCS_COUNT = 3;
constexpr int APDS_COUNT = 3;

constexpr int TCS0_SDA = 2;  // hardware I2C
constexpr int TCS0_SCL = 3;
constexpr int TCS0_LED = 14;
constexpr int TCS1_SDA = 16;
constexpr int TCS1_SCL = 10;
constexpr int TCS1_LED = 15;
constexpr int TCS2_SDA = A0; // 18
constexpr int TCS2_SCL = 10;
constexpr int TCS2_LED = A1; // 19

constexpr int LED[TCS_COUNT] = { TCS0_LED, TCS1_LED, TCS2_LED };

//NOTE We use 5V but those lines are connected to 3.3V.
//     -> BitBang_I2C only pulls low but not high so the
//        pullups will pull to 3.3V and the device will
//        never see any harmful 5V.
constexpr int APDS0_SDA = 5;
constexpr int APDS0_SCL = 4;
constexpr int APDS1_SDA = 6;
constexpr int APDS1_SCL = 4;
constexpr int APDS2_SDA = 7;
constexpr int APDS2_SCL = 4;

constexpr int NUM_LEDS = 1;
constexpr int LED_PIN = A3;

BBI2C bbi2c[TCS_COUNT+APDS_COUNT-1];

void printHex(uint32_t x, uint8_t digits) {
  char buf[9];
  char *ptr = buf + sizeof(buf) - 1;
  *ptr = 0;
  digits = min(digits, sizeof(buf)-1);

  for (int i=0; i<digits; i++) {
    uint8_t digit = x & 0xf;
    *--ptr = digit < 10 ? digit + '0' : digit + 'A' - 10;
    x >>= 4;
  };

  Serial.write(ptr);
}

void printHex(uint8_t  x) { printHex(x, 2); }
void printHex(uint16_t x) { printHex(x, 4); }
void printHex(uint32_t x) { printHex(x, 8); }

class TCS3472 {
  static const uint8_t address = 0x29;
  BBI2C* i2cInstance;
  bool initialized;
  uint8_t gain, integrationTime;
  uint8_t part_number_ident;

  static uint8_t tmp[10];

  friend class APDS9960;
public:
  TCS3472(BBI2C* i2cInstance) {  // i2cInstance==NULL -> use Wire
    this->i2cInstance = i2cInstance;
    this->initialized = false;
    this->gain = 1;
    this->integrationTime = 63;
  }

	bool readRegs(uint8_t regaddr, uint8_t* buf, uint8_t length) {
    int retry = 2;
    again:
    if (!i2cInstance) {
      Wire.beginTransmission(address);
      Wire.write(0xa0 | (regaddr & 0x1f));
      switch (Wire.endTransmission()) {
        case 0: break;
        case 1: return false;
        default:
          if (!retry)
            return false;
          retry--;
          goto again;
      }

      Wire.requestFrom(address, length);
      if (Wire.readBytes(buf, length) != length) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      return true;
    } else {
      tmp[0] = 0xa0 | (regaddr & 0x1f);
      if (I2CWrite(i2cInstance, address, tmp, 1) != 1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      if (!I2CRead(i2cInstance, address, buf, length)) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      return true;
    }
  }

	bool writeRegs(uint8_t regaddr, const uint8_t* buf, uint8_t length) {
    int retry = 2;
    again:
    if (!i2cInstance) {
      Wire.beginTransmission(address);
      Wire.write(0xa0 | (regaddr & 0x1f));
      for (int i=0; i<length; i++)
        Wire.write(buf[i]);
      switch (Wire.endTransmission()) {
        case 0: break;
        case 1: return false;
        default:
          if (!retry)
            return false;
          retry--;
          goto again;
      }
      return true;
    } else {
      if ((size_t)(length+1) > sizeof(tmp))
        return false;  // too long
      tmp[0] = 0xa0 | (regaddr & 0x1f);
      memcpy(tmp+1, buf, length);
      if (I2CWrite(i2cInstance, address, tmp, length+1) != length+1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }
      return true;
    }
  }

	bool writeReg(uint8_t regaddr, uint8_t value) {
    return writeRegs(regaddr, &value, 1);
  }

	bool clearInterrupt() {
    int retry = 2;
    again:
    if (!i2cInstance) {
      Wire.beginTransmission(address);
      Wire.write(0xe6);
      switch (Wire.endTransmission()) {
        case 0: break;
        case 1: return false;
        default:
          if (!retry)
            return false;
          retry--;
          goto again;
      }
      return true;
    } else {
      tmp[0] = 0xe6;
      if (I2CWrite(i2cInstance, address, tmp, 1) != 1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }
      return true;
    }
  }

  bool check(bool verbose) {
    uint8_t id_reg;
    if (!readRegs(0x12, &id_reg, 1)) {
      if (verbose)
        Serial.println(F("#warn: not found (I2C NACK)"));
      return false;
    }
    // 0x44 = TCS34721 or TCS34725 (I2C with VDD), 0x4D = TCS34723 or TCS34727 (I2C with 1.8V)
    this->part_number_ident = id_reg;
    if (id_reg != 0x44 && id_reg != 0x4D) {
      if (verbose) {
        Serial.print(F("#warn: Reg 0x12 should be 0x44 or 0x4D but it is 0x"));
        printHex(id_reg);
        Serial.println();
      }
      return false;
    }
    return true;
  }

  uint8_t getPartNumberIdentification() {
    return part_number_ident;
  }

  uint8_t getGain() {
    return gain;
  }

  bool setGain(uint8_t gain) {
    if (gain > 4)
      return false;

    if (initialized) {
      if (!writeReg(0x0f, gain))
        return false;
    }

    this->gain = gain;
    return true;
  }

  uint8_t getIntegrationTime() {
    return integrationTime;
  }

  bool setIntegrationTime(uint8_t integrationTime) {
    if (initialized) {
      if (!writeReg(0x01, 0xff - integrationTime))
        return false;
    }

    this->integrationTime = integrationTime;
    return true;
  }

  bool prepare(bool verbose) {
    if (initialized)
      return true;
    if (!check(verbose))
      return false;

    // Set low threshold > high threshold so we will always get an interrupt because the interrupt
    // bit is the only thing that tells us that there is a new value (because we cannot clear the
    // valid bit).
    uint8_t values[] = { 0x11, (uint8_t)(0xff - integrationTime), 0x00, 0x80, 0xff, 0xff, 0x00, 0x00 };
    if (!writeRegs(0x00, values, sizeof(values)))
      return false;
    if (!writeReg(0x0d, 0x00))
      return false;
    if (!writeReg(0x0f, gain))
      return false;
    delayMicroseconds(2400);
    if (!writeReg(0x00, 0x0b))
      return false;

    this->initialized = true;
    return true;
  }

  struct Measurement {
    uint16_t brightness, red, green, blue;
  } __attribute__((packed));

  static uint16_t fromLittleEndian(uint16_t x) {
    #if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
      return x;
    #elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
      return (x >> 8) | (x << 8);
    #else
    #  error Unsupported byte order!
    #endif
  }

  bool readMeasurement(Measurement* result) {
    uint8_t status_reg;
    if (!readRegs(0x13, &status_reg, 1)) {
      this->initialized = false;
      return false;
    }

    if (!(status_reg & 0x10))
      return false;
    clearInterrupt();

    // datasheet says to use two byte reads with "read word protocol bit set" but there is no such bit in the command register
    // -> auto-increment read should be good enough to trigger the shadow register behavior, I guess
    if (!readRegs(0x14, (uint8_t*)result, 8))
      return false;

    result->brightness = fromLittleEndian(result->brightness);
    result->red        = fromLittleEndian(result->red);
    result->green      = fromLittleEndian(result->green);
    result->blue       = fromLittleEndian(result->blue);
    return true;
  }
};
uint8_t TCS3472::tmp[10];

TCS3472 tcs[TCS_COUNT] = { NULL, bbi2c+0, bbi2c+1 };

//FIXME merge with TCS3472 class
class APDS9960 {
  static const uint8_t address = 0x39;
  BBI2C* i2cInstance;
  bool initialized;
  uint8_t gain, integrationTime;
  uint8_t part_number_ident;
public:
  APDS9960(BBI2C* i2cInstance) {  // i2cInstance==NULL -> use Wire
    this->i2cInstance = i2cInstance;
    this->initialized = false;
    this->gain = 1;
    this->integrationTime = 63;
  }

	bool readRegs(uint8_t regaddr, uint8_t* buf, uint8_t length) {
    int retry = 2;
    again:
    if (!i2cInstance) {
      Wire.beginTransmission(address);
      Wire.write(regaddr & 0xff);
      switch (Wire.endTransmission()) {
        case 0: break;
        case 1: return false;
        default:
          if (!retry)
            return false;
          retry--;
          goto again;
      }

      Wire.requestFrom(address, length);
      if (Wire.readBytes(buf, length) != length) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      return true;
    } else {
      TCS3472::tmp[0] = regaddr & 0xff;
      if (I2CWrite(i2cInstance, address, TCS3472::tmp, 1) != 1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      if (!I2CRead(i2cInstance, address, buf, length)) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      return true;
    }
  }

	bool writeRegs(uint8_t regaddr, const uint8_t* buf, uint8_t length) {
    int retry = 2;
    again:
    if (!i2cInstance) {
      Wire.beginTransmission(address);
      Wire.write(regaddr & 0xff);
      for (int i=0; i<length; i++)
        Wire.write(buf[i]);
      switch (Wire.endTransmission()) {
        case 0: break;
        case 1: return false;
        default:
          if (!retry)
            return false;
          retry--;
          goto again;
      }
      return true;
    } else {
      if ((size_t)(length+1) > sizeof(TCS3472::tmp))
        return false;  // too long
      TCS3472::tmp[0] = regaddr & 0xff;
      memcpy(TCS3472::tmp+1, buf, length);
      if (I2CWrite(i2cInstance, address, TCS3472::tmp, length+1) != length+1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }
      return true;
    }
  }

	bool writeReg(uint8_t regaddr, uint8_t value) {
    return writeRegs(regaddr, &value, 1);
  }

	bool clearInterrupt() {
    int retry = 2;
    again:
    if (!i2cInstance) {
      Wire.beginTransmission(address);
      Wire.write(0xe6);
      switch (Wire.endTransmission()) {
        case 0: break;
        case 1: return false;
        default:
          if (!retry)
            return false;
          retry--;
          goto again;
      }
      return true;
    } else {
      TCS3472::tmp[0] = 0xe6;
      if (I2CWrite(i2cInstance, address, TCS3472::tmp, 1) != 1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }
      return true;
    }
  }

  bool check(bool verbose) {
    uint8_t id_reg;
    if (!readRegs(0x92, &id_reg, 1)) {
      if (verbose)
        Serial.println(F("#warn: not found (I2C NACK)"));
      return false;
    }
    this->part_number_ident = id_reg;
    if (id_reg != 0xAB) {
      if (verbose) {
        Serial.print(F("#warn: Reg 0x92 should be 0xAB but it is 0x"));
        printHex(id_reg);
        Serial.println();
      }
      return false;
    }
    return true;
  }

  uint8_t getPartNumberIdentification() {
    return part_number_ident;
  }

  uint8_t getGain() {
    return gain;
  }

  bool setGain(uint8_t gain) {
    if (gain > 4)
      return false;

    if (initialized) {
      if (!writeReg(0x8f, gain | (gain << 3) | (3 << 6)))
        return false;
    }

    this->gain = gain;
    return true;
  }

  uint8_t getIntegrationTime() {
    return integrationTime;
  }

  bool setIntegrationTime(uint8_t integrationTime) {
    if (initialized) {
      if (!writeReg(0x81, 0xff - integrationTime))
        return false;
    }

    this->integrationTime = integrationTime;
    return true;
  }

  bool prepare(bool verbose) {
    if (initialized)
      return true;
    if (!check(verbose))
      return false;

    // Set low threshold > high threshold so we will always get an interrupt because the interrupt
    // bit is the only thing that tells us that there is a new value (because we cannot clear the
    // valid bit).
    uint8_t values[] = { 0x11, (uint8_t)(0xff - integrationTime), 0x00, 0xff, 0xff, 0xff, 0x00, 0x00 };
    if (!writeRegs(0x80, values, sizeof(values)))
      return false;
    if (!writeReg(0x8d, 0x00))
      return false;
    if (!writeReg(0x8f, gain | (gain << 2) | (3 << 6)))
      return false;
    delayMicroseconds(2400);
    if (!writeReg(0x80, 0x0b))
      return false;

    this->initialized = true;
    return true;
  }

  typedef TCS3472::Measurement Measurement;

  static uint16_t fromLittleEndian(uint16_t x) {
    #if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
      return x;
    #elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
      return (x >> 8) | (x << 8);
    #else
    #  error Unsupported byte order!
    #endif
  }

  bool readMeasurement(Measurement* result) {
    uint8_t status_reg;
    if (!readRegs(0x93, &status_reg, 1)) {
      this->initialized = false;
      return false;
    }

    if (!(status_reg & 0x10))
      return false;
    clearInterrupt();

    // datasheet says to use two byte reads with "read word protocol bit set" but there is no such bit in the command register
    // -> auto-increment read should be good enough to trigger the shadow register behavior, I guess
    if (!readRegs(0x94, (uint8_t*)result, 8))
      return false;

    result->brightness = fromLittleEndian(result->brightness);
    result->red        = fromLittleEndian(result->red);
    result->green      = fromLittleEndian(result->green);
    result->blue       = fromLittleEndian(result->blue);
    return true;
  }
};

APDS9960 apds[APDS_COUNT] = { bbi2c+TCS_COUNT-1+0, bbi2c+TCS_COUNT-1+1, bbi2c+TCS_COUNT-1+2 };

CRGB leds[NUM_LEDS];

void setup() {
  Serial.println(F("%startup: TCS3472 Test"));

  for (size_t i=0; i<sizeof(LED)/sizeof(*LED); i++) {
    pinMode(LED[i], OUTPUT);
    digitalWrite(LED[i], 0);
  }

  Wire.begin();
  Wire.setClock(400000);

  memset(bbi2c+0, 0, sizeof(*bbi2c));
  bbi2c[0].iSDA = TCS1_SDA;
  bbi2c[0].iSCL = TCS1_SCL;
  bbi2c[0].bWire = 0;
  I2CInit(bbi2c+0, 100000L);

  memset(bbi2c+1, 0, sizeof(*bbi2c));
  bbi2c[1].iSDA = TCS2_SDA;
  bbi2c[1].iSCL = TCS2_SCL;
  bbi2c[1].bWire = 0;
  I2CInit(bbi2c+1, 100000L);

  memset(bbi2c+2, 0, sizeof(*bbi2c));
  bbi2c[2].iSDA = APDS0_SDA;
  bbi2c[2].iSCL = APDS0_SCL;
  bbi2c[2].bWire = 0;
  I2CInit(bbi2c+2, 100000L);

  memset(bbi2c+3, 0, sizeof(*bbi2c));
  bbi2c[3].iSDA = APDS1_SDA;
  bbi2c[3].iSCL = APDS1_SCL;
  bbi2c[3].bWire = 0;
  I2CInit(bbi2c+3, 100000L);

  memset(bbi2c+4, 0, sizeof(*bbi2c));
  bbi2c[4].iSDA = APDS2_SDA;
  bbi2c[4].iSCL = APDS2_SCL;
  bbi2c[4].bWire = 0;
  I2CInit(bbi2c+4, 100000L);

  FastLED.addLeds<WS2812, LED_PIN, RGB>(leds, NUM_LEDS);
  leds[0] = CRGB::Green; leds[0] /= 10;
  FastLED.show();
}

void loop1() {
  Serial.println("blub");
  delay(500);
}

void loop2() {
  for (size_t i=0; i<sizeof(LED)/sizeof(*LED); i++) {
    digitalWrite(LED[i], 1); delay(500);
    digitalWrite(LED[i], 0); delay(500);
  }
}

void loop3() {
  Serial.println("0x29:");
  Wire.beginTransmission(0x29);
  Wire.write(0xa0 | 0x12);
  auto result = Wire.endTransmission();
  Serial.println(result);

  Serial.println("0x28:");
  Wire.beginTransmission(0x28);
  Wire.write(0xa0 | 0x12);
  result = Wire.endTransmission();
  Serial.println(result);

  delay(2000);
}

static bool tcs_present[TCS_COUNT+APDS_COUNT] = { false, false };
static bool auto_poll = false, echo = true;

void pollSensors() {
  static TCS3472::Measurement color;
  static APDS9960::Measurement color2;

  for (uint8_t tcs_index=0; tcs_index<TCS_COUNT; tcs_index++) {
    bool present = tcs[tcs_index].prepare(true);
    if (present != tcs_present[tcs_index]) {
      tcs_present[tcs_index] = present;
      Serial.print(F(":tcs"));
      Serial.print(tcs_index);
      Serial.print(F(".present="));
      Serial.println(present);
    }
    if (present) {
      if (tcs[tcs_index].readMeasurement(&color)) {
        Serial.print(F(":tcs"));
        Serial.print(tcs_index);
        Serial.print(F(".color=(0x"));
        printHex(color.brightness);
        Serial.print(F(", 0x"));
        printHex(color.red);
        Serial.print(F(", 0x"));
        printHex(color.green);
        Serial.print(F(", 0x"));
        printHex(color.blue);
        Serial.println(F(")"));
      }
    }
  }

  for (uint8_t tcs_index=0; tcs_index<APDS_COUNT; tcs_index++) {
    bool present = apds[tcs_index].prepare(true);
    if (present != tcs_present[TCS_COUNT+tcs_index]) {
      tcs_present[TCS_COUNT+tcs_index] = present;
      Serial.print(F(":tcs"));
      Serial.print(TCS_COUNT+tcs_index);
      Serial.print(F(".present="));
      Serial.println(present);
    }
    if (present) {
      if (apds[tcs_index].readMeasurement(&color2)) {
        Serial.print(F(":tcs"));
        Serial.print(TCS_COUNT+tcs_index);
        Serial.print(F(".color=(0x"));
        printHex(color2.brightness);
        Serial.print(F(", 0x"));
        printHex(color2.red);
        Serial.print(F(", 0x"));
        printHex(color2.green);
        Serial.print(F(", 0x"));
        printHex(color2.blue);
        Serial.println(F(")"));
      }
    }
  }
}

void allSensorRegs() {
  uint8_t buf[8];
  for (uint8_t tcs_index=0; tcs_index<TCS_COUNT+APDS_COUNT; tcs_index++) {
    Serial.print(tcs_index < TCS_COUNT ? F("TCS3472: tcs") : F("APDS9960: tcs"));
    Serial.println(tcs_index);
    Serial.println(F("    00 01 02 03 04 05 06 07"));
    for (uint8_t row=0; row<4 || (tcs_index >= TCS_COUNT && row < 256/8); row++) {
      printHex((uint8_t)(row*8));
      Serial.print(':');
      bool ok;
      if (tcs_index >= TCS_COUNT) {
        ok = apds[tcs_index-TCS_COUNT].readRegs(8*row, buf, 8);
      } else {
        ok = tcs[tcs_index].readRegs(8*row, buf, 8);
      }
      if (!ok) {
        Serial.println(F(" couldn't read"));
        continue;
      }
      for (uint8_t reg=0; reg<8; reg++) {
        Serial.print(' ');
        printHex(buf[reg]);
      }
      Serial.println();
    }
    Serial.println();
  }
}

void handleInput(char* inbuf, uint8_t inbuf_cnt) {
  if (inbuf_cnt == 1 && inbuf[0] == '?') {
    Serial.println(F("%values"));
    for (int i=0; i<TCS_COUNT; i++) {
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".present="));
      Serial.println(tcs_present[i]);
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".type="));
      switch (tcs[i].getPartNumberIdentification()) {
        case 0x44: Serial.println(F("TCS34721")); break;
        case 0x4D: Serial.println(F("TCS34723")); break;
        default:   Serial.println(F("TCS3472x")); break;
      }
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".gain="));
      Serial.println(tcs[i].getGain());
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".itime="));
      Serial.println(tcs[i].getIntegrationTime());
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".partnum="));
      Serial.println(tcs[i].getPartNumberIdentification());
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".led="));
      Serial.println(digitalRead(LED[i]));
    }
    for (int i=0; i<APDS_COUNT; i++) {
      Serial.print(F(":tcs"));
      Serial.print(TCS_COUNT+i);
      Serial.print(F(".present="));
      Serial.println(tcs_present[TCS_COUNT+i]);
      Serial.print(F(":tcs"));
      Serial.print(TCS_COUNT+i);
      Serial.println(F(".type=APDS9960"));
      Serial.print(F(":tcs"));
      Serial.print(TCS_COUNT+i);
      Serial.print(F(".gain="));
      Serial.println(apds[i].getGain());
      Serial.print(F(":tcs"));
      Serial.print(TCS_COUNT+i);
      Serial.print(F(".itime="));
      Serial.println(apds[i].getIntegrationTime());
      Serial.print(F(":tcs"));
      Serial.print(TCS_COUNT+i);
      Serial.print(F(".partnum="));
      Serial.println(apds[i].getPartNumberIdentification());
      //Serial.print(F(":tcs"));
      //Serial.print(TCS_COUNT+i);
      //Serial.print(F(".led="));
      //Serial.println(digitalRead(LED[i]));
    }
    for (int i=0; i<NUM_LEDS; i++) {
      Serial.print(F(":led"));
      Serial.print(i);
      Serial.print(F(".r="));
      Serial.println(leds[i].red);
      Serial.print(F(":led"));
      Serial.print(i);
      Serial.print(F(".g="));
      Serial.println(leds[i].green);
      Serial.print(F(":led"));
      Serial.print(i);
      Serial.print(F(".b="));
      Serial.println(leds[i].blue);
    }
    Serial.println(F("%end"));
    return;
  } else if (memcmp(inbuf, ":poll", 6) == 0) {
    pollSensors();
    return;
  } else if (memcmp(inbuf, ":allSensorRegs", 15) == 0) {
    allSensorRegs();
    return;
  } else if (inbuf[0] == ':') {
    char* value_ptr = strchr(inbuf+5, '=');
    if (!value_ptr) goto invalid_command;
    if (!value_ptr[1]) goto invalid_format;

    uint8_t value = 0;
    while (*++value_ptr) {
      if (*value_ptr < '0' || *value_ptr > '9')
        goto invalid_format;
      value = value * 10 + (*value_ptr - '0');
    }

    bool ok;
    if (memcmp(inbuf, ":auto=", 6) == 0) {
      auto_poll = !!value;
      ok = true;
    } else if (memcmp(inbuf, ":echo=", 6) == 0) {
      echo = !!value;
      ok = true;
    } else if (inbuf_cnt > 7 && memcmp(inbuf, ":tcs", 4) == 0 && inbuf[4] >= '0' && inbuf[4]-'0' < TCS_COUNT && inbuf[5] == '.') {
      uint8_t tcs_index = inbuf[4] - '0';

      if (memcmp(inbuf+6, "gain=", 5) == 0)
        ok = tcs[tcs_index].setGain(value);
      else if (memcmp(inbuf+6, "itime=", 6) == 0)
        ok = tcs[tcs_index].setIntegrationTime(value);
      else if (memcmp(inbuf+6, "led=", 4) == 0) {
        digitalWrite(LED[tcs_index], !!value);
        ok = true;
      } else
        goto invalid_command;
    } else if (inbuf_cnt > 7 && memcmp(inbuf, ":led", 4) == 0 && inbuf[4] >= '0' && inbuf[4]-'0' < NUM_LEDS && inbuf[5] == '.') {
      uint8_t led_index = inbuf[4] - '0';

      if (memcmp(inbuf+6, "r=", 2) == 0)
        leds[led_index].r = value;
      else if (memcmp(inbuf+6, "g=", 2) == 0)
        leds[led_index].g = value;
      else if (memcmp(inbuf+6, "b=", 2) == 0) {
        leds[led_index].b = value;
      } else
        goto invalid_command;
      ok = true;
      FastLED.show();
    } else
      goto invalid_command;

    if (ok)
      Serial.println(F("%ok"));
    else
      Serial.println(F("%failed"));
    return;
  }
invalid_command:
  Serial.println(F("%ERR: invalid command"));
  Serial.print(F("#DEBUG: ")); Serial.print(inbuf); Serial.print(F("|, ")); Serial.println(inbuf_cnt);
  return;
invalid_format:
  Serial.println(F("%ERR: invalid format"));
  Serial.print(F("#DEBUG: ")); Serial.print(inbuf); Serial.print(F("|, ")); Serial.println(inbuf_cnt);
  return;
}

void loop() {
  static unsigned long last_poll = -200;
  if (!auto_poll) {
    last_poll = millis() - 200;
  } if (auto_poll && Serial.availableForWrite() > 10 && millis() - last_poll > 50) {
    last_poll = millis();
    pollSensors();
  }

  static char inbuf[20];
  static uint8_t inbuf_cnt = 0;
  static char prev_char = 0;
  while (Serial.available()) {
    char c = Serial.read();
    bool echo_this_one = echo;
    switch (c) {
      case '\r':
      case '\n':
        echo_this_one = false;
        if (inbuf_cnt == 0) {
          if (prev_char != '\r' || c != '\n')
            Serial.println();
        } else if ((size_t)(inbuf_cnt+1) < sizeof(inbuf)) {
          if (echo)
            Serial.println();
          inbuf[inbuf_cnt] = 0;
          handleInput(inbuf, inbuf_cnt);
        } else {
          if (echo)
            Serial.println();
          Serial.println("%ERR: too long");
        }
        inbuf_cnt = 0;
        break;
      case '\0':
      case 27:  // escape
        inbuf_cnt = 0;
        echo_this_one = false;
        if (echo)
          Serial.println();
        break;
      case 8:   // backspace
        if (inbuf_cnt > 0) {
          inbuf_cnt--;
          Serial.print(F("\x08 \x08"));
        }
        echo_this_one = false;
        break;
      default:
        if (c == '@' && !inbuf_cnt && false) {
          echo = false;
          Serial.println(F("%echo_off"));
        } else if (c < 32 || c > 128) {
          Serial.print(F("# char code: 0x"));
          printHex((uint8_t)c);
        } else if (inbuf_cnt < sizeof(inbuf)) {
          inbuf[inbuf_cnt++] = c;
        } else {
          echo_this_one = false;
        }
        break;
    }
    if (echo_this_one)
      Serial.write(c);
    prev_char = c;

    if (c == '*')
      delay(500); //DEBUG
  }
}
