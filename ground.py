import socket
import cv2
import numpy as np
import threading
import time
import json
from sdl2 import *
from sdl2 import joystick


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


def draw_telemetry(canvas, telemetry_text, pos_x, pos_y, font_scale, thickness, font):


   # text OSD
   cv2.putText(canvas, telemetry_text, (pos_x, pos_y),
               font, font_scale,
               (0, 255, 0), thickness, cv2.LINE_AA)


def draw_crosshair(canvas, center_x, center_y, new_width, crosshair_length_ratio=0.02, crosshair_thickness_ratio=1/1000.0, dot_radius_ratio=0.001, gap_size=10, crosshair_alpha=0.7):


   crosshair_length = int(new_width * crosshair_length_ratio)  # 2% of frame width
   crosshair_thickness = max(int(new_width * crosshair_thickness_ratio), 1)
   crosshair_color = (0, 255, 0)  # White color
   dot_radius = max(int(new_width * dot_radius_ratio), 2)
   gap = dot_radius + gap_size


   crosshair_overlay = canvas.copy()


   # vertical lines
   cv2.line(crosshair_overlay, (center_x, center_y - crosshair_length),
            (center_x, center_y - gap), crosshair_color, crosshair_thickness)
   cv2.line(crosshair_overlay, (center_x, center_y + gap),
            (center_x, center_y + crosshair_length), crosshair_color, crosshair_thickness)


   # horizontal lines
   cv2.line(crosshair_overlay, (center_x - crosshair_length, center_y),
            (center_x - gap, center_y), crosshair_color, crosshair_thickness)
   cv2.line(crosshair_overlay, (center_x + gap, center_y),
            (center_x + crosshair_length, center_y), crosshair_color, crosshair_thickness)


   # center dot
   cv2.circle(crosshair_overlay, (center_x, center_y), dot_radius, crosshair_color, -1)


   cv2.addWeighted(crosshair_overlay, crosshair_alpha, canvas, 1 - crosshair_alpha, 0, canvas)


def display_frame(canvas, telemetry_text, new_width, new_height, x_offset, y_offset):


   # telemetry text
   pos_x = x_offset + int(new_width * 0.35)
   pos_y = y_offset + int(new_height * 0.05)


   font_scale = max(new_width / 2000.0, 0.5)
   thickness = max(int(new_width / 2000.0), 1)
   font = cv2.FONT_HERSHEY_SIMPLEX


   draw_telemetry(canvas, telemetry_text, pos_x, pos_y, font_scale, thickness, font)
  
   # crosshair center
   center_x = x_offset + new_width // 2
   center_y = y_offset + new_height // 2


   draw_crosshair(canvas, center_x, center_y, new_width)


def display_no_data(window_width=800, window_height=600):


   canvas = np.zeros((window_height, window_width, 3), dtype=np.uint8)
   text = "Video Offline"
   font = cv2.FONT_HERSHEY_SIMPLEX
   font_scale = 0.5
   thickness = 1
   (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, thickness)
   text_x = (canvas.shape[1] - text_width) // 2
   text_y = (canvas.shape[0] + text_height) // 2
   cv2.putText(canvas, text, (text_x, text_y), font, font_scale, (0, 255, 0), thickness, cv2.LINE_AA)
   return canvas


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
               #print(f"[Joystick Sent] {message} to {client_ip}:{client_port}")
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


def main():
   global latest_telemetry, last_telemetry_time


   print("Starting UDP video receiver... Press 'q' to quit.")


   # telemetry thread
   telemetry_thread = threading.Thread(target=receive_telemetry_tcp, daemon=True)
   telemetry_thread.start()


   # joystick UDP thread
   joystick_thread = threading.Thread(target=joystick_sender, daemon=True)
   joystick_thread.start()


   try:
       receiver_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
       receiver_socket.bind((server_ip, video_port))
       receiver_socket.settimeout(1)  # Set timeout to 1 second
       print(f"[INFO] UDP video receiver bound to {server_ip}:{video_port}, waiting for incoming video data...")
   except Exception as e:
       print(f"[ERROR] Failed to create or bind UDP video socket: {e}")
       return


   window_name = "UDP Video Stream with Telemetry"
   cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
   cv2.resizeWindow(window_name, 800, 600)


   sharpening_kernel = np.array([[0, -1, 0],
                                 [-1, 5, -1],
                                 [0, -1, 0]])


   while True:
       frame = None
       try:
           data, addr = receiver_socket.recvfrom(65536)
           frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
           if frame is None:
               print("[Warning] Decoding failed or received empty frame.")


       except socket.timeout:
           pass
       except Exception as e:
           print(f"[ERROR] Receiving UDP video data failed: {e}")


       if frame is not None:
           sharpened_frame = cv2.filter2D(frame, -1, sharpening_kernel)


           frame_height, frame_width = sharpened_frame.shape[:2]


           window_rect = cv2.getWindowImageRect(window_name)
           window_width = window_rect[2] if window_rect[2] > 0 else 800
           window_height = window_rect[3] if window_rect[3] > 0 else 600


           if frame_height == 0 or window_height == 0:
               print("[ERROR] Invalid frame or window height.")
               continue


           aspect_ratio = frame_width / frame_height
           window_aspect_ratio = window_width / window_height


           if window_aspect_ratio > aspect_ratio:
               new_height = window_height
               new_width = int(window_height * aspect_ratio)
           else:
               new_width = window_width
               new_height = int(window_width / aspect_ratio)


           resized_frame = cv2.resize(sharpened_frame, (new_width, new_height))


           canvas = np.zeros((window_height, window_width, 3), dtype=np.uint8)
           x_offset = (window_width - new_width) // 2
           y_offset = (window_height - new_height) // 2
           canvas[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = resized_frame


           with telemetry_lock:
               # Since telemetry_timeout is removed, always display the latest telemetry
               telemetry_text = latest_telemetry


           # Display frame with overlays
           display_frame(canvas, telemetry_text, new_width, new_height, x_offset, y_offset)


           cv2.imshow(window_name, canvas)
       else:
           # No frame received; display "No video data" with telemetry
           window_width, window_height = 800, 600  # Default sizes
           canvas = display_no_data(window_width, window_height)


           with telemetry_lock:
               telemetry_text = latest_telemetry


           # Telemetry Text Settings
           pos_x = 50
           pos_y = 50
           font_scale = 0.7
           thickness = 2
           font = cv2.FONT_HERSHEY_SIMPLEX


           draw_telemetry(canvas, telemetry_text, pos_x, pos_y, font_scale, thickness, font)


           cv2.imshow(window_name, canvas)


       # Handle user input
       key = cv2.waitKey(1) & 0xFF
       if key == ord('q'):
           print("User requested exit.")
           break


   receiver_socket.close()
   cv2.destroyAllWindows()
   print("[INFO] Receiver shut down.")


if __name__ == "__main__":
   try:
       main()
   except KeyboardInterrupt:
       print("\nExiting on user request (Ctrl+C).")
   finally:
       cv2.destroyAllWindows()






