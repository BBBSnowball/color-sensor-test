#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: with p; [pyftdi tkinter])"

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

	def fix_i2c(self, always_generate_stop=False):
		while True:
			try:
				self._sda_in()
				if not self._read_sda() or always_generate_stop:
					# some device is pulling SDA low -> try to generate clocks to resolve this
					ok = False
					for _ in range(10):
						self._write(0x0)
						if self._read_sda():
							# SDA is released -> generate stop condition
							self._sda_out()
							self._write(0x1)
							self._write(0x3)  # stop condition
							ok = True
							break
						else:
							self._write(0x1)
					if not ok:
						raise Exception("Couldn't release SDA line by generating some clock pulses")

				return True
			except pyftdi.ftdi.FtdiError as exc:
				if str(exc) == "UsbError: [Errno 110] Operation timed out":  # we only get the string, sorry...
					print("ignoring timeout")
				else:
					raise

	def read(self, address, length):
		return self.transfer(address, True, length)

	def write(self, address, data):
		return self.transfer(address, False, data)

	def scan(self):
		for i in range(128):
			while True:
				try:
					print((i, i2c.transfer_autorepeat(i, False, [])))  #FIXME
					break
				except pyftdi.ftdi.FtdiError:
					print("error")

class I2CAutoRetry(object):
	__slots__ = ("i2c", "retry",)

	def __init__(self, i2c):
		self.i2c = i2c
		self.retry = True

	def __bool__(self):
		return self.retry

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if exc_type == pyftdi.ftdi.FtdiError and str(exc_value) == "UsbError: [Errno 110] Operation timed out":  # we only get the string, sorry...
			print("USB timeout -> try again")
			self.retry = True
			self.i2c.fix_i2c(always_generate_stop=True)
			return True  # suppress exception
		else:
			self.retry = False
			return False

class TCS3472(object):
	__slots__ = ("i2c", "address", "_regs")
	
	def __init__(self, i2c, address):
		self.i2c = i2c
		self.address = address
		self.i2c.gpio_direction |= 0x08
		
		id_reg = self.read_regs(0x12)
		if not id_reg:
			self.i2c.fix_i2c(True)
			id_reg = self.read_regs(0x12)
			if not id_reg:
				raise Exception("not found (I2C NACK)")
		elif id_reg[0] != 0x44:
			raise Exception("Reg 0x12 should be 0x44 but it is 0x%02x" % regs[0x12])

		self._regs = self.read_regs(0x00, 0x1c)
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

	def read_regs(self, regaddr, length=1):
		retry = I2CAutoRetry(self.i2c)
		while retry:
			with retry:
				if self.i2c.write(self.address, [0xa0 | (regaddr & 0x1f)]):
					return self.i2c.read(self.address, length)
	def write_regs(self, regaddr, data):
		retry = I2CAutoRetry(self.i2c)
		while retry:
			with retry:
				return self.i2c.write(self.address, [0xa0 | (regaddr & 0x1f)] + data)
		
def run():
	i2c = I2CBitbanging(url)
	tcs = TCS3472(i2c, 0x29)

	tcs.led = True
	sleep(0.5)
	tcs.led = False
	sleep(0.5)
	tcs.led = True

	integration_time = 0x80
	tcs.write_regs(0x00, [0x01, 0xff - integration_time, 0x80, 0x12, 0x34, 0x56, 0x78])
	tcs.write_regs(0x0d, [0x00])
	tcs.write_regs(0x0f, [0x01])  # gain
	sleep(0.0024)
	tcs.write_regs(0x00, [0x0b])
	while True:
		valid = tcs.read_regs(0x13)
		if (valid[0] & 1) != 0:
			# datasheet says to use two byte reads with "read word protocol bit set" but there is no such bit in the command register
			# -> auto-increment read should be good enough to trigger the shadow register behavior, I guess
			data = tcs.read_regs(0x14, 8)
			print("clear: %04x" % (data[0] | (data[1] << 8)))
			print("red:   %04x" % (data[2] | (data[3] << 8)))
			print("green: %04x" % (data[4] | (data[5] << 8)))
			print("blue:  %04x" % (data[6] | (data[7] << 8)))

