import socket, struct, pygame, time 
from collections import deque

# --- CONFIGURATION ---
PACK_FORMAT = '6B6B'
DEADZONE_VAL = 0.2      
SMOOTH_LEN   = 5        
CLEAN_THRESH = 0.05    
TARGET_IP    = "192.168.1.50"
TARGET_PORT  = 9090
AXIS_L2  = 2 
AXIS_R2  = 5
def deadzone(v):
    return v if abs(v) > DEADZONE_VAL else 0.0

def smooth(buf, v):
    buf.append(v)
    return sum(buf) / len(buf)

def clean(v):
    return 0.0 if abs(v) < CLEAN_THRESH else v

# --- INITIALIZATION ---
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick detected!")
    exit()

controller = pygame.joystick.Joystick(0)
controller.init()
print(f"Controller Initialized: {controller.get_name()}")

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Using a timeout so the script doesn't hang forever on network issues
client.settimeout(0.1) 

# Buffers for smoothing (initialized at 0.0)
bufs = [deque([0.0] * SMOOTH_LEN, maxlen=SMOOTH_LEN) for _ in range(4)]

# Start at 0 for safety. Must press Button 0 or 1 to "Arm" the ROV.
Max_pwm = 0 

# --- HARDWARE WARM-UP ---
# This clears the "ghost" -1.0 values that Pygame often reads at launch
print("Clearing ghost inputs... hold sticks neutral.")
for _ in range(15):
    pygame.event.pump()
    time.sleep(0.05)

print("System Ready. Press Button A/0 to Arm.")

# --- MAIN LOOP ---
gripper=0
try:
    while True:
        pygame.event.pump()

        # Arming / Speed modes
        if controller.get_button(0):
            Max_pwm = 255 # Full Power
        elif controller.get_button(1):
            Max_pwm = 150 # Precision Mode
        
        # if controller.get_button(4) :
        #     gripper = 0 # Open
        #     print("open")
        # elif controller.get_button(5) :
        #     gripper = 1 # Close
        #     print("closed")

        # Read axes using standard Linux mapping:
        # 0: Left Stick X, 1: Left Stick Y
        # 2: Left Trigger (SKIPPED), 3: Right Stick X, 4: Right Stick Y
        raw_ax = controller.get_axis(0)
        raw_ay = -controller.get_axis(1) # Inverted Y for intuitive flight
        raw_yw = controller.get_axis(2)
        raw_az = controller.get_axis(3)

        # Apply processing pipeline
        ax = int(clean(smooth(bufs[0], deadzone(raw_ax))) * Max_pwm)
        ay = int(clean(smooth(bufs[1], deadzone(raw_ay))) * Max_pwm)
        yw = int(clean(smooth(bufs[2], deadzone(raw_yw))) * Max_pwm)
        az = int(clean(smooth(bufs[3], deadzone(raw_az))) * -Max_pwm)

        # Motor mixing (Mecanum/Vector Drive)
        m = [
            ax + ay + yw,   # TL
            ax - ay + yw,   # TR
            ax + ay - yw,   # BR
            
            ax - ay - yw,   # BL
            az,       # UP2
        ]

        pwms = []
        dirs = []

        for v in m:
            # Clamp to Max_pwm range
            v = max(-Max_pwm, min(Max_pwm, v))
            if v >= 0:
                dirs.append(1)
                pwms.append(int(v))
            else:
                dirs.append(0)
                pwms.append(int(-v))

        # Pack and Send
        pwms.append(0)
        dirs.append(gripper) # Add gripper state to the end of the directions
        packet = struct.pack(PACK_FORMAT, *pwms, *dirs)
        
        try:
            client.sendto(packet, (TARGET_IP, TARGET_PORT))
            if Max_pwm > 0: # Only clutter console if armed
                print(f"PWMs: {pwms} | Power: {Max_pwm}")
        except OSError:
            print("Network unreachable. Check connection to ROV.")

        time.sleep(0.1) # ~20Hz update rate

except KeyboardInterrupt:
    print("\nShutting down. Sending stop signal...")
    # Send one last "All Stop" packet
    stop_packet = struct.pack(PACK_FORMAT, 0,0,0,0,0,0, 0,0,0,0,0,0)
    client.sendto(stop_packet, (TARGET_IP, TARGET_PORT))
    pygame.quit()
