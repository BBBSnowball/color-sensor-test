#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: [p.pyftdi])"

# use ftdi_urls.py in the nix-shell to list available device.
#url = "ftdi:///1"  # just use the first one / only one
url = 'ftdi://ftdi:2232h/1'

# datasheet: https://cdn-shop.adafruit.com/datasheets/TCS34725.pdf

import sys
import pyftdi.gpio
from time import sleep

dev = pyftdi.gpio.GpioAsyncController()
dev.open_from_url(url=url)
dev.set_direction(0xf, 0x3)

def i2c_bla(address, read, readlen_or_data):
	dev.set_direction(0xf, 0x3)
	dev.write(0x3)
	dev.write(0x1)  # start condition
	if read:
		addr = address*2 | 1
	else:
		addr = address*2 | 0
	prev = 0x0
	for i in range(8):
		dev.write(prev)
		if (addr & (1<<(7-i))) != 0:
			dev.write(0x2)
			dev.write(0x3)
			prev = 0x2
		else:
			dev.write(0x0)
			dev.write(0x1)
			prev = 0x0
	if prev != 0:
		dev.set_direction(0xf, 0x1)
		dev.write(0x0)
	else:
		dev.write(0x0)
		dev.set_direction(0xf, 0x1)
	ack = dev.read(peek=True)
	#print(ack)
	if (ack & 2) == 0:
		if not read and len(readlen_or_data) == 0:
			dev.write(0x1)
			dev.write(0x0)
			dev.set_direction(0xf, 0x3)
			dev.write(0x1)
			dev.write(0x3)
			return True
		elif read:
			read_data = []
			dev.set_direction(0xf, 0x1)
			dev.write(0x1)
			for i in range(readlen_or_data):
				d = 0
				for j in range(8):
					dev.write(0x0)
					dev.set_direction(0xf, 0x1)
					dev.write(0x1)
					#print("byte %d, bit %d: %d" % (i, j, (dev.read(peek=True) & 2) != 0))
					d *= 2
					if (dev.read(peek=True) & 2) != 0:
						d |= 1
				print("byte %d: 0x%02x" % (i, d))
				read_data.append(d)
				dev.write(0x0)
				if i == readlen_or_data-1:
					#pass  # nack
					# stop condition
					dev.write(0x0)
					dev.set_direction(0xf, 0x3)
					dev.write(0x1)
					dev.write(0x3)
				else:
					# send ack
					dev.write(0x0)
					dev.set_direction(0xf, 0x3)
					dev.write(0x1)
			return d
		else:
			dev.write(0x1)
			for byte in readlen_or_data:
				prev = 0x0
				dev.set_direction(0xf, 0x3)
				for j in range(8):
					dev.write(prev)
					if (byte & (1<<(7-j))) != 0:
						dev.write(0x2)
						dev.write(0x3)
						prev = 0x2
					else:
						dev.write(0x0)
						dev.write(0x1)
						prev = 0x0
				if prev != 0:
					dev.set_direction(0xf, 0x1)
					dev.write(0x0)
				else:
					dev.write(0x0)
					dev.set_direction(0xf, 0x1)
				ack = dev.read(peek=True)
				print(ack)
				if (ack & 2) == 0:
					dev.write(0x1)
				else:
					dev.write(0x0)
					dev.set_direction(0xf, 0x3)
					dev.write(0x1)
					dev.write(0x3)  # stop condition
					return False
			dev.write(0x0)
			dev.set_direction(0xf, 0x3)
			dev.write(0x1)
			dev.write(0x3)  # stop condition
			return True
	else:
		dev.write(0x0)
		dev.set_direction(0xf, 0x3)
		dev.write(0x1)
		dev.write(0x3)  # stop condition
		return False

if not i2c_bla(0x29, False, [0xa0 | 0]):
	print("not found")
	sys.exit(1)
regs = i2c_bla(0x29, True, 0x1c)
if regs[0x12] != 0x44:
	print("Reg 0x12 should be 0x44 but it is 0x%02x" % regs[0x12])
	sys.exit(1)
sys.exit()
print(i2c_bla(0x29, False, [0xa0 | 0]))
print(i2c_bla(0x29, True, 1))

for i in range(128):
	while True:
		try:
			print((i, i2c_bla(i, False, [])))
			break
		except pyftdi.ftdi.FtdiError:
			print("error")

sys.exit()


i2c.force_clock_mode(True)   # why is this necessary? this is a H series device?!
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
	return device.exchange([0xa0 | (regaddr & 0x1f)], readlen=length)
def tcs_write(regaddr, data):
	return device.exchange([0xa0 | (regaddr & 0x1f)] + data)

print(repr(tcs_read(0)))
tcs_write(0, [0x01])
print(repr(tcs_read(0)))

