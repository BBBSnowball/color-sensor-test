This repository contains code for evaluating the TCS3472 and - later - maybe compare it to other options, e.g. APDS-9960.

* `tcs3472_ftdi.py`: One sensor connected to a Sipeed RV Debugger. I2C is done by bitbanging via USB so this is very slow.
* `tcs3472_arduino.py`: Three sensors and one WS2812-F8 connected to an Arduino Pro Micro (ATmega32U4). See `src/main.cpp` for the firmware of the Arduino.

License: MIT for my code but libraries have other licenses (e.g. GPL) and it is based on the PlatformIO project template (PlatformIO uses an Apache license)
