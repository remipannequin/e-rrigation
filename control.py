#!/usr/bin/python3

import json
import threading
import time
import subprocess

from Phidget22.Phidget import *
from Phidget22.Devices.DigitalOutput import DigitalOutput
from Phidget22.Devices.VoltageInput import VoltageInput
from Phidget22.Devices.TemperatureSensor import TemperatureSensor
from influxdb import InfluxDBClient

# dictionary that give names according to ids
NAMES = {"369507//1": "pump",
         "369507//2": "ev1",
         "369507//3": "ev2",
         "107839//3": "pot2_1",
         "107839//4": "pot2_2",
         "107839//5": "pot1_1",
         "107839//7": "main_flow",
         "285105//0": "pot1",
         "285105//1": "pot2",
         "285105//2": "water_reserve",
         "285105//4": "ambiant",
         "167.121": "pot1",
         "81.174": "pot2"}


class ActuatorController:

    def __init__(self):
        self.tags = list()
        self.pump = DigitalOutput()
        self.pump.setDeviceSerialNumber(369507)
        self.pump.setChannel(1)
        self.tags.append("369507//1")
        self.ev = list()
        self.ev.append(DigitalOutput())
        self.ev[0].setDeviceSerialNumber(369507)
        self.ev[0].setChannel(2)
        self.ev.append(DigitalOutput())
        self.ev[1].setDeviceSerialNumber(369507)
        self.ev[1].setChannel(3)
        self.tags.append("369507//2")
        self.tags.append("369507//3")

        self.names = ("pump", "valve", "valve")

        self.pump.openWaitForAttachment(2000)
        self.ev[0].openWaitForAttachment(2000)
        self.ev[1].openWaitForAttachment(2000)

    def stop(self):
        self.ev[0].setState(False)
        self.ev[1].setState(False)
        self.pump.setState(False)

    def start(self, dev, duration = 0):
        def _set(dev, state):
            if not dev.getState() == state:
                dev.setState(state)
            
        _set(self.pump, True)
        _set(self.ev[dev], True)
        if duration:
            time.sleep(duration)
            _set(self.pump, False)
            _set(self.ev[dev], False)

    def record_state(self, tsdb, state):
        s = self.state()
        points = list()
        for (v, n, tag) in zip(s, self.names, self.tags):
            f = {n: v}
            points.append({"measurement": "actuators",
                     "tags" : {"id": tag,
                               "name": NAMES[tag]},
                     "fields": f})
            state.update(f, tag=tag)
        tsdb.write_points(points)

    def state(self):
        def _get(dev):
            if dev.getState():
                return 1
            return 0
        return (_get(self.pump), _get(self.ev[0]), _get(self.ev[1]))


class State:
    """The current values of the elements of the system.
    """
    
    NB_PART = 2

    def __init__(self):
        self.values = list()
        while len(self.values) < State.NB_PART + 1:
            self.values.append(dict())
    
    def part(tag):
        """Get the part of the system corresponding to this tag/id"""
        # TODO
        return 0

    def update(self, fields, tag=None):
        """Update the state with the dictionary fields"""
        if tag:
            p = State.part(tag)
        else:
            p = 0
        for (k, v) in fields.items():
            self.values[p][k] = v


class SkyMotesSensor:
    """Sensor component that get data from the Sky / TelosB motes"""
   
    NODE_ID = 4
    LIGHT1 = 22
    LIGHT2 = 23
    TEMPERATURE = 24
    HUMIDITY = 25

    def _process_data(values):
        """Process the data packet from a sky mote and return it."""
        def _temperature(values):
            return -39.6 + 0.01 * values[SkyMotesSensor.TEMPERATURE]

        def _humidity(values):
            v = -4.0 + 405.0 * values[SkyMotesSensor.HUMIDITY] / 10000.0
            if(v > 100):
                return 100
            return v

        def _light1(values):
            return 10.0 * values[SkyMotesSensor.LIGHT1] / 7.0

        def _light2(values):
            return 46.0 * values[SkyMotesSensor.LIGHT2] / 10.0
    
        def mapNodeID(values):
            nodeID = values[SkyMotesSensor.NODE_ID]
            return "{}.{}".format(nodeID & 0xff, (nodeID >> 8) & 0xff)
        
        return (mapNodeID(values), 
                _temperature(values),
                _humidity(values),
                _light1(values),
                _light2(values))
   

    def __init__(self):
        self.kill = False


    def start(self, tsdb, state):
        """Listen to event on the serial port using the serialdump utility. 
        Loops until self.kill becomes true."""
        self.proc = subprocess.Popen(['tools/serialdump', '-b115200', '/dev/ttyUSB0', ],
                                      stdout=subprocess.PIPE,
                                      stdin=subprocess.PIPE)

        while not self.kill:
            line = self.proc.stdout.readline()
            if not line:
                break
            #the real code does filtering here
            # print("test:", line.rstrip())
            line = line.replace(b'\x00', b'')
            
            values = [int(s) for s in line.split()]
            if len(values) >= 25:
                (nodeid, temp, humid, l_vis, l_vis_ir) = SkyMotesSensor._process_data(values)
                fields = {"temperature": temp,
                          "air_humidity": humid,
                          "light_visible": l_vis,
                          "light_visible_ir": l_vis_ir}
                point = {"measurement": "sky",
                        "tags" : {"id": nodeid,
                                  "name": NAMES[nodeid]},
                        "fields": fields}

                tsdb.write_points([point])
                state.update(fields, tag=nodeid)



