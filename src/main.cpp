#include <Arduino.h>
#include <Wire.h>
#include <BitBang_I2C.h>

constexpr int LED0 = 4;
constexpr int LED1 = 7;

constexpr int I2C1_SDA = 5;
constexpr int I2C1_SCL = 6;

BBI2C i2c1;

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
  int useWire;
  bool initialized;
  uint8_t gain, integrationTime;
  uint8_t part_number_ident;

  static uint8_t tmp[10];
public:
  TCS3472(int useWire) {
    this->useWire = useWire;
    this->initialized = false;
    this->gain = 1;
    this->integrationTime = 63;
  }

	bool readRegs(uint8_t regaddr, uint8_t* buf, uint8_t length) {
    int retry = 2;
    again:
    if (useWire) {
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
      if (I2CWrite(&i2c1, address, tmp, 1) != 1) {
        if (!retry)
          return false;
        retry--;
        goto again;
      }

      if (!I2CRead(&i2c1, address, buf, length)) {
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
    if (useWire) {
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
      if (I2CWrite(&i2c1, address, tmp, length+1) != length+1) {
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
    if (useWire) {
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
      if (I2CWrite(&i2c1, address, tmp, 1) != 1) {
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

TCS3472 tcs[2] = { true, false };

void setup() {
  Serial.println(F("%startup: TCS3472 Test"));

  pinMode(LED0, OUTPUT);
  pinMode(LED1, OUTPUT);
  digitalWrite(LED0, 0);
  digitalWrite(LED1, 0);

  Wire.begin();
  Wire.setClock(400000);

  memset(&i2c1, 0, sizeof(i2c1));
  i2c1.iSDA = I2C1_SDA;
  i2c1.iSCL = I2C1_SCL;
  i2c1.bWire = 0;
  I2CInit(&i2c1, 100000L);
}

void loop1() {
  Serial.println("blub");
  delay(500);
}

void loop2() {
  digitalWrite(LED0, 1); delay(500);
  digitalWrite(LED0, 0); delay(500);
  digitalWrite(LED1, 1); delay(500);
  digitalWrite(LED1, 0); delay(500);
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

static bool tcs_present[2] = { false, false };
static bool auto_poll = false, echo = true;

void pollSensors() {
  static TCS3472::Measurement color;

  bool present = tcs[0].prepare(true);
  if (present != tcs_present[0]) {
    tcs_present[0] = present;
    Serial.print(F(":tcs0.present="));
    Serial.println(present);
  }
  if (present) {
    if (tcs[0].readMeasurement(&color)) {
      Serial.print(F(":tcs0.color=(0x"));
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

  present = tcs[1].prepare(true);
  if (present != tcs_present[1]) {
    tcs_present[1] = present;
    Serial.print(F(":tcs1.present="));
    Serial.println(present);
  }
  if (present) {
    if (tcs[1].readMeasurement(&color)) {
      Serial.print(F(":tcs1.color=(0x"));
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

void allSensorRegs() {
  uint8_t buf[8];
  for (uint8_t tcs_index=0; tcs_index<2; tcs_index++) {
    Serial.print(F("TCS3472: tcs"));
    Serial.println(tcs_index);
    Serial.println(F("    00 01 02 03 04 05 06 07"));
    for (uint8_t row=0; row<4; row++) {
      printHex((uint8_t)(row*8));
      Serial.print(':');
      if (!tcs[tcs_index].readRegs(8*row, buf, 8)) {
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
    for (int i=0; i<2; i++) {
      Serial.print(F(":tcs"));
      Serial.print(i);
      Serial.print(F(".present="));
      Serial.println(tcs_present[i]);
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
      if (i == 0)
        Serial.println(digitalRead(LED0));
      else
        Serial.println(digitalRead(LED1));
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
    } else if (inbuf_cnt > 7 && memcmp(inbuf, ":tcs", 4) == 0 && (inbuf[4] == '0' || inbuf[4] == '1') && inbuf[5] == '.') {
      uint8_t tcs_index = inbuf[4] - '0';

      if (memcmp(inbuf+6, "gain=", 5) == 0)
        ok = tcs[tcs_index].setGain(value);
      else if (memcmp(inbuf+6, "itime=", 6) == 0)
        ok = tcs[tcs_index].setIntegrationTime(value);
      else if (memcmp(inbuf+6, "led=", 4) == 0) {
        if (tcs_index == 0)
          digitalWrite(LED0, !!value);
        else
          digitalWrite(LED1, !!value);
        ok = true;
      } else
        goto invalid_command;
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
