import pygame, time

pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick detected!")
    exit()

js = pygame.joystick.Joystick(0)
js.init()
print(f"Controller: {js.get_name()}")
print(f"Buttons: {js.get_numbuttons()} | Axes: {js.get_numaxes()} | Hats: {js.get_numhats()}")
print("Press buttons / move sticks / D-pad. Ctrl+C to quit.\n")

AXIS_REPORT_THR = 0.5   # only report an axis when it passes this
prev_btn  = [0] * js.get_numbuttons()
prev_axis = [0.0] * js.get_numaxes()
prev_hat  = [(0, 0)] * js.get_numhats()

try:
    while True:
        pygame.event.pump()

        for i in range(js.get_numbuttons()):
            cur = js.get_button(i)
            if cur != prev_btn[i]:
                print(f"BUTTON {i} {'PRESSED' if cur else 'released'}")
                prev_btn[i] = cur

        for i in range(js.get_numaxes()):
            cur = js.get_axis(i)
            if (abs(cur) > AXIS_REPORT_THR) != (abs(prev_axis[i]) > AXIS_REPORT_THR):
                state = f"{cur:+.2f}" if abs(cur) > AXIS_REPORT_THR else "centered"
                print(f"AXIS {i}: {state}")
            prev_axis[i] = cur

        for i in range(js.get_numhats()):
            cur = js.get_hat(i)
            if cur != prev_hat[i]:
                print(f"HAT {i}: {cur}")
                prev_hat[i] = cur

        time.sleep(0.01)

except KeyboardInterrupt:
    pygame.quit()