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

# --- CONTROLLER MAPPING ---
# PS4 / PS5 "Wireless Controller" on Ubuntu 24 (hid-playstation driver, SDL 2.30)
#   Buttons: 0 Cross, 1 Circle, 2 Triangle, 3 Square, 4 L1, 5 R1, 6 L2, 7 R2,
#            8 Share/Create, 9 Options, 10 PS, 11 L3, 12 R3
#   D-pad is a HAT (not buttons) -> read with get_hat(0)
#   Axes: 0 LX, 1 LY, 2 L2 trigger, 3 RX, 4 RY, 5 R2 trigger
BTN_TEST_TOGGLE = 8         # Share / Create
BTN_TEST_STOP   = 3         # Square
BTN_FULL_POWER  = 0         # Cross
BTN_PRECISION   = 1         # Circle

AXIS_SURGE_SWAY_X = 0       # left stick X
AXIS_SURGE_SWAY_Y = 1       # left stick Y
AXIS_YAW          = 3       # right stick X
AXIS_HEAVE        = 4       # right stick Y

# Fallback D-pad buttons, only used if the controller reports NO hat
# (some older drivers expose the D-pad as buttons 11-14).
FALLBACK_DPAD_BTNS = {"up": 11, "down": 12, "left": 13, "right": 14}

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
N_BUTTONS = controller.get_numbuttons()
N_AXES    = controller.get_numaxes()
N_HATS    = controller.get_numhats()
print(f"Controller Initialized: {controller.get_name()}")
print(f"  buttons={N_BUTTONS} axes={N_AXES} hats={N_HATS}")

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client.settimeout(0.1)

def button(btn):
    """Safe button read: returns 0 instead of crashing on a bad index."""
    if btn is None or btn < 0 or btn >= N_BUTTONS:
        return 0
    return controller.get_button(btn)

def axis(idx):
    """Safe axis read: returns 0.0 if the axis doesn't exist."""
    if idx < 0 or idx >= N_AXES:
        return 0.0
    return controller.get_axis(idx)

Max_pwm = 0

prev_btn = {}
def edge(btn):
    cur = button(btn)
    was = prev_btn.get(btn, 0)
    prev_btn[btn] = cur
    return bool(cur and not was)

# D-pad: hat first, button fallback
prev_dpad = {"up": False, "down": False, "left": False, "right": False}
def dpad_edges():
    if N_HATS > 0:
        hx, hy = controller.get_hat(0)
        cur = {"up": hy == 1, "down": hy == -1, "left": hx == -1, "right": hx == 1}
    else:
        cur = {k: bool(button(b)) for k, b in FALLBACK_DPAD_BTNS.items()}
    out = {k: cur[k] and not prev_dpad[k] for k in cur}
    prev_dpad.update(cur)
    return out

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

print(f"System Ready. Test mode toggle = button {BTN_TEST_TOGGLE} (Share). "
      f"Cross = full power, Circle = precision (normal driving).")
print("=== TEST MODE ON ===  D-pad LEFT/RIGHT = change bilge | UP = forward | "
      "DOWN = reverse | same again or Square = stop")
report()

# --- MAIN LOOP ---
heartbeat = 0
try:
    while True:
        pygame.event.pump()

        e_toggle = edge(BTN_TEST_TOGGLE)
        e_stop   = edge(BTN_TEST_STOP)
        dp       = dpad_edges()
        e_up, e_down, e_left, e_right = dp["up"], dp["down"], dp["left"], dp["right"]

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
            if button(BTN_FULL_POWER):
                Max_pwm = 255
            elif button(BTN_PRECISION):
                Max_pwm = 150

            ax = int(deadzone( axis(AXIS_SURGE_SWAY_X)) * Max_pwm)
            ay = int(deadzone(-axis(AXIS_SURGE_SWAY_Y)) * Max_pwm)
            yw = int(deadzone( axis(AXIS_YAW))          * Max_pwm)
            az = int(deadzone( axis(AXIS_HEAVE))        * -Max_pwm)

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

        time.sleep(0.02)

except KeyboardInterrupt:
    print("\nShutting down. Sending stop signal...")
    stop_packet = struct.pack(PACK_FORMAT, 0,0,0,0,0,0, 0,0,0,0,0,0)
    try:
        client.sendto(stop_packet, (TARGET_IP, TARGET_PORT))
    except OSError:
        pass
    pygame.quit()