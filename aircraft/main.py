import threading
import time
import serial
import os
from pymavlink import mavutil
import sys
import socket
import json
from com import communication
import subprocess
import signal

def stream_video(stop_event):
    """
    Stream UDP
    """

    cmd = (
        "gst-launch-1.0 libcamerasrc ! "
        "'video/x-raw,width=640,height=480,format=NV12,framerate=30/1' ! "
        "videoconvert ! "
        "jpegenc quality=50 ! "
        "rtpjpegpay ! "
        "udpsink host=192.168.2.1 port=7777"
    )

    process = subprocess.Popen(
        cmd,
        shell=True,
        preexec_fn=os.setsid
    )

    try:
        while process.poll() is None:
            if stop_event.is_set():
                print("[INFO] Stopping gstreamer")
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                break
            time.sleep(0.1)

    finally:
        process.wait()
        print("[INFO] Gstreamer pipeline terminated.")

def update_channel(stop_event):
    self_ip = "192.168.2.2"
    crsf_port = 4444

    com = communication(com_port='/dev/ttyUSB0')

    # Start the communication transmit thread
    thread = threading.Thread(target=com.transmit, daemon=True)
    thread.start()

    # Define PWM channel configurations
    disarm_channels = [
        1500, 1500, 885, 1500, 1000, 1500, 1500, 1500,
        1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500
    ]

    arm_channels = [
        1500, 1500, 885, 1500, 1800, 1500, 1500, 1500,
        1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500
    ]

    axis_to_channel = {
        'roll': 0,
        'pitch': 1,
        'yaw': 2,
        'throttle': 3
    }

    try:
        # Initialize the drone in a disarmed state
        com.update_data(disarm_channels)
        print("[STATUS] Disarm sequence on startup.")
        armed = False  # Flag to track arming state
        time.sleep(1)  # Brief pause to ensure commands are sent

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.bind((self_ip, crsf_port))
            print(f"[STATUS] UDP: Listening on {self_ip}:{crsf_port}")

            while not stop_event.is_set():
                try:
                    udp_socket.settimeout(1.0)  # 1-second timeout for receiving data
                    data, addr = udp_socket.recvfrom(1024)  # Buffer size of 1024 bytes

                    decoded_data = data.decode('utf-8')

                    recv_dict = json.loads(decoded_data)
                    print(f"[DEBUG] Received data from {addr}: {recv_dict}")

                    # Extract axes and buttons data
                    axes = recv_dict.get('axes', {})
                    buttons = recv_dict.get('buttons', {})

                    # Get the state of Button 0 (default to 0 if not present)
                    button_0_state = buttons.get('0', 0)

                    # Handle arming based on Button 0 state
                    if button_0_state == 1 and not armed:
                        # Button 0 pressed: Arm the drone
                        com.update_data(arm_channels)
                        print("[INFO] Arm command sent.")
                        armed = True
                        time.sleep(0.1)  # Short pause to prevent rapid toggling
                    elif button_0_state == 0 and armed:
                        # Button 0 released: Disarm the drone
                        com.update_data(disarm_channels)
                        print("[INFO] Disarm command sent.")
                        armed = False
                        time.sleep(0.1)  # Short pause to prevent rapid toggling

                    if armed:
                        # If armed, update PWM channels based on joystick axes
                        channels_pwm = arm_channels.copy()

                        for axis, channel in axis_to_channel.items():
                            axis_value = axes.get(axis, channels_pwm[channel])

                            if not isinstance(axis_value, int):
                                print(f"[WARNING] Invalid value for {axis}: {axis_value}. Skipping.")
                                continue

                            channels_pwm[channel] = axis_value

                        com.update_data(channels_pwm)
                        print(f"[INFO] Updated PWM channels: {channels_pwm}")
                    else:
                        # If disarmed, ensure PWM channels are set to disarmed state
                        com.update_data(disarm_channels)
                        print("[INFO] Drone is disarmed. PWM channels set to disarm.")

                except socket.timeout:

                    current_time = time.time()
                    time_since_last = current_time - last_received_time

                    if time_since_last > 2.0 and armed:
                        com.update_data(disarm_channels)
                        print("[WARNING] No command packets received for 2 seconds. Disarming drone.")
                        armed = False

                except json.JSONDecodeError:
                    print(f"[ERROR] Received invalid JSON data from {addr}: {data}")
                except Exception as e:
                    print(f"[ERROR] {e}")

    except KeyboardInterrupt:
        print("\n[INFO] Stopping PWM channel updates.")
        com.join()
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        # Ensure the drone is disarmed on exit
        com.update_data(disarm_channels)
        print("[INFO] Disarmed channels. Exiting PWM channel thread.")


def mavlink_telem(stop_event):
    """
    UART mavlink data handler
    """

    target_ip = "192.168.2.1"
    tcp_port = 9999

    serial_port = '/dev/ttyUSB1'
    baud_rate = 115200

    try:
        master = mavutil.mavlink_connection(serial_port, baud=baud_rate)
        print("[INFO] Mavlink connection: Successful ")
    except Exception as e:
        print(f"[ERROR] Mavlink comm. failed: {e}")
        return

    while not stop_event.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)  # Increased timeout for connection attempts
                print(f"[INFO] Attempting to connect to {target_ip}:{tcp_port}...")
                try:
                    s.connect((target_ip, tcp_port))
                    print("[INFO] TCP connected. Sending telemetry.")
                except socket.timeout:
                    print("[ERROR] Connection timed out. Retrying in 5 seconds...")
                    time.sleep(5)
                    continue
                except Exception as e:
                    print(f"[ERROR] Failed to connect: {e}. Retrying in 5 seconds...")
                    time.sleep(5)
                    continue

                while not stop_event.is_set():
                    try:
                        msg = master.recv_match(blocking=False)

                        if not msg:
                            time.sleep(0.1)
                            continue

                        msg_type = msg.get_type()
                        if msg_type == 'SYS_STATUS':
                            msg_data = msg.to_dict()

                            batV = msg_data.get('voltage_battery', 0) / 1000.0
                            batI = msg_data.get('current_battery', 0) / 100.0

                            telem_str = f"{batV:.2f} V {batI:.2f} A\n"
                            print(f"[Mavlink] {telem_str.strip()}")

                            try:
                                s.sendall(telem_str.encode("utf-8"))
                                print(f"Send: {telem_str.strip()}")
                            except Exception as e:
                                print(f"[ERROR] Telem. send error: {e}. Reconnecting...")
                                break  # Exit the inner loop to attempt reconnection

                        time.sleep(0.1)

                    except Exception as e:
                        print(f"[ERROR] Mavlink telemetry error: {e}. Reconnecting...")
                        break  # Exit the inner loop to attempt reconnection

        except KeyboardInterrupt:
            print("\n[INFO] Stopping Mavlink Telemetry.")
            break
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

    print("[INFO] Mavlink telemetry thread exiting.")



if __name__ == "__main__":
    stop_event = threading.Event()

    # Initialize threads
    video_thread = threading.Thread(target=stream_video, args=(stop_event,), daemon=True)
    pwm_thread   = threading.Thread(target=update_channel, args=(stop_event,), daemon=True)
    telem_thread = threading.Thread(target=mavlink_telem, args=(stop_event,), daemon=True)

    # Start threads
    video_thread.start()
    pwm_thread.start()
    telem_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Exiting main program.")
        stop_event.set()
        pwm_thread.join()
        telem_thread.join()
        video_thread.join()
    finally:
        print("[INFO] Program terminated.")