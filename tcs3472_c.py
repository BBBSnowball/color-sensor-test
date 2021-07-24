#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: with p; [pyserial tkinter])"

import sys
import serial
from time import sleep
import tkinter
from tkinter import N, E, W, S, IntVar, Label
import threading
import re

def run_gui(serial_device):
  root = tkinter.Tk()
  root.columnconfigure(1, weight=1)
  root.rowconfigure(0, weight=1)

  row = 0
  canvas = tkinter.Canvas(root)
  canvas.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=2)
  row += 1

  led0 = IntVar(value=0)
  check_led0 = tkinter.Checkbutton(root, variable=led0, text="LED 0")
  check_led0.grid(column=0, row=row, columnspan=2, sticky=W)
  led1 = IntVar(value=0)
  check_led1 = tkinter.Checkbutton(root, variable=led1, text="LED 1")
  check_led1.grid(column=1, row=row, columnspan=2, sticky=W)
  row += 1
  
  integration_time = IntVar(value=62)
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

  global prev
  prev = (0, 0, 0, 0)
  def on_sensor_data(sensor_index, clear, red, green, blue):
    global prev
    step = 1
    w = canvas.winfo_width()
    h = canvas.winfo_height() - 45 - 50
    max = (1<<16) + 50
    if sensor_index == 0:
      color_as_text.configure(state = "normal")
      color_as_text.delete(0, "end")
      color_as_text.insert(0, "%04x, %04x, %04x, %04x" % (clear, red, green, blue))
      color_as_text.configure(state = "readonly")

      canvas.move("lines", -step, 0)
      canvas.create_line(w-step-1, h+2-prev[0]*h/max, w-1, h+2-clear*h/max, tags=("clear", "lines"), fill="black", width=2)
      canvas.create_line(w-step-1, h+2-prev[1]*h/max, w-1, h+2-red*h/max, tags=("red", "lines"), fill="red", width=2)
      canvas.create_line(w-step-1, h+2-prev[2]*h/max, w-1, h+2-green*h/max, tags=("green", "lines"), fill="green", width=2)
      canvas.create_line(w-step-1, h+2-prev[3]*h/max, w-1, h+2-blue*h/max, tags=("blue", "lines"), fill="blue", width=2)
      canvas.delete("bars")
      canvas.create_rectangle(0, h+5, clear*w/max, h+15, tags=("clear", "bars"), fill="black")
      canvas.create_rectangle(0, h+15, red*w/max, h+25, tags=("red", "bars"), fill="red")
      canvas.create_rectangle(0, h+25, green*w/max, h+35, tags=("green", "bars"), fill="green")
      canvas.create_rectangle(0, h+35, blue*w/max, h+45, tags=("blue", "bars"), fill="blue")
      prev = (clear, red, green, blue)
      root.update()
    elif sensor_index == 1:
      canvas.delete("bars1")
      canvas.create_rectangle(0, h+45+5,  clear*w/max, h+45+15, tags=("clear", "bars1"), fill="black")
      canvas.create_rectangle(0, h+45+15, red*w/max, h+45+25, tags=("red", "bars1"), fill="red")
      canvas.create_rectangle(0, h+45+25, green*w/max, h+45+35, tags=("green", "bars1"), fill="green")
      canvas.create_rectangle(0, h+45+35, blue*w/max, h+45+45, tags=("blue", "bars1"), fill="blue")

  if False:
    on_sensor_data(0, 10000, 0, 0)
    on_sensor_data(100, 0, 65535, 0)
    on_sensor_data(1000, 0, 65535, 1000)
    on_sensor_data(10000, 0, 0, 0)

  mainloop_done = False
  def query_sensor():
    ser = serial.serial_for_url(serial_device, timeout=2)
    ser.write(b":echo=0\r\n:auto=1\r\n?\r\n")
    state = 0
    values = {}
    while True:
      line = b""
      while len(line) == 0 or line[-1] != b"\n"[0]:
        line += ser.read()
      line = line.strip()
      if line == b"":
        pass
      if state == 0:
        # first line is most likely only a partial one -> ignore it
        state = 1
      elif line in [b"%ok"]:
        pass
      elif state == 1 and line == b"%values":
        state = 2
      elif state == 2 and line == b"%end":
        state = 3
        break
      elif state == 2 and line[0] == b":"[0]:
        eq = line.find(b"=")
        if eq >= 0:
          values[line[1:eq]] = int(line[eq+1:])
      else:
        print("unexpected line: %r" % line)

    if b"tcs0.gain" in values:
      gain.set(values[b"tcs0.gain"])
    if b"tcs0.itime" in values:
      integration_time.set(values[b"tcs0.itime"])
    if b"tcs0.led" in values:
      led0.set(values[b"tcs0.led"])
    if b"tcs1.led" in values:
      led1.set(values[b"tcs1.led"])

    prev_integration_time = integration_time.get()
    prev_gain = gain.get()
    prev_led0 = led0.get()
    prev_led1 = led1.get()

    line = b""
    while not mainloop_done:
      #FIXME wait for reply
      if prev_led0 != led0.get():
        print("update LED 0")
        ser.write(b":tcs0.led=%d\r\n" % led0.get())
        prev_led0 = led0.get()
      if prev_led1 != led1.get():
        print("update LED 1")
        ser.write(b":tcs1.led=%d\r\n" % led1.get())
        prev_led1 = led1.get()
      if prev_integration_time != integration_time.get():
        print("update integration_time")
        ser.write(b":tcs0.itime=%d\r\n" % integration_time.get())
        ser.write(b":tcs1.itime=%d\r\n" % integration_time.get())
        prev_integration_time = integration_time.get()
      if prev_gain != gain.get():
        print("update gain")
        ser.write(b":tcs0.gain=%d\r\n" % gain.get())
        ser.write(b":tcs1.gain=%d\r\n" % gain.get())
        prev_gain = gain.get()

      line += ser.read()
      if len(line) > 0 and line[-1] == b"\n"[0]:
        line = line.strip()
        if line == b"":
          pass
        elif line in [b"%ok"] or line[0] == '#'[0]:
          print(line)
        elif re.match(b':tcs[01][.]present=[01]', line):
          #TODO do something useful
          print(line)
        elif re.match(b':tcs([01])[.]color=[(]0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+)[)]', line):
          #print("color: %r" % line)
          m = re.match(b':tcs([01])[.]color=[(]0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+)[)]', line)
          tcs_index = int(m[1])
          if not mainloop_done:
            root.after_idle(on_sensor_data, tcs_index, int(m[2], 16), int(m[3], 16), int(m[4], 16), int(m[5], 16))
        line = b""
  t = threading.Thread(target=query_sensor)
  t.start()

  root.mainloop()
  mainloop_done = True
  t.join()

if __name__ == "__main__":
  run_gui(sys.argv[1])
