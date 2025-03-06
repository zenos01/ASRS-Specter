"""

320 x 240 - 33ms
640 x 480 - 42ms

Pi command:

gst-launch-1.0 libcamerasrc ! \
    'video/x-raw,width=640,height=480,format=NV12,framerate=30/1' ! \
    videoconvert ! \
    jpegenc quality=50 ! \
    rtpjpegpay ! \
    udpsink host=192.168.2.1 port=7777


Ground PC:

gst-launch-1.0 -v udpsrc port=7777 caps="application/x-rtp, encoding-name=JPEG, payload=26" ! rtpjpegdepay ! jpegdec ! videoconvert ! videoflip method=rotate-180 ! autovideosink sync=false

"""

import socket
import cv2
import numpy as np
import threading
import time
import json
import subprocess
from sdl2 import *
from sdl2 import joystick
import tkinter as tk

latest_telemetry = " "
last_telemetry_time = 0
telemetry_lock = threading.Lock()

# server
server_ip = '192.168.2.1'
video_port = 7777
telemetry_tcp_port = 9999
joystick_udp_port = 4444

# client
client_ip = '192.168.2.2'
client_port = joystick_udp_port

axes = {
    'roll': 0,
    'pitch': 1,
    'yaw': 2,
    'throttle': 3
}

output_min = 885
output_max = 2115
dead_band = 0.0

def handle_telemetry_client(conn, addr):
    global latest_telemetry, last_telemetry_time
    print(f"[INFO] Handling telemetry data from {addr}")
    buffer = ""
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                print(f"[INFO] Telemetry connection closed by {addr}.")
                with telemetry_lock:
                    latest_telemetry = "No telemetry data available."
                    last_telemetry_time = time.time()
                break
            buffer += data.decode("utf-8")
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                with telemetry_lock:
                    latest_telemetry = line.strip()
                    last_telemetry_time = time.time()
                print(f"[Telemetry Received from {addr}] {latest_telemetry}")
    except Exception as e:
        print(f"[ERROR] Error handling telemetry from {addr}: {e}")
        with telemetry_lock:
            latest_telemetry = "No telemetry data available."
            last_telemetry_time = time.time()
    finally:
        conn.close()
        print(f"[INFO] Closed telemetry connection with {addr}.")


def receive_telemetry_tcp(host='0.0.0.0', port=9999):
    global latest_telemetry, last_telemetry_time

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((host, port))
        server_socket.listen()
        print(f"[INFO] TCP telemetry server listening on {host}:{port}...")
    except Exception as e:
        print(f"[ERROR] Failed to bind TCP server on {host}:{port}: {e}")
        return

    while True:
        try:
            print("[INFO] Waiting for telemetry sender to connect...")
            conn, addr = server_socket.accept()
            print(f"[INFO] Connected by {addr}")
            client_thread = threading.Thread(target=handle_telemetry_client, args=(conn, addr), daemon=True)
            client_thread.start()
        except Exception as e:
            print(f"[ERROR] Telemetry server encountered an error: {e}")
            break

    server_socket.close()
    print("[INFO] TCP telemetry server shut down.")

def map_axis(value, in_min=-1.0, in_max=1.0, out_min=output_min, out_max=output_max):
    if abs(value) < dead_band:
        value = 0.0

    value = max(min(value, in_max), in_min)

    mapped = ((value - in_min) / (in_max - in_min)) * (out_max - out_min) + out_min
    return int(mapped)


def joystick_sender():
    if SDL_Init(SDL_INIT_JOYSTICK) < 0:
        print("[ERROR] Failed to initialize SDL.")
        return

    if joystick.SDL_NumJoysticks() < 1:
        print("[ERROR] No joystick found.")
        SDL_Quit()
        return

    js = joystick.SDL_JoystickOpen(0)
    if not js:
        print("[ERROR] Failed to open joystick.")
        SDL_Quit()
        return

    name = joystick.SDL_JoystickName(js).decode('utf-8')
    print(f"[INFO] Joystick name: {name}")

    num_buttons = joystick.SDL_JoystickNumButtons(js)
    print(f"[INFO] Number of buttons: {num_buttons}")

    udp_send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        while True:
            joystick.SDL_JoystickUpdate()
            axes_values = {}
            for axis_name, axis_idx in axes.items():
                axis_val = joystick.SDL_JoystickGetAxis(js, axis_idx) / 32767.0  # Normalize to [-1, 1]
                axes_values[axis_name] = map_axis(axis_val)

            buttons = {}
            for button_idx in range(num_buttons):
                button_state = joystick.SDL_JoystickGetButton(js, button_idx)
                buttons[str(button_idx)] = button_state  # 1 (pressed) or 0 (released)

            message_dict = {
                "axes": axes_values,
                "buttons": buttons
            }

            # Convert to JSON string
            message = json.dumps(message_dict)

            try:
                udp_send_socket.sendto(message.encode('utf-8'), (client_ip, client_port))
                # print(f"[Joystick Sent] {message} to {client_ip}:{client_port}")
            except Exception as e:
                print(f"[ERROR] Failed to send joystick data: {e}")

            time.sleep(0.05)  # Send at ~20Hz
    except KeyboardInterrupt:
        print("\n[INFO] Joystick sender interrupted by user.")
    finally:
        joystick.SDL_JoystickClose(js)
        SDL_Quit()
        udp_send_socket.close()
        print("[INFO] Joystick sender shut down.")

def run_overlay():
    overlay_window = create_overlay_window()
    overlay_window.mainloop()

def update_overlay(label):
    global latest_telemetry

    while True:
        label.config(text=latest_telemetry)
        time.sleep(0.5)

def create_overlay_window():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.7)
    root.geometry("+50+50")
    label = tk.Label(root, text="", font=("Helvetica", 16), fg="white", bg="black")
    label.pack()
    threading.Thread(target=update_overlay, args=(label,), daemon=True).start()
    return root

def main():
    global latest_telemetry, last_telemetry_time

    print("Starting UDP video receiver... Press 'q' to quit.")

    # telemetry thread
    telemetry_thread = threading.Thread(target=receive_telemetry_tcp, daemon=True)
    telemetry_thread.start()

    # joystick UDP thread
    joystick_thread = threading.Thread(target=joystick_sender, daemon=True)
    joystick_thread.start()

    overlay_thread = threading.Thread(target=run_overlay, daemon=True)
    overlay_thread.start()

    working_dir = r"C:\gstreamer\1.0\msvc_x86_64\bin"

    # Define the GStreamer pipeline command to receive the video stream.
    cmd = (
        'gst-launch-1.0 -v udpsrc port=7777 caps="application/x-rtp, encoding-name=JPEG, payload=26" ! '
        'rtpjpegdepay ! jpegdec ! videoconvert ! videoflip method=rotate-180 ! autovideosink sync=false'
    )

    # On Windows, use CREATE_NEW_PROCESS_GROUP to allow sending CTRL_BREAK_EVENT.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    # Launch the command in a shell with the specified working directory.
    process = subprocess.Popen(
        cmd,
        shell=True,
        cwd=working_dir,
        creationflags=creationflags
    )

    try:
        # Wait for the process to complete.
        process.wait()
    except KeyboardInterrupt:
        print("\nCtrl+C received. Terminating the GStreamer pipeline...")
        # Send CTRL_BREAK_EVENT to the process group so the process terminates gracefully.
        process.send_signal(signal.CTRL_BREAK_EVENT)
        process.wait()
    finally:
        print("GStreamer pipeline terminated.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting on user request (Ctrl+C).")
    finally:
        cv2.destroyAllWindows()
