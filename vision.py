"""Image recognition, independent from the desktop and from mouse input."""
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parent / 'Sources' / 'images_status'


def read_image(path):
    return np.asarray(Image.open(path).convert('RGB'))


def gray(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def white(rgb):
    a = rgb.astype(np.int16)
    return ((a.min(2) > 175) & (a.max(2) - a.min(2) < 60)).astype(np.uint8)


def foreground(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    return ((hsv[:, :, 2] > 100) & ((hsv[:, :, 1] > 65) |
                                                 (hsv[:, :, 2] > 170))).astype(np.uint8)


def trim(mask):
    y, x = np.where(mask)
    if not len(x):
        raise ValueError('Empty image template')
    return mask[y.min():y.max()+1, x.min():x.max()+1]


@dataclass
class Garden:
    image: np.ndarray
    origin: tuple
    scale: float
    water_empty: bool
    water_key: bytes
    plants_key: bytes
    ready: bool
    plants_at_least_20: bool = False
    water_max: bool = False

    def point(self, x, y):
        return (round(self.origin[0] + x*self.scale),
                round(self.origin[1] + y*self.scale))


class Vision:
    def __init__(self):
        self.example = read_image(ASSETS / 'exemple_jeu complet.png')
        self.harvest = gray(read_image(ASSETS / 'harvest.png'))
        self.garden_log = gray(read_image(ASSETS / 'log.png'))
        self.sprinkler_image = read_image(ASSETS / 'grow.png')
        self.sprinkler_mask = self.gold(self.sprinkler_image).astype(np.float32)
        self.ready = gray(read_image(ASSETS / 'log_status.png'))
        self.back = gray(read_image(ASSETS / 'log_card.png')[54:195, 31:132])
        self.board_title = gray(read_image(ASSETS / 'log_card.png')[18:44, 190:483])
        self.log_faces = {name: gray(read_image(ASSETS / f'log_{name}.png'))
                          for name in ('star', 'skull')}
        self.zero = white(read_image(ASSETS / 'water_status.png'))[7:18, 21:29]
        self.water_max_template = white(read_image(ASSETS / 'water_max.png'))
        header = white(self.example)
        self.slash = header[11:22, 48:55]
        # Counter font, sampled from the supplied toolbar. Unrecognised
        # numerals never authorize a sprinkler click.
        self.tens = {n: header[11:22, x:x+w] for n, x, w in
                     [(0,210,8),(1,100,6),(2,30,8),(3,175,7),
                      (4,39,7),(5,246,7),(6,282,7),(7,238,7)]}
        self.last_scale = None
        self.lab_templates = []
        # Three isolated Chemical plants from the supplied full garden. Hue is
        # used only to isolate training silhouettes; matching ignores colour.
        for x1, y1, x2, y2 in [(178, 56, 263, 133), (312, 264, 389, 345),
                                  (124, 276, 210, 353)]:
            crop = self.example[y1:y2, x1:x2]
            hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
            active = foreground(crop).astype(bool)
            hue = np.bincount(hsv[:, :, 0][active], minlength=180).argmax()
            mask = trim((active & (np.abs(hsv[:, :, 0].astype(int)-hue) < 8)).astype(np.uint8))
            side = int(np.hypot(*mask.shape))+6
            padded = np.zeros((side, side), np.uint8)
            yy, xx = (side-mask.shape[0])//2, (side-mask.shape[1])//2
            padded[yy:yy+mask.shape[0], xx:xx+mask.shape[1]] = mask
            for angle in range(0, 360, 15):
                rotated = trim(cv2.warpAffine(padded, cv2.getRotationMatrix2D(
                    (side/2, side/2), angle, 1), (side, side), flags=cv2.INTER_NEAREST))
                for size in (.9, 1., 1.1):
                    self.lab_templates.append(cv2.resize(rotated, None, fx=size, fy=size,
                                                         interpolation=cv2.INTER_NEAREST).astype(np.float32))

    @staticmethod
    def match(source, template):
        if source.shape[0] < template.shape[0] or source.shape[1] < template.shape[1]:
            return 0., (0, 0)
        _, score, _, pos = cv2.minMaxLoc(cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED))
        return score, pos

    @staticmethod
    def gold(rgb):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        return ((hsv[:,:,0] >= 10) & (hsv[:,:,0] <= 38) &
                (hsv[:,:,1] >= 75) & (hsv[:,:,2] >= 140)).astype(np.uint8)

    def sprinkler(self, garden):
        """Locate the gold sprite, then target its central bowl, not its stand."""
        x0,y0 = 5,30
        crop = garden.image[y0:425,x0:704]
        scene = self.gold(crop).astype(np.float32)
        t = self.sprinkler_mask
        h,w = t.shape
        overlap = cv2.matchTemplate(scene,t,cv2.TM_CCORR)
        integral = cv2.integral(scene)
        local = integral[h:,w:]-integral[:-h,w:]-integral[h:,:-w]+integral[:-h,:-w]
        union = np.maximum(local+t.sum()-overlap,1.)
        _,score,_,(x,y) = cv2.minMaxLoc(overlap/union)
        if score < .64:
            return None, score
        # Pick an actual gold pixel closest to the bowl centre. This point
        # moves with the detected sprite, including its current animation.
        ys,xs = np.where(t)
        k = np.argmin((xs-w*.5)**2+(ys-h*.43)**2)
        return (x0+x+int(xs[k]),y0+y+int(ys[k])), score

    def log_target(self, garden):
        return self.locate_log(garden.image)

    def locate_log(self, normalized):
        # Garden upgrades can move independently; do not assume a left column.
        score,(x,y) = self.match(gray(normalized[30:425,5:704]),self.garden_log)
        if score < .7:
            return None,score
        h,w=self.garden_log.shape
        return (x+5+w//2,y+30+h//2),score

    def garden(self, rgb):
        source = gray(rgb)
        if self.log_open(rgb):
            return None
        best = (0., None, None)
        scales = ([self.last_scale] if self.last_scale else [])
        scales += list(np.arange(.6, 2.01, .05))
        for scale in scales:
            t = cv2.resize(self.harvest, None, fx=scale, fy=scale)
            score, pos = self.match(source, t)
            if score > best[0]:
                best = score, pos, scale
            if score > .94:
                break
        score, pos, scale = best
        if score < .79:
            return None
        # Refine around the strongest coarse result for resized game windows.
        for s in np.arange(max(.4, scale-.025), scale+.026, .005):
            t = cv2.resize(self.harvest, None, fx=s, fy=s)
            q, p = self.match(source, t)
            if q > score:
                score, pos, scale = q, p, s
        self.last_scale = scale
        ox, oy = pos[0]-616*scale, pos[1]-3*scale
        if ox < -8 or oy < -8 or ox+709*scale > rgb.shape[1]+8 or oy+432*scale > rgb.shape[0]+8:
            return None
        normalized = cv2.warpAffine(rgb, np.float32([[1/scale, 0, -ox/scale],
                                                    [0, 1/scale, -oy/scale]]), (709, 432))
        # The toolbar reappears before the actual garden after the log closes.
        # Wait for a permanent garden icon before targeting any garden sprite.
        log_position, _ = self.locate_log(normalized)
        if log_position is None:
            return None
        # Numerator only: /20 and /24 both work. Never infer empty from a
        # failed match of the entire water_status example.
        hsv = cv2.cvtColor(normalized[:29, 60:145], cv2.COLOR_RGB2HSV)
        blue = ((hsv[:, :, 0] >= 90) & (hsv[:, :, 0] <= 120) &
                (hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 110)).astype(np.uint8)
        drops = [r for r in cv2.connectedComponentsWithStats(blue)[2][1:]
                 if r[4] > 35 and r[3] > 9]
        if len(drops) != 1:
            raise RuntimeError("Blue water droplet not recognized: stopped without clicking.")
        dx, _, dw, _, _ = drops[0]
        right = 60+int(dx)+int(dw)
        water_text = white(normalized[6:26, right+1:right+35])
        max_score,_ = self.match(water_text,self.water_max_template)
        water_max = max_score > .78
        numerator = water_text[:,:23]
        components = cv2.connectedComponentsWithStats(numerator)[2][1:]
        digits = sorted((r for r in components if r[4] >= 15 and r[3] >= 8), key=lambda r:r[0])
        if not digits or digits[0][0] > 6:
            raise RuntimeError("Unreadable water counter: stopped without clicking.")
        x, y, w, h, _ = digits[0]
        digit = numerator[y:y+h, x:x+w]
        digit = cv2.resize(digit, (8, 11), interpolation=cv2.INTER_NEAREST)
        zero_similarity = 1 - np.count_nonzero(digit != self.zero)/self.zero.size
        empty = zero_similarity > .88
        ready, _ = self.match(gray(normalized[:29, 300:435]), self.ready)
        return Garden(normalized, (ox, oy), scale, empty, numerator.tobytes(),
                      white(normalized[7:25, 26:75]).tobytes(), ready > .83,
                      self.enough_plants(normalized),water_max)

    @staticmethod
    def glyph_similarity(a, b):
        if abs(a.shape[1]-b.shape[1]) > 1:
            return 0.
        a = cv2.resize(a, (b.shape[1], b.shape[0]), interpolation=cv2.INTER_NEAREST)
        return 1 - np.count_nonzero(a != b)/b.size

    def enough_plants(self, rgb):
        """Read the numerator of the plant counter, never its capacity /24."""
        mask = white(rgb[9:24, 20:78])
        boxes = sorted((r for r in cv2.connectedComponentsWithStats(mask)[2][1:]
                        if 8 <= r[3] <= 12 and r[4] >= 15), key=lambda r:r[0])
        numerator = []
        found_slash = False
        for x,y,w,h,_ in boxes:
            glyph = mask[y:y+h, x:x+w]
            if self.glyph_similarity(glyph, self.slash) > .84:
                found_slash = True
                break
            numerator.append(glyph)
        if not found_slash or not numerator or len(numerator) > 2:
            return False
        if len(numerator) == 1:
            return False
        scores = [(self.glyph_similarity(numerator[0], t), n) for n,t in self.tens.items()]
        scores.sort(reverse=True)
        score, tens = scores[0]
        return score > .8 and score-scores[1][0] >= .08 and tens >= 2

    def lab(self, garden):
        # Exclude toolbar and the permanent icons in the left-hand column.
        scene = foreground(garden.image[30:424, 110:700]).astype(np.float32)
        integral = cv2.integral(scene)
        best = (0., None)
        for t in self.lab_templates:
            h, w = t.shape
            overlap = cv2.matchTemplate(scene, t, cv2.TM_CCORR)
            local = integral[h:, w:] - integral[:-h, w:] - integral[h:, :-w] + integral[:-h, :-w]
            union = np.maximum(local+t.sum()-overlap, 1.)
            iou = overlap/union
            _, score, _, (x, y) = cv2.minMaxLoc(iou)
            if score > best[0]:
                # Click on a foreground pixel near the centre, not the hollow
                # middle of the triangle where the game has no plant pixels.
                ys, xs = np.where(t)
                k = np.argmin((xs-w/2)**2+(ys-h/2)**2)
                best = score, (x+int(xs[k])+110, y+int(ys[k])+30)
        return best[1] if best[0] >= .59 else None, best[0]

    def log_open(self, rgb):
        source = gray(rgb)
        for s in dict.fromkeys([self.last_scale or 1., .75, 1., 1.25, 1.5, 2.]):
            score, _ = self.match(source, cv2.resize(self.board_title, None, fx=s, fy=s))
            if score > .84:
                return True
        return False

    def log_result(self, rgb):
        if not self.log_open(rgb):
            return None
        source = gray(rgb)
        best = (0., None)
        for name, template in self.log_faces.items():
            for scale in dict.fromkeys([self.last_scale or 1., .75, 1., 1.25, 1.5, 2.]):
                t = cv2.resize(template, None, fx=scale, fy=scale)
                score, _ = self.match(source, t)
                if score > best[0]:
                    best = score, name
        return best[1] if best[0] > .86 else None

    def cards(self, rgb):
        """Only unopened card backs are actionable, never a revealed face."""
        source = gray(rgb)
        best = (0., None, None)
        for scale in [self.last_scale or 1., .75, 1., 1.25, 1.5, 2.]:
            t = cv2.resize(self.back, None, fx=scale, fy=scale)
            score, pos = self.match(source, t)
            if score > best[0]:
                best = score, pos, t.shape
        score, pos, shape = best
        if score < .87:
            return None
        return (pos[0]+shape[1]//2, pos[1]+shape[0]//2)
