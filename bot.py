"""Bounded game state machine and Windows input adapter."""
import ctypes
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from vision import Vision


class Stopped(Exception):
    pass


class Desktop:
    def __init__(self, title='Legends Of Idleon'):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass
        import win32gui
        import win32con
        import win32api
        import pyautogui
        self.gui, self.con, self.api, self.mouse = win32gui, win32con, win32api, pyautogui
        matches = []
        win32gui.EnumWindows(lambda h, _: matches.append(h) if (
            win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) == title) else None, None)
        if len(matches) != 1:
            raise RuntimeError(f'Open exactly one “{title}” window before starting.')
        self.hwnd = matches[0]
        self.mouse.FAILSAFE = True
        self.mouse.PAUSE = .05
        self.api.GetAsyncKeyState(self.con.VK_F8)  # Clear an earlier stop press.
        win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            # Windows may deny a background process the foreground. The
            # countdown lets the user bring the game forward themselves.
            pass

    def emergency(self):
        if self.api.GetAsyncKeyState(self.con.VK_F8) & 0x8001:
            raise Stopped('Stopped with F8')

    def check(self):
        self.emergency()
        if (not self.gui.IsWindow(self.hwnd) or self.gui.IsIconic(self.hwnd)
                or self.gui.GetForegroundWindow() != self.hwnd):
            raise Stopped('Game hidden or no longer in the foreground')

    def rect(self):
        left, top, right, bottom = self.gui.GetClientRect(self.hwnd)
        x, y = self.gui.ClientToScreen(self.hwnd, (left, top))
        return x, y, right-left, bottom-top

    def capture(self):
        import numpy as np
        from PIL import ImageGrab
        self.check()
        x, y, w, h = self.rect()
        return np.asarray(ImageGrab.grab(bbox=(x, y, x+w, y+h), all_screens=True).convert('RGB'))

    def click(self, point):
        self.check()
        x, y, w, h = self.rect()
        px, py = point
        if not (0 <= px < w and 0 <= py < h):
            raise RuntimeError('Click outside the game window: stopped.')
        hit = self.gui.WindowFromPoint((x+px, y+py))
        if self.gui.GetAncestor(hit, 2) != self.hwnd:
            raise Stopped('Another window is covering the target')
        self.mouse.moveTo(x+px, y+py)
        # The game's own cursor can lag behind the OS pointer. Let it reach
        # the detected target before pressing, especially across the garden.
        time.sleep(.25)
        self.check()
        self.mouse.mouseDown()
        try:
            time.sleep(.12)
        finally:
            self.mouse.mouseUp()


@dataclass
class Settings:
    harvest_wait: float = 2.
    card_wait: float = 1.
    max_actions: int = 2000
    max_minutes: float = 60.