class MoistureSensor:

    V_MAX = [4.30, 4.30, 4.30]

    def __init__(self):
        self.tags = list()
        self.sensor = list()
        self.sensor.append(VoltageInput())
        self.sensor[0].setDeviceSerialNumber(107839)
        self.sensor[0].setChannel(5)
        self.tags.append("107839//5")
        self.sensor[0].openWaitForAttachment(5000)

        self.sensor.append(VoltageInput())
        self.sensor[1].setDeviceSerialNumber(107839)
        self.sensor[1].setChannel(4)
        self.tags.append("107839//4")
        self.sensor[1].openWaitForAttachment(5000)

        self.sensor.append(VoltageInput())
        self.sensor[2].setDeviceSerialNumber(107839)
        self.sensor[2].setChannel(3)
        self.tags.append("107839//3")
        self.sensor[2].openWaitForAttachment(5000)


    def normalize(voltages):
        """Normalize values"""
        return [ v / vmax for (v, vmax) in zip(voltages, MoistureSensor.V_MAX)]


    def raw_value(self):
        """Get the raw data (voltage) from the board."""
        return [s.getVoltage() for s in self.sensor]
    

    def run(self, tsdb, state):
        """Get the values, process them, update the state variable and write in the tsdb."""
        raw_v = self.raw_value()
        normalized_v = MoistureSensor.normalize(raw_v)
        points = list()
        for (v, v_, tag) in zip(raw_v, normalized_v, self.tags):        
            f = {"voltage": v,
                "normalized_voltage": v_}
            points.append({"measurement": "soil_moisture",
                           "tags": {"id": tag,
                                    "name": NAMES[tag]},
                           "fields": f})
            state.update(f, tag)
        tsdb.write_points(points)
        


class FlowSensor:
    CALLIB = 12.84

    def __init__(self):
        self.main = VoltageInput()
        self.main.setDeviceSerialNumber(107839)
        self.main.setChannel(7)
        self.main.openWaitForAttachment(5000)
        self.tag = "107839//7"
        self.history = list()

    def main_flow(self):
        now = time.time()
        v = self.main.getVoltage()
        c = v * 40 / 9
        f = ((c - 4) / 16) * FlowSensor.CALLIB
        self.history.append((f, now))
        return (f, v)

    def reset_total(self):
        self.history = list()

    def total(self):
        result = 0.
        if len(self.history < 1):
            return 0.
        for ((f0, t0), (f1, t1)) in zip(self.history[:-1], self.history[1:]):
            result += (f0+f1)/2*(t1-t0)
        return result
    
    def run(self, tsdb, state):
        """Get the values, process them, update the state variable and write in the tsdb."""
        (v, v_) = self.main_flow()
        f = {"flow": v,
             "flow_row": v_}
        p = {"measurement": "flow",
             "tags" : {"id": self.tag,
                       "name": NAMES[self.tag]},
             "fields": f}
        state.update(f)
        tsdb.write_points([p])


class ThermoCoupleSensor:
    """Read thermocouple sensors"""

    def __init__(self):
        self.tc = list()
        self.tags = list()

        self.tc.append(TemperatureSensor())
        self.tc[0].setDeviceSerialNumber(285105)
        self.tc[0].setChannel(0)
        self.tc[0].openWaitForAttachment(5000)
        self.tags.append("285105//0")

        self.tc.append(TemperatureSensor())
        self.tc[1].setDeviceSerialNumber(285105)
        self.tc[1].setChannel(1)
        self.tc[1].openWaitForAttachment(5000)
        self.tags.append("285105//1")

        self.tc.append(TemperatureSensor())
        self.tc[2].setDeviceSerialNumber(285105)
        self.tc[2].setChannel(2)
        self.tc[2].openWaitForAttachment(5000)
        self.tags.append("285105//2")

        self.tc.append(TemperatureSensor())
        self.tc[3].setDeviceSerialNumber(285105)
        self.tc[3].setChannel(4)
        self.tc[3].openWaitForAttachment(5000)
        self.tags.append("285105//4")

    
    def run(self, tsdb, state):
        """Get the values, process them, update the state variable and write in the tsdb."""
        
        points = list()
        temps = [tc.getTemperature() for tc in self.tc]
        for (temp, tag) in zip(temps, self.tags):        
            f = {"temperature": temp}
            points.append({"measurement": "thermocouples",
                           "tags": {"id": tag,
                                    "name": NAMES[tag]},
                           "fields": f})
            state.update(f, tag)
        tsdb.write_points(points)
        


if __name__ == "__main__":
    act = ActuatorController()
    mainflow_sensor = FlowSensor()
    moist_sensor = MoistureSensor()
    sky_sensor = SkyMotesSensor()
    tc_sensor = ThermoCoupleSensor()
    # Read credentials from a file
    with open('./influxdb-credentials.json', 'r') as f:
        cred = json.load(f)
    if cred and 'username' in cred and 'password' in cred:
        tsdb = InfluxDBClient(host="localhost", port=8086, username=cred['username'], password=cred['password'])
    else:
        tsdb = InfluxDBClient(host="localhost", port=8086)
    tsdb.switch_database('irrigation')
    print("logged into the TSDB")
    
    state = State()
    
    kill = False

    def read_sync(tsdb, state):
        while not kill:
            mainflow_sensor.run(tsdb, state)
            moist_sensor.run(tsdb, state)
            act.record_state(tsdb, state)
            tc_sensor.run(tsdb, state)
            time.sleep(5)

    read_sync = threading.Thread(target=read_sync, args=(tsdb, state))
    read_sync.start()

    read_sky = threading.Thread(target=sky_sensor.start, args=(tsdb, state))
    read_sky.start()

    act.stop()
    exit()
    
    
    
    
    
    
    while True:
        act.start(0, 30)
        time.sleep(30)
        act.start(1, 30)
        time.sleep(30)
