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
  tcs_count = 3

  root = tkinter.Tk()
  root.columnconfigure(tcs_count-1, weight=1)
  root.rowconfigure(0, weight=1)

  row = 0
  canvas = tkinter.Canvas(root)
  canvas.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=tcs_count)
  row += 1

  ledvars = []
  for i in range(tcs_count):
    ledvar = IntVar(value=0)
    check_led = tkinter.Checkbutton(root, variable=ledvar, text="LED %d"%i)
    check_led.grid(column=i, row=row, sticky=W)
    ledvars.append(ledvar)
  row += 1

  slider_params = (("Integration time", 62, 0, 255, b"tcs%d.itime"), ("Gain", 1, 0, 3, b"tcs%d.gain"),
    ("WS2812 red", 0, 0, 255, b"led0.r"), ("WS2812 green", 0, 0, 255, b"led0.g"), ("WS2812 blue", 0, 0, 255, b"led0.b"))
  slider_vars = []
  for p in slider_params:
    var = IntVar(value=p[1])
    slider_vars.append(var)
    Label(root, text=p[0]).grid(column=0, row=row, sticky=(W,))
    slider_inst = tkinter.Scale(root, from_=p[2], to=p[3], variable=var, orient=tkinter.HORIZONTAL, takefocus=True)
    slider_inst.grid(column=1, row=row, columnspan=tcs_count-1, sticky=(E, W))
    row += 1
  integration_time, gain, led_red, led_green, led_blue = slider_vars

  color_as_text = tkinter.Entry(root)
  color_as_text.grid(column=0, row=row, columnspan=tcs_count, sticky=(E, W))
  color_as_text.insert(0, "...")
  color_as_text.configure(state = "readonly")
  row += 1

  global prev
  prev = (0, 0, 0, 0)
  def on_sensor_data(sensor_index, clear, red, green, blue):
    global prev
    step = 1
    w = canvas.winfo_width()
    h = canvas.winfo_height() - 45*tcs_count
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
      prev = (clear, red, green, blue)

    bars_tag = "bars%d" % sensor_index
    canvas.delete(bars_tag)
    h0 = h + 45*sensor_index
    canvas.create_rectangle(0, h0+5,  clear*w/max, h0+15, tags=("clear", bars_tag), fill="black")
    canvas.create_rectangle(0, h0+15, red  *w/max, h0+25, tags=("red",   bars_tag), fill="red")
    canvas.create_rectangle(0, h0+25, green*w/max, h0+35, tags=("green", bars_tag), fill="green")
    canvas.create_rectangle(0, h0+35, blue *w/max, h0+45, tags=("blue",  bars_tag), fill="blue")

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

    vars = ledvars + slider_vars
    var_names = [b"tcs%d.led"%i for i in range(tcs_count)] + [p[4] for p in slider_params]

    for var, name in zip(vars, var_names):
      if b"%d" in name:
        name = name%0
      if name in values:
        print("%r is %r" % (name, values[name]))
        var.set(values[name])
      else:
        print("value not sent by Arduino for %r" % name)

    prev_values = [v.get() for v in vars]

    line = b""
    while not mainloop_done:
      #FIXME wait for reply
      current_values = [v.get() for v in vars]
      for name, prev, current in zip(var_names, prev_values, current_values):
        if prev != current:
          print("update %s" % name)
          if b"%d" in name:
            for i in range(tcs_count):
              ser.write(b":%s=%d\r\n" % (name%i, current))
          else:
            ser.write(b":%s=%d\r\n" % (name, current))
      prev_values = current_values

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
        elif re.match(b':tcs(\d+)[.]color=[(]0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+)[)]', line):
          #print("color: %r" % line)
          m = re.match(b':tcs(\d+)[.]color=[(]0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+), *0x([0-9a-fA-F]+)[)]', line)
          tcs_index = int(m[1])
          if not mainloop_done:
            root.after_idle(on_sensor_data, tcs_index, int(m[2], 16), int(m[3], 16), int(m[4], 16), int(m[5], 16))
        else:
          print("line not recognized: %r" % line)
        line = b""
  t = threading.Thread(target=query_sensor)
  t.start()

  root.mainloop()
  mainloop_done = True
  t.join()

if __name__ == "__main__":
  run_gui(sys.argv[1])
