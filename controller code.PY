import socket, struct, pygame, time

# --- NETWORK ---
PACK_FORMAT  = '6B6B'
TARGET_IP    = "192.168.1.50"
TARGET_PORT  = 9090
DEADZONE_VAL = 0.2

# --- PACKET LAYOUT (must match updateMotors() on the STM32) ---
# bytes 0-3 : PWM  TL, TR, BR, BL
# byte  4   : PWM  UP1
# byte  5   : PWM  UP2
# bytes 6-9 : DIR  TL, TR, BR, BL
# byte  10  : DIR  shared by UP1 and UP2
# byte  11  : heartbeat (alternates 0/1 every packet)
MOTOR_NAMES = ["TL", "TR", "BR", "BL", "UP1", "UP2"]
N_MOTORS    = len(MOTOR_NAMES)

FWD_BIT = 0                 # value of FORWARD in Motors.h (check it)
REV_BIT = 1 - FWD_BIT

# --- TEST MODE CONFIG ---
TEST_PWM = 255              # fixed power during single-bilge test (0-255)

# --- BUTTON INDICES (change using the finder script) ---111112fxxzz
BTN_TEST_TOGGLE = 4         # Share (guess)
BTN_TEST_STOP   = 2         # Square (guess)
BTN_DPAD_UP     = 11
BTN_DPAD_DOWN   = 12
BTN_DPAD_LEFT   = 13
BTN_DPAD_RIGHT  = 14
BTN_FULL_POWER  = 0         # Cross
BTN_PRECISION   = 1         # Circle

# --- PACKET PRINTING ---
PRINT_PACKETS   = True
PRINT_ON_CHANGE = True      # True: only when PWM/dir change (heartbeat ignored)

def deadzone(v):
    return v if abs(v) > DEADZONE_VAL else 0.0

def dbit(v):
    """Dir bit for a signed value. A stopped motor always gets 0."""
    if v == 0:
        return 0
    return REV_BIT if v < 0 else FWD_BIT

def build_packet(m, limit, hb):
    """m = 6 signed values in PWM-slot order [TL, TR, BR, BL, UP1, UP2]."""
    m = [max(-limit, min(limit, int(v))) for v in m]
    pwms = [abs(v) for v in m]                       # bytes 0-5
    dirs = [dbit(v) for v in m[:4]]                  # bytes 6-9
    vert = [v for v in m[4:] if v != 0]              # UP1/UP2 share one dir bit
    dirs.append(dbit(vert[0]) if vert else 0)        # byte 10
    dirs.append(hb)                                  # byte 11
    return struct.pack(PACK_FORMAT, *pwms, *dirs)

_last_shown = None
def show_packet(packet):
    global _last_shown
    if not PRINT_PACKETS:
        return
    vals = struct.unpack(PACK_FORMAT, packet)
    pwms, dirs = vals[:6], vals[6:]
    key = (pwms, dirs[:5])                           # ignore heartbeat
    if PRINT_ON_CHANGE and key == _last_shown:
        return
    _last_shown = key
    print(f"[PKT] {len(packet)} bytes | hex: {packet.hex(' ')}")
    for i, name in enumerate(MOTOR_NAMES):
        d = dirs[i] if i < 4 else dirs[4]
        note = "  (shared vertical dir)" if i >= 4 else ""
        print(f"   {name:>4}: pwm={pwms[i]:3d} dir={d}{note}")
    print(f"   heartbeat={dirs[5]}")

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
client.settimeout(0.1)

Max_pwm = 0

prev_btn = {}
def edge(btn):
    cur = controller.get_button(btn)
    was = prev_btn.get(btn, 0)
    prev_btn[btn] = cur
    return bool(cur and not was)

# Test mode state
test_mode = True
test_idx = 0
test_dir = 0                # latched: +1 forward, -1 reverse, 0 stopped
DIR_LABEL = {1: f"FORWARD (dir={FWD_BIT})", -1: f"REVERSE (dir={REV_BIT})", 0: "STOPPED"}

def report():
    print(f"[TEST] {MOTOR_NAMES[test_idx]} (slot {test_idx}) -> {DIR_LABEL[test_dir]}")

# --- HARDWARE WARM-UP ---
print("Clearing ghost inputs... hold sticks neutral.")
for _ in range(15):
    pygame.event.pump()
    time.sleep(0.05)

print("System Ready. Press Button A/0 to Arm. Test mode toggle = button", BTN_TEST_TOGGLE)

# --- MAIN LOOP ---
heartbeat = 0
try:
    while True:
        pygame.event.pump()

        e_toggle = edge(BTN_TEST_TOGGLE)
        e_stop   = edge(BTN_TEST_STOP)
        e_up     = edge(BTN_DPAD_UP)
        e_down   = edge(BTN_DPAD_DOWN)
        e_left   = edge(BTN_DPAD_LEFT)
        e_right  = edge(BTN_DPAD_RIGHT)

        if e_toggle:
            test_mode = not test_mode
            test_dir = 0
            if test_mode:
                print(f"\n=== TEST MODE ON (power {TEST_PWM}) ===")
                print("LEFT/RIGHT = change bilge (stops motor) | UP = forward | "
                      "DOWN = reverse | same again or STOP button = stop")
                report()
            else:
                print("\n=== TEST MODE OFF ===")

        if test_mode:
            # ---------- SINGLE-BILGE TEST (latched) ----------
            if e_right or e_left:
                test_idx = (test_idx + (1 if e_right else -1)) % N_MOTORS
                test_dir = 0
                report()
            elif e_up:
                test_dir = 0 if test_dir == 1 else 1
                report()
            elif e_down:
                test_dir = 0 if test_dir == -1 else -1
                report()
            elif e_stop and test_dir != 0:
                test_dir = 0
                report()

            # Every slot is 0 except the one under test
            m = [0] * N_MOTORS
            m[test_idx] = test_dir * TEST_PWM
            limit = 255

        else:
            # ---------- NORMAL DRIVING ----------
            if controller.get_button(BTN_FULL_POWER):
                Max_pwm = 255
            elif controller.get_button(BTN_PRECISION):
                Max_pwm = 150

            ax = int(deadzone( controller.get_axis(0)) * Max_pwm)
            ay = int(deadzone(-controller.get_axis(1)) * Max_pwm)
            yw = int(deadzone( controller.get_axis(2)) * Max_pwm)
            az = int(deadzone( controller.get_axis(3)) * -Max_pwm)

            m = [
                ax + ay + yw,   # TL
                ax - ay + yw,   # TR
                ax + ay - yw,   # BR
                ax - ay - yw,   # BL
                az,             # UP1
                az,             # UP2 (same value: they share one dir bit)
            ]
            limit = Max_pwm

        packet = build_packet(m, limit, heartbeat)
        show_packet(packet)
        heartbeat ^= 1

        try:
            client.sendto(packet, (TARGET_IP, TARGET_PORT))
        except OSError:
            print("Network unreachable. Check connection to ROV.")

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nShutting down. Sending stop signal...")
    stop_packet = struct.pack(PACK_FORMAT, 0,0,0,0,0,0, 0,0,0,0,0,0)
    client.sendto(stop_packet, (TARGET_IP, TARGET_PORT))
    pygame.quit()