def run_gui():
	import tkinter
	from tkinter import N, E, W, S, IntVar, Label
	import threading

	root = tkinter.Tk()
	root.columnconfigure(1, weight=1)
	root.rowconfigure(0, weight=1)

	row = 0
	canvas = tkinter.Canvas(root)
	canvas.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=2)
	row += 1

	led = IntVar(value=0)
	check_led = tkinter.Checkbutton(root, variable=led, text="LED")
	check_led.grid(column=0, row=row, columnspan=2, sticky=W)
	row += 1
	
	integration_time = IntVar(value=0x80)
	Label(root, text="Integration time").grid(column=0, row=row, sticky=(W,))
	slider_integration_time = tkinter.Scale(root, from_=0, to=255, variable=integration_time, orient=tkinter.HORIZONTAL)
	slider_integration_time.grid(column=1, row=row, sticky=(E, W))
	row += 1
	
	gain = IntVar(value=1)
	Label(root, text="Gain").grid(column=0, row=row, sticky=(W,))
	slider_gain = tkinter.Scale(root, from_=0, to=3, variable=gain, orient=tkinter.HORIZONTAL)
	slider_gain.grid(column=1, row=row, sticky=(E, W))
	row += 1

	color_as_text = tkinter.Entry(root)
	color_as_text.grid(column=0, row=row, columnspan=2, sticky=(E, W))
	color_as_text.insert(0, "...")
	color_as_text.configure(state = "readonly")
	row += 1

	i2c = I2CBitbanging(url)
	tcs = TCS3472(i2c, 0x29)

	tcs.write_regs(0x00, [0x01, 0xff - integration_time.get(), 0x80, 0x12, 0x34, 0x56, 0x78])
	tcs.write_regs(0x0d, [0x00])
	tcs.write_regs(0x0f, [gain.get()])  # gain
	sleep(0.0024)
	tcs.write_regs(0x00, [0x0b])

	def on_sensor_data(clear, red, green, blue):
		print("a")
		color_as_text.configure(state = "normal")
		color_as_text.delete(0, "end")
		color_as_text.insert(0, "%04x, %04x, %04x, %04x" % (clear, red, green, blue))
		color_as_text.configure(state = "readonly")
		root.update()
		print("b")

	mainloop_done = False
	def query_sensor():
		prev_integration_time = integration_time.get()
		prev_gain = gain.get()
		while not mainloop_done:
			if tcs.led  != (led.get() != 0):
				print("update LED")
				tcs.led = (led.get() != 0)
			if prev_integration_time != integration_time.get():
				print("update integration_time")
				tcs.write_regs(0x01, [0xff - integration_time.get()])
				prev_integration_time = integration_time.get()
			if prev_gain != gain.get():
				print("update gain")
				tcs.write_regs(0x0f, [gain.get()])
				prev_gain = gain.get()

			valid = tcs.read_regs(0x13)
			if (valid[0] & 1) != 0:
				# datasheet says to use two byte reads with "read word protocol bit set" but there is no such bit in the command register
				# -> auto-increment read should be good enough to trigger the shadow register behavior, I guess
				data = tcs.read_regs(0x14, 8)
				print("clear: %04x" % (data[0] | (data[1] << 8)))
				print("red:   %04x" % (data[2] | (data[3] << 8)))
				print("green: %04x" % (data[4] | (data[5] << 8)))
				print("blue:  %04x" % (data[6] | (data[7] << 8)))
				if not mainloop_done:
					root.after_idle(on_sensor_data,  (data[0] | (data[1] << 8)), (data[2] | (data[3] << 8)),
						(data[4] | (data[5] << 8)), (data[6] | (data[7] << 8)))
	t = threading.Thread(target=query_sensor)
	t.start()

	root.mainloop()
	mainloop_done = True
	t.join()

if __name__ == "__main__":
	#run()
	run_gui()

