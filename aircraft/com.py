import serial
import time
from utils import us_to_ticks, ticks_to_us, pack_channels, crc_transmit


class communication():

    def __init__(self, com_port):
        self.ser = serial.Serial(com_port, baudrate=416666, timeout=0)
        self.payload = []
        self.crc = []
        self.message = []
        self.t1 = 0
        self.received_bytes = None

    def transmit(self):
        self.t1 = time.time()
        read = False
        while True:
            t2 = time.time()
            dt = (t2-self.t1)*1000.0  # delta t in milliseconds

            # handle read buffer after telemetry is received (i.e. after 3ms for 150Hz(:6.67ms))
            if 3 < dt and not read:
                waiting = self.ser.in_waiting
                data = self.ser.read(waiting)
                if data != b'':
                    self.received_bytes = data
                read = True

            # write new frame
            if dt >= 6.666667:
                self.t1 = time.time()
                read = False
                self.ser.write(bytearray(self.message))

    def decode_telemetry(self):
        while True:
            if not self.received_bytes or len(self.received_bytes) < 26:
                #print("Invalid or incomplete data received.")
                time.sleep(0.0001)
                continue

            rcv_list = list(self.received_bytes)
            possible_telemetry_indices = [i for i, x in enumerate(rcv_list) if x == 234]  # 234 = b'\xea'

            if not possible_telemetry_indices:
                time.sleep(0.0001)
                continue

            for i in possible_telemetry_indices:
                telemetry_list = rcv_list[i:]
                
                if len(telemetry_list) < 3:
                    print(f"Telemetry list is too short: {telemetry_list}")
                    continue
                
                tel_type = telemetry_list[2]
                
                if tel_type == 8:  # 0x08: battery sensor
                    if len(telemetry_list) < 51:  # Ensure enough bytes for processing
                        print(f"Incomplete telemetry data for type 8: {telemetry_list}")
                        continue
                    
                    voltage = int.from_bytes(bytearray(telemetry_list[3:51]), "big")
                    print(f"Voltage: {voltage}")
            
            time.sleep(0.0001)  # Prevent excessive CPU usage

    def update_data(self, channels_pwm):
        # convert pwm values to rc values
        channels_rc = us_to_ticks(channels_pwm)

        # pack 16 channels to 22 bytes
        packed_channel = pack_channels(channels_rc)

        # calculate crc
        crc = crc_transmit([0x16], packed_channel)
        crc = [int(crc, 16)]

        self.payload = packed_channel
        self.crc = crc

