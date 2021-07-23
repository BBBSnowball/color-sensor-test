#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: [p.pyftdi])"


###### This one doesn't work. Use the other one! ######


# use ftdi_urls.py in the nix-shell to list available device.
#url = "ftdi:///1"  # just use the first one / only one
url = 'ftdi://ftdi:2232h/1'

# datasheet: https://cdn-shop.adafruit.com/datasheets/TCS34725.pdf

import sys
import pyftdi.ftdi
from pyftdi.i2c import I2cController, I2cNackError
from time import sleep

i2c = I2cController()

i2c.force_clock_mode(True)   # why is this necessary? this is a H series device?! -> well, actually it is an FT2232C...
#pyftdi.ftdi.Ftdi.is_H_series = lambda _: True  # oh, well...

i2c.configure(url, direction=0x08, initial=0x00, clockstretching=False, frequency = 10*1000)
#device = i2c.get_port(0x29)
device = i2c.get_port(0x01)

print(i2c.frequency)
print(i2c.ftdi.device_version)

print(i2c.poll(0x29, write=True))
sys.exit()

if False:
	for i in range(128):
		try:
			i2c.write(i, [])
			print("found 0x%02x" % i)
		except I2cNackError:
			pass

while True:
	if i2c.poll(0x01):
		print("0x28")
	sleep(0.05)

if True:
	for i in range(128):
		if i2c.poll(i):
			print("found 0x%02x" % i)

i2c.set_gpio_direction(0x08, 0x08)  # well, argument to configure doesn't seem to have any effect so do it again
i2c.write_gpio(0x08)
sleep(0.5)
i2c.write_gpio(0x00)
sleep(0.5)
i2c.write_gpio(0x08)

def tcs_read(regaddr, length=1):
	return device.exchange([0xa0 or (regaddr and 0x1f)], readlen=length)
def tcs_write(regaddr, data):
	return device.exchange([0xa0 or (regaddr and 0x1f)] + data)

print(repr(tcs_read(0)))
tcs_write(0, [0x01])
print(repr(tcs_read(0)))

