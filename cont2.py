import socket, struct, pygame, time

# --- NETWORK ---
PACK_FORMAT  = '6B6B'
TARGET_IP    = "192.168.1.50"
TARGET_PORT  = 9090
DEADZONE_VAL = 0.2
LOOP_PERIOD  = 0.02         # seconds between packets (50 Hz)

# --- PACKET LAYOUT (must match updateMotors() on the STM32 -- do NOT change) ---
# A "channel" is one output slot of the firmware (motors[0..5]).
# bytes 0-5 : PWM  channel 0-5
# bytes 6-9 : DIR  channel 0-3   (one dir byte each)
# byte  10  : DIR  shared by channels 4 and 5
# byte  11  : heartbeat, must flip 0/1 on every packet sent (firmware stops on mismatch)

FWD_BIT = 0                 # value of FORWARD in Motors.h (check it)
REV_BIT = 1 - FWD_BIT

# =====================================================================================
#  BILGE MAP  <-- to swap bilges, edit only this block
# =====================================================================================
# Which firmware channel (0-5) each bilge (by position on the vehicle) is wired to.
# Any bilge can use any channel (vertical <-> horizontal is fine); every channel 0-5
# must be used exactly once. Swap two bilges by swapping their numbers.
#
# FIRMWARE LIMIT: channels 4 and 5 share ONE dir bit. The two bilges on channels 4/5
# can't run in opposite directions at the same moment. If they are asked to, the weaker
# one is stopped (and a warning is printed) instead of spinning the wrong way.
THRUSTER_CHANNEL = {"TL": 5, "TR": 4, "BR": 2, "BL": 3, "UP1": 1, "UP2": 0}

# Bilges that spin backwards (any of TL, TR, BR, BL, UP1, UP2).
# If both bilges on channels 4/5 are vertical, invert both or neither (shared dir bit).
INVERT = set()              # e.g. {"TR", "BL"}

THRUSTERS = ["TL", "TR", "BR", "BL", "UP1", "UP2"]
VERT      = ["UP1", "UP2"]
N_MOTORS  = len(THRUSTERS)

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
FALLBACK_DPAD_BTNS = {"up": 11, "down": 12, "left": 13, "right": 14}

# --- PACKET PRINTING ---
PRINT_PACKETS   = True
PRINT_ON_CHANGE = True      # True: only when PWM/dir change (heartbeat ignored)

# ------------------------------------------------------------------------------------
# Map helpers
# ------------------------------------------------------------------------------------
def validate_map():
    if set(THRUSTER_CHANNEL) != set(THRUSTERS):
        raise SystemExit(f"THRUSTER_CHANNEL must have exactly these keys: {THRUSTERS}")
    if sorted(THRUSTER_CHANNEL.values()) != list(range(N_MOTORS)):
        raise SystemExit("THRUSTER_CHANNEL: use each channel 0-5 exactly once.")
    bad = INVERT - set(THRUSTERS)
    if bad:
        raise SystemExit(f"INVERT: unknown names {sorted(bad)} (use {THRUSTERS}).")

def thruster_at(ch):
    return next(t for t in THRUSTERS if THRUSTER_CHANNEL[t] == ch)

def is_inverted(name):
    return name in INVERT

def print_map():
    print("Bilge map (bilge -> channel):")
    for t in THRUSTERS:
        inv = "  [inverted]" if is_inverted(t) else ""
        print(f"   {t:>3} -> ch{THRUSTER_CHANNEL[t]}{inv}")
    a, b = thruster_at(4), thruster_at(5)
    safe = a in VERT and b in VERT and is_inverted(a) == is_inverted(b)
    if not safe:
        print(f"WARNING: {a} (ch4) and {b} (ch5) share ONE dir bit. They can't run in "
              f"opposite directions at once; the weaker one will be stopped if asked to.")

_shared_conflict = False
def to_channels(cmd):
    """cmd = {thruster: signed value} -> 6 signed values in CHANNEL order,
    with the bilge map and inversion applied."""
    global _shared_conflict
    out = [0] * N_MOTORS
    for name, v in cmd.items():
        out[THRUSTER_CHANNEL[name]] = -v if is_inverted(name) else v

    # Channels 4/5 share one dir bit: never let one of them run backwards.
    if out[4] * out[5] < 0:
        loser = 4 if abs(out[4]) < abs(out[5]) else 5
        out[loser] = 0
        if not _shared_conflict:
            _shared_conflict = True
            print(f"[WARN] {thruster_at(4)} and {thruster_at(5)} want opposite directions "
                  f"but share one dir bit -> stopping {thruster_at(loser)}")
    else:
        _shared_conflict = False
    return out

