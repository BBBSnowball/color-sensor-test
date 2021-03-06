#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p "python3.withPackages (p: with p; [pyserial tkinter numpy])"

import sys
import math
import serial
from time import sleep
import tkinter
from tkinter import N, E, W, S, X, Y, LEFT, IntVar, Label
import threading
import re
import numpy, numpy.linalg
import tempfile
import datetime

def run_gui(serial_device):
  tcs_count = 6

  root = tkinter.Tk()
  root.title("Color Sensor Test")
  root.configure(bg="black")
  root.columnconfigure(tcs_count-1, weight=1)
  root.rowconfigure(0, weight=1)

  row = 0
  canvas = tkinter.Canvas(root, bg="black")
  canvas.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=tcs_count)
  row += 1

  settings = tkinter.Frame(root)
  settings.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=tcs_count)
  row += 1
  logscale = IntVar(value=0)
  tkinter.Checkbutton(settings, variable=logscale, text="logarithmic scale").pack(side=LEFT)
  raw_values = IntVar(value=0)
  tkinter.Checkbutton(settings, variable=raw_values, text="show raw values (without correction)").pack(side=LEFT)

  clear_old_graphs = lambda *args: canvas.delete("lines")
  canvas.bind("<Configure>", clear_old_graphs)
  logscale.trace_variable("w", clear_old_graphs)
  raw_values.trace_variable("w", clear_old_graphs)

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
    slider_inst = tkinter.Scale(root, from_=p[2], to=p[3], variable=var, orient=tkinter.HORIZONTAL, takefocus=True, bg="black", fg="white")
    slider_inst.grid(column=1, row=row, columnspan=tcs_count-1, sticky=(E, W))
    row += 1
  integration_time, gain, led_red, led_green, led_blue = slider_vars

  color_as_text = tkinter.Entry(root)
  color_as_text.grid(column=0, row=row, columnspan=tcs_count, sticky=(E, W))
  color_as_text.insert(0, "...")
  color_as_text.configure(state = "readonly")
  row += 1

  ratios = tkinter.Frame(root)
  ratios.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=tcs_count)
  row += 1
  ratio_text = tkinter.StringVar()
  tkinter.Entry(ratios, textvariable=ratio_text).pack(side=LEFT, fill=X, expand=True)
  collect_ratios = IntVar(value=0)
  tkinter.Checkbutton(ratios, variable=collect_ratios, text="update").pack(side=LEFT)
  bt_clear_ratios = tkinter.Button(ratios, text="Clear")
  bt_clear_ratios.pack(side=LEFT)
  bt_print_ratios = tkinter.Button(ratios, text="Print to console")
  bt_print_ratios.pack(side=LEFT)

  global avg_ratios
  avg_ratios = [[0, 0, 0, 0, 0] for i in range(tcs_count)]
  def clear_ratios(*args):
    global avg_ratios
    avg_ratios = [[0, 0, 0, 0, 0] for i in range(tcs_count)]
  bt_clear_ratios.configure(command=clear_ratios)
  def print_ratios(*args):
    print("ratios: " + ratio_text.get())
  bt_print_ratios.configure(command=print_ratios)

  csvgen = tkinter.Frame(root)
  csvgen.grid(column=0, row=row, sticky=(N, E, W, S), columnspan=tcs_count)
  row += 1
  actuator_var = IntVar(value=0)
  tkinter.Radiobutton(csvgen, text="Int. Time", variable=actuator_var, value=0).pack(side=LEFT)
  tkinter.Radiobutton(csvgen, text="WS2812",    variable=actuator_var, value=1).pack(side=LEFT)
  tkinter.Radiobutton(csvgen, text="Monitor",   variable=actuator_var, value=2).pack(side=LEFT)
  tkinter.Radiobutton(csvgen, text="Gain",      variable=actuator_var, value=3).pack(side=LEFT)
  csvgen_progress_text = tkinter.StringVar(value="not started")
  tkinter.Label(csvgen, textvariable=csvgen_progress_text).pack(side=LEFT)
  bt_start_csvgen = tkinter.Button(csvgen, text="Start")
  bt_start_csvgen.pack(side=LEFT)

  color_window = tkinter.Toplevel(bg="orange")
  color_window.title("Color for test with monitor")
  color_window.withdraw()
  def on_actuator_var_changed(*args):
    if actuator_var.get() == 2:
      color_window.deiconify()
    else:
      color_window.withdraw()
  actuator_var.trace_variable("w", on_actuator_var_changed)

  global ok_count
  ok_count = 0
  global csvgen_state
  csvgen_state = 0
  def update_csvgen(sensor_index, raw, values):
    global csvgen_state
    global csvgen_data
    global csvgen_step
    global csvgen_rgb
    global csvgen_file
    global csvgen_expected_oks
    global ok_count

    if csvgen_state == 0:  # not active
      return
    elif csvgen_state == 1:  # set next value for actuator
      csvgen_step += 1
      csvgen_progress_text.set("step %d" % csvgen_step)
      if (actuator_var.get() == 0 and csvgen_step >= 256) or (actuator_var.get() == 3 and csvgen_step >= 4) or csvgen_step >= 256*7:
        print("csvgen done, data written to %s" % csvgen_file.name)
        csvgen_state = 0
        csvgen_progress_text.set("done")
        csvgen_file.close()
        bt_start_csvgen.configure(text="Start")
      elif actuator_var.get() == 0:
        ok_count = 0
        if csvgen_step != integration_time.get():
          integration_time.set(csvgen_step)
          csvgen_expected_oks = tcs_count
          csvgen_state = 2
        else:
          csvgen_state = 3
        csvgen_rgb = (csvgen_step, 0, 0)
      elif actuator_var.get() == 3:
        ok_count = 0
        if csvgen_step != gain.get():
          gain.set(csvgen_step)
          csvgen_expected_oks = tcs_count
          csvgen_state = 2
        else:
          csvgen_state = 3
        csvgen_rgb = (csvgen_step, 0, 0)
      else:
        if csvgen_step < 256:     # ramp up red   -> red
          r, g, b = csvgen_step, 0, 0
        elif csvgen_step < 2*256: # ramp up green -> yellow
          r, g, b = 255, csvgen_step-1*256, 0
        elif csvgen_step < 3*256: # ramp down red -> green
          r, g, b = 255-(csvgen_step-2*256), 255, 0
        elif csvgen_step < 4*256: # ramp up blue  -> cyan
          r, g, b = 0, 255, csvgen_step-3*256
        elif csvgen_step < 5*256: # ramp down green -> blue
          r, g, b = 0, 255-(csvgen_step-4*256), 255
        elif csvgen_step < 6*256: # ramp up red, again -> pink
          r, g, b = csvgen_step-5*256, 0, 255
        elif csvgen_step < 7*256: # ramp up green, again -> white
          r, g, b = 255, csvgen_step-6*256, 255
        else:
          raise Exception("unexpected")
        csvgen_rgb = (r, g, b)

        if actuator_var.get() == 1:
          ok_count = 0
          csvgen_expected_oks = 0
          if r != led_red.get():
            led_red.set(r)
            csvgen_expected_oks += 1
          if g != led_green.get():
            led_green.set(g)
            csvgen_expected_oks += 1
          if b != led_blue.get():
            led_blue.set(b)
            csvgen_expected_oks += 1
          csvgen_state = 2
        else:
          color_window.configure(bg="#%02x%02x%02x"%(r, g, b))
          csvgen_state = 3  # no need to wait for ok from Arduino
    elif csvgen_state == 2:  # wait for ok from Arduino
      #FIXME timeout and set again?
      if ok_count >= csvgen_expected_oks:
        csvgen_state = 3
    elif csvgen_state == 3:  # collect measurements
      pass  # handled below so we don't lose one measurement when switching to this state
    else:
      print("invalid state")
      csvgen_state = 0

    if csvgen_state == 3:  # collect measurements
      csvgen_data[sensor_index].append((raw, values))

      #FIXME skip sensors that don't provide any data, e.g. are not connected
      if min(len(vs) for vs in csvgen_data) >= 3:
        if csvgen_step == 0:
          time = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
          csvgen_file = tempfile.NamedTemporaryFile(prefix="tcstest%d--%s--" % (actuator_var.get(), time), suffix=".csv", delete=False, dir=".", mode="w")
          print("csvgen data will be written to %s" % csvgen_file.name)
          with open(csvgen_file.name + ".txt", "w") as f:
            f.write("mode=%d\nitime=%d\ngain=%d\nws2812.r=%d\nws2812.g=%d\nws2812.b=%d\n"
              % tuple(v.get() for v in (actuator_var, integration_time, gain, led_red, led_green, led_blue)))
          cells = ["mode", "step", "r", "g", "b"]
          for i in range(tcs_count):
            cells.extend(("sensor%d.raw_c1"%i, "sensor%d.raw_r1"%i, "sensor%d.raw_g1"%i, "sensor%d.raw_b1"%i, "sensor%d.raw_c2"%i, "sensor%d.raw_r2"%i, "sensor%d.raw_g2"%i, "sensor%d.raw_b2"%i))
            cells.extend(("sensor%d.c1"%i, "sensor%d.r1"%i, "sensor%d.g1"%i, "sensor%d.b1"%i, "sensor%d.c2"%i, "sensor%d.r2"%i, "sensor%d.g2"%i, "sensor%d.b2"%i))
            cells.extend(("sensor%d.c"%i, "sensor%d.r"%i, "sensor%d.g"%i, "sensor%d.b"%i))
          csvgen_file.write("\t".join(cells) + "\n")
        cells = []
        if actuator_var.get() == 0:
          cells.append("itime")
        elif actuator_var.get() == 1:
          cells.append("WS2812")
        elif actuator_var.get() == 2:
          cells.append("monitor")
        elif actuator_var.get() == 3:
          cells.append("gain")
        else:
          cells.append("??")
        cells.append(csvgen_step)
        cells.extend(csvgen_rgb)
        for d in csvgen_data:
          for i in [1, 2]:
            cells.extend(d[i][0])  # raw
          for i in [1, 2]:
            cells.extend(d[i][1])  # maybe compensated
          avg = (sum(v[1][j] for v in d[1:]) / len(d[1:]) for j in range(4))
          cells.extend(avg)
        csvgen_file.write("\t".join(map(str, cells)) + "\n")
        csvgen_file.flush()

        csvgen_state = 1
        for v in csvgen_data:
          v.clear()


  def csvgen_start(*args):
    global csvgen_state
    global csvgen_data
    global csvgen_step
    if csvgen_state == 0:
      csvgen_data = [[] for _ in range(tcs_count)]
      csvgen_step = -1
      csvgen_state = 1
      bt_start_csvgen.configure(text="Abort")
    else:
      csvgen_state = 0
      csvgen_progress_text.set("aborted")
      bt_start_csvgen.configure(text="Start")
  bt_start_csvgen.configure(command=csvgen_start)

  global prev, prevs
  prev = (0, 0, 0, 0)
  prevs = [(0, 0, 0, 0) for i in range(tcs_count)]
  def on_sensor_data(sensor_index, clear, red, green, blue):
    raw = (clear, red, green, blue)

    if clear > 0 and collect_ratios.get() != 0:
      avg_ratios[sensor_index][0] += 1
      avg_ratios[sensor_index][1] += red/clear
      avg_ratios[sensor_index][2] += green/clear
      avg_ratios[sensor_index][3] += blue/clear
      avg_ratios[sensor_index][4] += clear

      ratio_text.set(", ".join("(%4.2f, %4.2f, %4.2f, %5.0f)" % (x[1]/x[0], x[2]/x[0], x[3]/x[0], x[4]/x[0]) for x in avg_ratios if x[0] > 0))

    if raw_values.get() == 0:
      # Test wavelength from the TCS34725 datasheet match WS2812D-F8 to within 10 nm so these values should be a good match.
      # This is the "Optical Characteristics" data from the datasheet. We are using the average of min and max because the
      # typical value isn't specified.
      # https://cdn-shop.adafruit.com/datasheets/TCS34725.pdf
      rgb_to_tcs_datasheet = numpy.transpose(numpy.array(((0.8+1.1, 0+0.14, 0.05+0.24), (0.04+0.25, 0.60+0.85, 0.10+0.45), (0.00+0.15, 0.10+0.42, 0.65+0.88)))/2)
      # gain=0, itime=255 (max), WS2812 at maximum, width of Pro Micro above the sensor, average over 5 seconds, other light sources are less than 1/1000 for the clear value
      rgb_to_tcs__sensor0_a = numpy.transpose(numpy.array((
        (0.93, 0.04, 0.09),  # value/clear for red,   clear=17003
        (0.09, 0.63, 0.25),  # value/clear for green, clear=13293
        (0.01, 0.22, 0.78),  # value/clear for blue,  clear=14130
      )))
      rgb_to_tcs__sensor1_a = numpy.transpose(numpy.array((
        (0.88, 0.06, 0.09),  # value/clear for red,   clear=8294
        (0.09, 0.66, 0.27),  # value/clear for green, clear=7944
        (0.01, 0.25, 0.79),  # value/clear for blue,  clear=10477
      )))
      rgb_to_tcs__sensor2_a = numpy.transpose(numpy.array((
        (0.84, 0.04, 0.08),  # value/clear for red,   clear=10294
        (0.09, 0.55, 0.22),  # value/clear for green, clear=8298
        (0.01, 0.20, 0.65),  # value/clear for blue,  clear=11842
      )))
      # same as before bug gain=1 and other light sources are below 10 counts
      rgb_to_tcs__sensor0_b = numpy.transpose(numpy.array((
        (0.92, 0.04, 0.09),  # value/clear for red,   clear=54716
        (0.09, 0.63, 0.24),  # value/clear for green, clear=39902
        (0.01, 0.22, 0.77),  # value/clear for blue,  clear=49474
      )))
      rgb_to_tcs__sensor1_b = numpy.transpose(numpy.array((
        (0.88, 0.06, 0.09),  # value/clear for red,   clear=33426
        (0.09, 0.67, 0.27),  # value/clear for green, clear=38158
        (0.01, 0.25, 0.79),  # value/clear for blue,  clear=49202
      )))
      rgb_to_tcs__sensor2_b = numpy.transpose(numpy.array((
        (0.84, 0.04, 0.08),  # value/clear for red,   clear=43874
        (0.09, 0.55, 0.22),  # value/clear for green, clear=27910
        (0.01, 0.19, 0.66),  # value/clear for blue,  clear=44301
      )))
      # same as before bug gain=2, itime=160, distance is the *length* of a Pro Micro, and other light sources are below 50 counts
      rgb_to_tcs__sensor0_c = numpy.transpose(numpy.array((
        (0.93, 0.04, 0.09),  # value/clear for red,   clear=55809
        (0.09, 0.64, 0.25),  # value/clear for green, clear=41563
        (0.01, 0.22, 0.78),  # value/clear for blue,  clear=55916
      )))
      rgb_to_tcs__sensor1_c = numpy.transpose(numpy.array((
        (0.89, 0.06, 0.09),  # value/clear for red,   clear=36620
        (0.09, 0.66, 0.27),  # value/clear for green, clear=41630
        (0.01, 0.25, 0.78),  # value/clear for blue,  clear=48462
      )))
      rgb_to_tcs__sensor2_c = numpy.transpose(numpy.array((
        (0.84, 0.04, 0.08),  # value/clear for red,   clear=43001
        (0.09, 0.54, 0.23),  # value/clear for green, clear=43740
        (0.01, 0.19, 0.66),  # value/clear for blue,  clear=58406
      )))
      # same as before bug gain=3, itime=255 for red and green, itime=240 for blue, distance is 9cm over the middle sensor (sensor 1), and other light sources are below 100 counts
      rgb_to_tcs__sensor0_d = numpy.transpose(numpy.array((
        (0.92, 0.04, 0.07),  # value/clear for red,   clear=29655
        (0.09, 0.62, 0.22),  # value/clear for green, clear=46442
        (0.01, 0.21, 0.75),  # value/clear for blue,  clear=63688
      )))
      rgb_to_tcs__sensor1_d = numpy.transpose(numpy.array((
        (0.90, 0.06, 0.09),  # value/clear for red,   clear=17412
        (0.09, 0.66, 0.26),  # value/clear for green, clear=52489
        (0.01, 0.25, 0.79),  # value/clear for blue,  clear=65535
      )))
      rgb_to_tcs__sensor2_d = numpy.transpose(numpy.array((
        (0.88, 0.06, 0.09),  # value/clear for red,   clear=12422
        (0.08, 0.66, 0.25),  # value/clear for green, clear=37328
        (0.01, 0.22, 0.77),  # value/clear for blue,  clear=42840
      )))

      #rgb_to_tcs = rgb_to_tcs_datasheet
      #rgb_to_tcs = (rgb_to_tcs__sensor0_a + rgb_to_tcs__sensor1_a + rgb_to_tcs__sensor2_a + rgb_to_tcs__sensor0_b + rgb_to_tcs__sensor1_b + rgb_to_tcs__sensor2_b
      #  + rgb_to_tcs__sensor0_c + rgb_to_tcs__sensor1_c + rgb_to_tcs__sensor2_c + rgb_to_tcs__sensor0_d + rgb_to_tcs__sensor1_d + rgb_to_tcs__sensor2_d) / 12
      rgb_to_tcs = (rgb_to_tcs__sensor0_a + rgb_to_tcs__sensor1_a + rgb_to_tcs__sensor2_a + rgb_to_tcs__sensor0_b + rgb_to_tcs__sensor1_b + rgb_to_tcs__sensor2_b
        + rgb_to_tcs__sensor0_c + rgb_to_tcs__sensor1_c + rgb_to_tcs__sensor2_c) / 9
      tcs_to_rgb = numpy.linalg.inv(rgb_to_tcs)
      #NOTE All of the above need only be done once.

      red, green, blue = numpy.dot(tcs_to_rgb, (red, green, blue))
      #print("%d: %r -> %r" % (sensor_index, raw, (red, green, blue)))

    update_csvgen(sensor_index, raw, (clear, red, green, blue))

    if logscale.get() != 0:
      #disp_clear = math.log(clear)/math.log(1<<16)
      #disp_red   = math.log(red)  /math.log(1<<16)
      #disp_green = math.log(green)/math.log(1<<16)
      #disp_blue  = math.log(blue) /math.log(1<<16)
      #disp_sum   = math.log(red + green + blue)/math.log(1<<16)

      #factor = 1e-4
      #min = 1
      #disp_clear = (-math.log(factor*min) + math.log(factor*max(min, clear)))             /math.log(factor*(1<<16))
      #disp_red   = (-math.log(factor*min) + math.log(factor*max(min, red)))               /math.log(factor*(1<<16))
      #disp_green = (-math.log(factor*min) + math.log(factor*max(min, green)))             /math.log(factor*(1<<16))
      #disp_blue  = (-math.log(factor*min) + math.log(factor*max(min, blue)))              /math.log(factor*(1<<16))
      #disp_sum   = (-math.log(factor*min) + math.log(factor*max(min, red + green + blue)))/math.log(factor*(1<<16))

      #FIXME This is still not really useful...
      power = 200
      min_limit = 1
      vmin       = math.log(min_limit,                          power)
      vmax       = math.log(1<<16,                              power)
      disp_clear = math.log(max(min_limit, clear),              power)
      disp_red   = math.log(max(min_limit, red),                power)
      disp_green = math.log(max(min_limit, green),              power)
      disp_blue  = math.log(max(min_limit, blue),               power)
      disp_sum   = math.log(max(min_limit, red + green + blue), power)
      disp_clear = (disp_clear-vmin)/(vmax-vmin)
      disp_red   = (disp_red  -vmin)/(vmax-vmin)
      disp_green = (disp_green-vmin)/(vmax-vmin)
      disp_blue  = (disp_blue -vmin)/(vmax-vmin)
      disp_sum   = (disp_sum  -vmin)/(vmax-vmin)
    else:
      disp_clear = clear/(1<<16)
      disp_red   = red  /(1<<16)
      disp_green = green/(1<<16)
      disp_blue  = blue /(1<<16)
      disp_sum = disp_red + disp_green + disp_blue

    global prevs
    prevs[sensor_index] = raw
    color_as_text.configure(state = "normal")
    color_as_text.delete(0, "end")
    color_as_text.insert(0, ", ".join("(%04x, %04x, %04x, %04x)" % x for x in prevs))
    color_as_text.configure(state = "readonly")

    step = 1
    w = canvas.winfo_width()
    h = canvas.winfo_height() - 45*tcs_count - 5
    if sensor_index == 0:
      global prev
      canvas.move("lines", -step, 0)
      canvas.create_line(w-step-1, h+2-prev[0]*h, w-1, h+2-disp_clear*h, tags=("clear", "lines"), fill="white", width=2)
      canvas.create_line(w-step-1, h+2-prev[1]*h, w-1, h+2-disp_red*h,   tags=("red", "lines"), fill="red", width=2)
      canvas.create_line(w-step-1, h+2-prev[2]*h, w-1, h+2-disp_green*h, tags=("green", "lines"), fill="green", width=2)
      canvas.create_line(w-step-1, h+2-prev[3]*h, w-1, h+2-disp_blue*h,  tags=("blue", "lines"), fill="blue", width=2)
      prev = (disp_clear, disp_red, disp_green, disp_blue)

    bars_tag = "bars%d" % sensor_index
    canvas.delete(bars_tag)
    h0 = h + 45*sensor_index
    wbar = w*0.8
    offset = w*0.1
    canvas.create_rectangle(offset, h0+5,  disp_clear*wbar + offset, h0+15, tags=("clear", bars_tag), fill="white",  outline="white")
    canvas.create_rectangle(offset, h0+8,  disp_sum  *wbar + offset, h0+12, tags=("clear", bars_tag), fill="orange", outline="orange")
    canvas.create_rectangle(offset, h0+15, disp_red  *wbar + offset, h0+25, tags=("red",   bars_tag), fill="red",    outline="red")
    canvas.create_rectangle(offset, h0+25, disp_green*wbar + offset, h0+35, tags=("green", bars_tag), fill="green",  outline="green")
    canvas.create_rectangle(offset, h0+35, disp_blue *wbar + offset, h0+45, tags=("blue",  bars_tag), fill="blue",   outline="blue")

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
          k = line[1:eq]
          v = line[eq+1:]
          if k.endswith(b".type"):
            values[k] = v
          else:
            values[k] = int(v)
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
        elif line in [b"%ok"]:
          global ok_count
          print(line)
          ok_count += 1
        elif line[0] == '#'[0]:
          print(line)
        elif re.match(b':tcs(\d+)[.]present=[01]', line):
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
