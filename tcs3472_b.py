#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: [p.pyftdi])"

# use ftdi_urls.py in the nix-shell to list available device.
#url = "ftdi:///1"  # just use the first one / only one
url = 'ftdi://ftdi:2232h/1'

# datasheet: https://cdn-shop.adafruit.com/datasheets/TCS34725.pdf

import sys
import pyftdi.gpio
from time import sleep

class I2CBitbanging(object):
	__slots__ = ("dev", "_gpio_direction", "_gpio_value", "_i2c_direction", "_i2c_value")

	def __init__(self, url):
		self.dev = pyftdi.gpio.GpioAsyncController()
		self.dev.open_from_url(url=url)
		self.dev.set_direction(0xff, 0x1)
		self._gpio_direction = 0
		self._gpio_value = 0
		self._i2c_direction = 0x1
		self._i2c_value = 0x3

	def _update_direction(self):
		self.dev.set_direction(0xff, self._i2c_direction | (self._gpio_direction & 0xf8))
	def _update_gpout(self):
		self.dev.write(self._i2c_value | (self._gpio_value & 0xf8))
	def _write(self, value):
		self._i2c_value = value
		self._update_gpout()
	def _sda_in(self):
		self._i2c_direction = 0x1
		self._update_direction()
	def _sda_out(self):
		self._i2c_direction = 0x3
		self._update_direction()
	def _read_sda(self):
		return (self.dev.read(peek=True) & 0x2) != 0

	@property
	def gpio_direction(self):
		return self._gpio_direction
	@property
	def gpio_value(self):
		return self._gpio_value
	@gpio_direction.setter
	def gpio_direction(self, value):
		self._gpio_direction = value
		self._update_direction()
	@gpio_value.setter
	def gpio_value(self, value):
		self._gpio_value = value
		self._update_gpout()

	def transfer(self, address, read, readlen_or_data):
		#NOTE for self._write: bit 0 is SCK, bit 1 is SDA
		self._sda_out()
		self._write(0x3)
		self._write(0x1)  # start condition
		if read:
			addr = address*2 | 1
		else:
			addr = address*2 | 0
		prev = 0x0
		for i in range(8):
			self._write(prev)
			if (addr & (1<<(7-i))) != 0:
				self._write(0x2)
				self._write(0x3)
				prev = 0x2
			else:
				self._write(0x0)
				self._write(0x1)
				prev = 0x0
		if prev != 0:
			self._sda_in()
			self._write(0x0)
		else:
			self._write(0x0)
			self._sda_in()
		nack = self._read_sda()
		if not nack:
			if not read and len(readlen_or_data) == 0:
				self._write(0x1)
				self._write(0x0)
				self._sda_out()
				self._write(0x1)
				self._write(0x3)
				return True
			elif read:
				read_data = []
				self._sda_in()
				self._write(0x1)
				for i in range(readlen_or_data):
					d = 0
					for j in range(8):
						self._write(0x0)
						self._sda_in()
						self._write(0x1)
						d *= 2
						if self._read_sda():
							d |= 1
					print("byte %d: 0x%02x" % (i, d))
					read_data.append(d)
					self._write(0x0)
					if i == readlen_or_data-1:
						#pass  # nack
						# stop condition
						self._write(0x0)
						self._sda_out()
						self._write(0x1)
						self._write(0x3)
					else:
						# send ack
						self._write(0x0)
						self._sda_out()
						self._write(0x1)
				return read_data
			else:
				self._write(0x1)
				for byte in readlen_or_data:
					prev = 0x0
					self._sda_out()
					for j in range(8):
						self._write(prev)
						if (byte & (1<<(7-j))) != 0:
							self._write(0x2)
							self._write(0x3)
							prev = 0x2
						else:
							self._write(0x0)
							self._write(0x1)
							prev = 0x0
					if prev != 0:
						self._sda_in()
						self._write(0x0)
					else:
						self._write(0x0)
						self._sda_in()
					nack = self._read_sda()
					print(not nack)
					if not nack:
						self._write(0x1)
					else:
						self._write(0x0)
						self._sda_out()
						self._write(0x1)
						self._write(0x3)  # stop condition
						return False
				self._write(0x0)
				self._sda_out()
				self._write(0x1)
				self._write(0x3)  # stop condition
				return True
		else:
			self._write(0x0)
			self._sda_out()
			self._write(0x1)
			self._write(0x3)  # stop condition
			return False

	def read(self, address, length):
		return self.transfer(address, True, length)

	def write(self, address, data):
		return self.transfer(address, False, data)

class TCS3472(object):
	__slots__ = ("i2c", "address", "_regs")
	
	def __init__(self, i2c, address):
		self.i2c = i2c
		self.address = address
		self.i2c.gpio_direction |= 0x08
		
		id_reg = self.read_reg(0x12)
		if not id_reg:
			raise Exception("not found (I2C NACK)")
		elif id_reg[0] != 0x44:
			raise Exception("Reg 0x12 should be 0x44 but it is 0x%02x" % regs[0x12])

		self._regs = self.read_reg(0x00, 0x1c)
		if not self._regs:
			raise Exception("not found (I2C NACK)")
		elif self._regs[0x12] != 0x44:
			raise Exception("Reg 0x12 should be 0x44 but it is 0x%02x (as part of larger read)" % regs[0x12])

	@property
	def led(self):
		return (self.i2c.gpio_value & 0x08) != 0
	@led.setter
	def led(self, value):
		if value:
			self.i2c.gpio_value |= 0x08
		else:
			self.i2c.gpio_value &= ~0x08

	def read_reg(self, regaddr, length=1):
		if self.i2c.write(self.address, [0xa0 | (regaddr & 0x1f)]):
			return self.i2c.read(self.address, length)
	def write_reg(self, regaddr, data):
		return self.i2c.write([0xa0 | (regaddr & 0x1f)] + data)
		

i2c = I2CBitbanging(url)
tcs = TCS3472(i2c, 0x29)

#i2c.gpio_direction = 0x08
#i2c.gpio_value = 0x08
#sleep(0.5)
#i2c.gpio_value = 0x00
#sleep(0.5)
#i2c.gpio_value = 0x08

tcs.led = True
sleep(0.5)
tcs.led = False
sleep(0.5)
tcs.led = True

if False:
	if not i2c.write(0x29, [0xa0 | 0x12]):
		print("not found")
		sys.exit(1)
	id_reg = i2c.read(0x29, 1)
	if id_reg[0] != 0x44:
		print("Reg 0x12 should be 0x44 but it is 0x%02x" % regs[0x12])
		sys.exit(1)
	print(i2c.write(0x29, [0xa0 | 0]))
	regs = i2c.read(0x29, 0x1c)
	if regs[0x12] != 0x44:
		print("Reg 0x12 should be 0x44 but it is 0x%02x" % regs[0x12])
		sys.exit(1)

#print(i2c.write(0x29, [0xa0 | 0]))
#print(i2c.read(0x29, 1))

if False:
	for i in range(128):
		while True:
			try:
				print((i, i2c.transfer(i, False, [])))
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