class Bot:
    def __init__(self, desktop, vision, stop, report, settings=None):
        self.desktop, self.vision = desktop, vision
        self.stop, self.report = stop, report
        self.settings = settings or Settings()
        self.actions = 0
        self.started = time.monotonic()
        self.last_frame = None

    def wait(self, seconds, monitor_focus=True):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if self.stop.wait(min(.05, max(0., deadline-time.monotonic()))):
                raise Stopped('Stop requested')
            if monitor_focus:
                self.desktop.check()
            else:
                self.desktop.emergency()

    def capture(self):
        if self.stop.is_set():
            raise Stopped('Stop requested')
        if time.monotonic()-self.started > self.settings.max_minutes*60:
            raise RuntimeError('Time limit reached.')
        self.last_frame = self.desktop.capture()
        return self.last_frame

    def garden(self):
        # Harvest All disappears during the harvest animation. A single
        # missing anchor does not mean that the Gaming panel was closed.
        deadline = time.monotonic()+10.
        waiting = False
        while True:
            garden = self.vision.garden(self.capture())
            if garden is not None:
                return garden
            if time.monotonic() >= deadline:
                raise RuntimeError('Garden not recognized after 10 seconds. Open the Gaming panel, then restart.')
            if not waiting:
                self.report('Waiting for the garden / harvest animation…')
                waiting = True
            self.wait(.25)

    def click(self, point, label, delay):
        if self.stop.is_set():
            raise Stopped('Stop requested')
        if self.actions >= self.settings.max_actions:
            raise RuntimeError('Click limit reached.')
        self.report(label)
        self.desktop.click(point)
        self.actions += 1
        self.wait(delay)

    def use_sprinkler(self, garden):
        target, confidence = self.vision.sprinkler(garden)
        if target is None:
            raise RuntimeError('Golden sprinkler not confidently recognized. Stopped without guessing a click.')
        self.click(garden.point(*target),
                   f'Golden sprinkler — refill after harvest ({confidence:.0%})', self.settings.harvest_wait)
        after = self.garden()
        if not after.water_empty and after.water_key == garden.water_key:
            self.report('Sprinkler counter unchanged — keeping sprinkler priority')
        return after

    def harvest_and_water(self):
        for _ in range(250):
            before = self.garden()
            if before.plants_at_least_20:
                # The threshold is checked BEFORE harvest, not on the reduced
                # count afterwards. Refill those newly freed slots immediately.
                self.click(before.point(658, 15), 'Harvest — batch of at least 20 plants', self.settings.harvest_wait)
                after = self.garden()
                if after.water_empty:
                    return after
                after = self.use_sprinkler(after)
            elif before.water_max:
                self.report('Sprinkler Max — refill before considering the log')
                after = self.use_sprinkler(before)
            else:
                self.report('Fewer than 20 plants and sprinkler not Max — check the log')
                return before
            # An unchanged counter may be a conserved charge. Re-observe the
            # actual Max state and plant count rather than assuming exhaustion.
            if not after.plants_at_least_20 and not after.water_max:
                return after
        raise RuntimeError('Harvest/water phase exceeded 250 cycles. Stopped.')

    def play_log(self, garden=None):
        if garden is not None:
            target,confidence = self.vision.log_target(garden)
            if target is None:
                raise RuntimeError('Green log not confidently recognized. Stopped without guessing a click.')
            self.click(garden.point(*target), f'Log Ready — detected green log ({confidence:.0%})', 1.)
        else:
            self.report('Log — resume the open card game')
        for _ in range(10):
            frame = self.capture()
            if self.vision.cards(frame) is not None or self.vision.log_open(frame):
                break
            self.wait(.2)
        else:
            raise RuntimeError('No face-down cards detected after opening the log.')
        clicked = 0
        skull_seen = False
        last_result = None
        deadline = time.monotonic()+12.
        while True:
            frame = self.capture()
            closing_garden = self.vision.garden(frame)
            if closing_garden is not None:
                self.report('Cards closed — back to the garden')
                if closing_garden.ready:
                    self.report('Log still Ready — recheck sprinkler charges before playing again')
                return
            result = self.vision.log_result(frame)
            if result == 'skull':
                skull_seen = True
            if result != last_result and result is not None:
                self.report('Log — gray skull: stop clicking and wait for the garden'
                            if result == 'skull' else
                            'Log — green star: wait for the next round')
            last_result = result
            if time.monotonic() >= deadline:
                raise RuntimeError('Log animation did not finish within 12 seconds. Stopped without clicking.')
            if skull_seen or result == 'star':
                self.wait(.15)
                continue
            card = self.vision.cards(frame)
            if card is None:
                # Both successful rounds and losses animate. Recheck backs,
                # faces AND the garden on every frame, rather than waiting
                # exclusively for the garden after a temporarily missing back.
                self.wait(.15)
                continue
            if clicked >= 150:
                raise RuntimeError('150-card limit reached.')
            self.click(card, 'Log — flip a card', self.settings.card_wait)
            clicked += 1
            deadline = time.monotonic()+12.

    def run(self):
        self.report('Starting in 3 seconds — press F8 to stop')
        self.wait(3., monitor_focus=False)
        frame = self.capture()
        if self.vision.cards(frame) is not None or self.vision.log_open(frame):
            self.play_log()
        for _ in range(250):
            garden = self.harvest_and_water()
            if garden.water_max:
                self.report('Log deferred — sprinkler still Max')
                self.wait(self.settings.harvest_wait)
                continue
            if garden.ready:
                self.play_log(garden)
                continue
            candidate = None
            for _ in range(3):
                garden = self.garden()
                candidate, confidence = self.vision.lab(garden)
                if candidate:
                    break
                self.wait(.4)
            if candidate is None:
                self.report('Done — harvesting finished, log unavailable, no lab plants detected')
                return
            self.click(garden.point(*candidate),
                       f'Lab plant — advance time (shape match {confidence:.0%})', 2.)
        raise RuntimeError('250-cycle limit reached.')


class Controller:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.running = False
        self.status = 'Ready — open Gaming in Idleon'
        self.entries = []
        self.thread = None

    def report(self, message):
        with self.lock:
            self.status = message
            self.entries.append(time.strftime('%H:%M:%S')+'  '+message)
            self.entries = self.entries[-150:]

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.stop_event.clear()
        self.thread = threading.Thread(target=self.work, daemon=True)
        self.thread.start()

    def work(self):
        bot = None
        try:
            self.report('Loading image recognition…')
            vision = Vision()
            desktop = Desktop()
            bot = Bot(desktop, vision, self.stop_event, self.report)
            bot.run()
        except Stopped as exc:
            self.report(str(exc))
        except Exception as exc:
            self.report(f'Stopped: {exc}')
            if bot is not None and bot.last_frame is not None:
                from PIL import Image
                folder = Path(__file__).resolve().parent / 'diagnostics'
                folder.mkdir(exist_ok=True)
                Image.fromarray(bot.last_frame).save(folder / 'last_error.png')
        finally:
            with self.lock:
                self.running = False

    def state(self):
        with self.lock:
            return dict(running=self.running, status=self.status, log=list(self.entries))
