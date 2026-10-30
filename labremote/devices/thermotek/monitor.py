from labremote.runtime.monitor import ParameterMonitor

PATHS = ('watchdog_json', 'temperature_setpoint', 'supply_temperature', 'ambient_temperature', 'coolant_flow')

class ThermotekMonitor(ParameterMonitor):
    def __init__(self,worker):super().__init__(worker,PATHS)