# ------------------------------------------------------------------------------------
# Packet
# ------------------------------------------------------------------------------------
def deadzone(v):
    return v if abs(v) > DEADZONE_VAL else 0.0

def dbit(v):
    """Dir bit for a signed value. A stopped motor always gets 0."""
    if v == 0:
        return 0
    return REV_BIT if v < 0 else FWD_BIT

def build_packet(m, limit, hb):
    """m = 6 signed values in CHANNEL order (use to_channels() to get them)."""
    m = [max(-limit, min(limit, int(v))) for v in m]
    pwms = [abs(v) for v in m]                       # bytes 0-5
    dirs = [dbit(v) for v in m[:4]]                  # bytes 6-9
    shared = [v for v in m[4:] if v != 0]            # ch4/ch5 share one dir bit
    dirs.append(dbit(shared[0]) if shared else 0)    # byte 10
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
    for ch in range(N_MOTORS):
        d = dirs[ch] if ch < 4 else dirs[4]
        note = "  (shared dir with ch4/ch5)" if ch >= 4 else ""
        print(f"   ch{ch} {thruster_at(ch):>4}: pwm={pwms[ch]:3d} dir={d}{note}")
    print(f"   heartbeat={dirs[5]}")

# --- INITIALIZATION ---
validate_map()
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
test_idx = 0                # index into THRUSTERS
test_dir = 0                # latched: +1 forward, -1 reverse, 0 stopped
DIR_LABEL = {1: f"FORWARD (dir={FWD_BIT})", -1: f"REVERSE (dir={REV_BIT})", 0: "STOPPED"}

def report():
    t = THRUSTERS[test_idx]
    print(f"[TEST] {t} -> channel {THRUSTER_CHANNEL[t]} invert={is_inverted(t)} "
          f"-> {DIR_LABEL[test_dir]}")

TEST_HELP = ("LEFT/RIGHT = pick bilge (stops motor) | UP = forward | DOWN = reverse | "
             "same again or Square = stop")

# --- HARDWARE WARM-UP ---
print("Clearing ghost inputs... hold sticks neutral.")
for _ in range(15):
    pygame.event.pump()
    time.sleep(0.05)

print(f"System Ready. Test mode toggle = button {BTN_TEST_TOGGLE} (Share). "
      f"Cross = full power, Circle = precision (normal driving).")
print_map()
print(f"=== TEST MODE ON (power {TEST_PWM}) ===\n   {TEST_HELP}")
report()

# --- MAIN LOOP ---
heartbeat = 0
next_tick = time.monotonic()
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
                print(f"\n=== TEST MODE ON (power {TEST_PWM}) ===\n   {TEST_HELP}")
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

            # Every bilge is 0 except the one under test
            cmd = {t: 0 for t in THRUSTERS}
            cmd[THRUSTERS[test_idx]] = test_dir * TEST_PWM
            m = to_channels(cmd)
            limit = 255

        else:
            # ---------- NORMAL DRIVING ----------
            if button(BTN_FULL_POWER):
                Max_pwm = 210
            elif button(BTN_PRECISION):
                Max_pwm = 150

            ax = int(deadzone( axis(AXIS_SURGE_SWAY_X)) * Max_pwm)
            ay = int(deadzone(-axis(AXIS_SURGE_SWAY_Y)) * Max_pwm)
            yw = int(deadzone( axis(AXIS_YAW))          * Max_pwm)
            az = int(deadzone( axis(AXIS_HEAVE))        * -Max_pwm)

            cmd = {
                "TL":  ax + ay + yw,
                "TR":  ax - ay - yw,
                "BL":  -ax + ay - yw,
                "BR":  -ax - ay + yw,
                "UP1": az,
                "UP2": az,
            }
            m = to_channels(cmd)
            limit = Max_pwm

        packet = build_packet(m, limit, heartbeat)
        show_packet(packet)

        try:
            client.sendto(packet, (TARGET_IP, TARGET_PORT))
            heartbeat ^= 1          # only flip once the packet really went out
        except OSError:
            print("Network unreachable. Check connection to ROV.")

        # Fixed-rate loop so the packet period doesn't drift with print time.
        next_tick += LOOP_PERIOD
        delay = next_tick - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_tick = time.monotonic()

except KeyboardInterrupt:
    print("\nShutting down.")

finally:
    # Runs on Ctrl+C and on any crash. A few all-zero packets (heartbeat still
    # alternating) in case one is lost.
    print("Sending stop signal...")
    for _ in range(5):
        stop_packet = build_packet([0] * N_MOTORS, 255, heartbeat)
        try:
            client.sendto(stop_packet, (TARGET_IP, TARGET_PORT))
            heartbeat ^= 1
        except OSError:
            pass
        time.sleep(LOOP_PERIOD)
    pygame.quit()