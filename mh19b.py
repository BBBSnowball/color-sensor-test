#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: with p; [pyserial tkinter numpy])"

import sys
import math
import serial
import struct
from time import sleep

def checksum(packet):
  return 0xff - sum(packet[1:8]) + 1

def send_command(cmd, bytes):
  global ser

  if len(bytes) != 5:
    raise Exception("command needs exactly five bytes as arguments")

  cmd = bytes((0xff, 1, cmd)) + bytes
  cmd += bytes((checksum(cmd),))
  ser.write(cmd)

def send_command_with_response(cmd, bytes):
  global ser

  old_timeout = ser.timeout
  ser.timeout = 0.1
  ser.read(100)
  ser.timeout = old_timeout

  send_command(cmd, bytes)
  response = ser.read(9)
  print(repr(response))

  if len(response) != 9:
    print("WARN: wrong length: %r" % (response,))
    return None
  x = response.find(0xff)
  if x == 0:
    pass
  elif x > 0:
    response = response[x:] + ser.read(x)
    if len(response) != 9:
      print("WARN: wrong length (after dropping %d bytes to get to 0xff): %r" % (x, response))
      return None
  else:
    print("WARN: reply doesn't start with 0xff: %r" % (response,))
    return None

  expected = checksum(response)
  if expected != response[8]:
    print("WARN: wrong checksum: %r, is 0x%02x, should be 0x%02x" % (response, response[8], expected))
    return None

  if response[1] != cmd:
    print("WARN: wrong command code in reply: %r, is 0x%02x, should be 0x%02x" % (response, response[1], cmd))
    return None

  return response[2:8]

def send_command_with_ack(cmd, bytes):
  response = send_command_with_response(cmd, bytes)
  if not response:
    return response
  elif response == "\x01\0\0\0\0\0":
    return True
  else:
    print("WARN: expected ACK but got: %r" % (response,))
    return False

def fetch_co2_unlimited():
  response = send_command_with_response(0x85, "\0\0\0\0\0")
  if not response:
    return response
  else:
    temperature_adc, co2_unclamped, min_light_adc = struct.unpack(">HHH", response)
    return { "temperature_adc": temperature_adc, "co2_unclamped": co2_unclamped, "min_light_adc": min_light_adc }

def fetch_auto_calibration_enabled():
  response = send_command_with_response(0x7D, "\0\0\0\0\0")
  if not response:
    return response
  else:
    return response[5] != 0

def set_auto_calibration_enabled(enable):
  if enable:
    return send_command_with_ack(0x79, "\xa0\0\0\0\0")
  else:
    return send_command_with_ack(0x79, "\0\0\0\0\0")

# see https://github.com/WifWaf/MH-Z19/blob/master/src/MHZ19.cpp
def verify():
  #x = fetch_co2_unlimited()
  response = send_command_with_response(0x85, "\0\0\0\0\0")
  if not x:
    return False

  # repeat last response
  response2 = send_command_with_response(0xA2, "\0\0\0\0\0")
  if not x:
    return False
  elif response != response2:
    print("WARN: response to 0xA2 is not equal to previous response: %r != %r" % (response, response2))

  return True

def run(serial_device):
  global ser
  ser = serial.serial_for_url(serial_device, timeout=2, baudrate=9600)

  print(repr(fetch_auto_calibration_enabled()))
  verify()
  set_auto_calibration(False)

if __name__ == "__main__":
  run(sys.argv[1])
