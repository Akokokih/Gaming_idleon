import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
from bot import Bot, Stopped, Settings
from vision import Vision, ASSETS, read_image, white


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = Vision()

    def test_water_not_empty_in_supplied_example(self):
        g = self.v.garden(self.v.example)
        self.assertIsNotNone(g)
        self.assertFalse(g.water_empty)
        self.assertFalse(g.water_max)

    def test_real_max_label_is_distinct_from_remaining_numeric_charges(self):
        frame=read_image(Path(__file__).parent/'fixtures'/'moved_upgrades.png')
        for scale in (.75,1.,1.25,1.5):
            with self.subTest(scale=scale):
                g=self.v.garden(cv2.resize(frame,None,fx=scale,fy=scale))
                self.assertTrue(g.water_max)
                self.assertFalse(g.water_empty)

    def test_zero_numerator_independent_of_denominator(self):
        im = self.v.example.copy()
        im[7:25,98:111] = 30
        zero = self.v.zero
        im[11:22,99:107][zero.astype(bool)] = 255
        self.assertTrue(self.v.garden(im).water_empty)
        self.assertFalse(self.v.garden(im).water_max)

    def test_numeric_remaining_charges_are_not_read_as_max(self):
        im=self.v.example.copy()
        im[7:25,98:140]=30
        x=100
        for n in (2,3):
            glyph=self.v.tens[n]
            h,w=glyph.shape
            im[11:11+h,x:x+w][glyph.astype(bool)]=255
            x+=w+1
        g=self.v.garden(im)
        self.assertFalse(g.water_max)
        self.assertFalse(g.water_empty)

    def test_unreadable_water_fails_closed(self):
        im = self.v.example.copy()
        im[7:25,98:111] = 30
        with self.assertRaisesRegex(RuntimeError, 'Unreadable'):
            self.v.garden(im)

    def test_water_counter_moves_with_one_digit_plant_count(self):
        im = self.v.example.copy()
        im[7:25,98:111] = 30
        im[11:22,99:107][self.v.zero.astype(bool)] = 255
        strip = im[:29,75:140].copy()
        im[:29,67:140] = 30
        im[:29,67:132] = strip
        self.assertTrue(self.v.garden(im).water_empty)

    def test_resized_garden(self):
        for s in (.75, 1.25, 1.5):
            with self.subTest(scale=s):
                g = self.v.garden(cv2.resize(self.v.example, None, fx=s, fy=s))
                self.assertIsNotNone(g)
                self.assertFalse(g.water_empty)
                self.assertTrue(g.plants_at_least_20)

    def test_plant_threshold_uses_current_count_not_capacity(self):
        for text, allowed in [('0',False),('2',False),('10',False),('19',False),
                              ('20',True),('21',True),('24',True),('30',True)]:
            with self.subTest(count=text):
                im = self.v.example.copy()
                im[9:24,28:78] = 30
                x = 30
                for ch in text+'/24':
                    if ch=='/':
                        glyph=self.v.slash
                    elif ch=='9':
                        glyph=np.array([[0,1,1,1,1,1,0], [1,1,0,0,0,1,1],
                                        [1,1,0,0,0,1,1], [1,1,0,0,0,1,1],
                                        [0,1,1,1,1,1,1], [0,0,0,0,0,1,1],
                                        [0,0,0,0,0,1,1], [0,0,0,0,0,1,1],
                                        [0,0,0,0,0,1,1], [0,0,0,0,0,1,1],
                                        [0,1,1,1,1,1,0]], dtype=np.uint8)
                    else:
                        glyph=self.v.tens[int(ch)]
                    h,w=glyph.shape
                    im[11:11+h,x:x+w][glyph.astype(bool)] = 255
                    x+=w+1
                self.assertEqual(self.v.enough_plants(im),allowed)

    def test_unreadable_plant_counter_never_authorizes_sprinkler(self):
        im=self.v.example.copy()
        im[9:24,28:78]=30
        self.assertFalse(self.v.enough_plants(im))

    def test_known_labs(self):
        point, score = self.v.lab(self.v.garden(self.v.example))
        self.assertIsNotNone(point)
        self.assertGreater(score, .8)

    def test_sprinkler_bowl_detected_at_multiple_scales(self):
        for scale in (.75,1.,1.25,1.5):
            with self.subTest(scale=scale):
                g=self.v.garden(cv2.resize(self.v.example,None,fx=scale,fy=scale))
                point,score=self.v.sprinkler(g)
                self.assertIsNotNone(point)
                self.assertGreater(score,.64)
                self.assertTrue(40 < point[0] < 85 and 175 < point[1] < 210)

    def test_sprinkler_target_moves_with_its_sprite(self):
        im=self.v.example.copy()
        sprite=im[157:230,21:104].copy()
        im[140:250,5:115]=30
        im[166:239,26:109]=sprite
        point,score=self.v.sprinkler(SimpleNamespace(image=im))
        self.assertEqual(point,(67,194))

    def test_sprinkler_can_move_to_bottom_right(self):
        im=self.v.example.copy()
        sprite=im[157:230,21:104].copy()
        im[140:250,5:115]=30
        im[350:423,599:682]=sprite
        point,score=self.v.sprinkler(SimpleNamespace(image=im))
        self.assertEqual(point,(640,378))

    def test_actual_moved_upgrades_are_located_in_full_garden(self):
        frame=read_image(Path(__file__).parent/'fixtures'/'moved_upgrades.png')
        g=self.v.garden(frame)
        self.assertIsNotNone(g)
        sprinkler,score=self.v.sprinkler(g)
        log,log_score=self.v.log_target(g)
        self.assertIsNotNone(sprinkler)
        self.assertTrue(sprinkler[0]>600 and sprinkler[1]>350)
        self.assertIsNotNone(log)
        self.assertTrue(log[0]<100 and log[1]>250)

    def test_missing_or_gray_sprinkler_has_no_click_target(self):
        for disabled in (False,True):
            im=self.v.example.copy()
            region=im[140:250,5:115]
            region[:]=cv2.cvtColor(cv2.cvtColor(region,cv2.COLOR_RGB2GRAY),cv2.COLOR_GRAY2RGB) if disabled else 30
            self.assertIsNone(self.v.sprinkler(SimpleNamespace(image=im))[0])

    def test_other_plants_do_not_match_labs(self):
        im = self.v.example.copy()
        for a,b,c,d in [(175,52,269,136),(306,258,394,347),(122,271,212,355),(478,27,572,113)]:
            im[b:d,a:c] = 30
        self.assertIsNone(self.v.lab(self.v.garden(im))[0])

    def test_labs_rotate_and_change_colour(self):
        for index, colour in [(0,(250,250,250)), (7,(255,100,40)), (19,(170,70,255))]:
            with self.subTest(colour=colour):
                im = np.full((432,709,3), 30, np.uint8)
                t = self.v.lab_templates[index]
                h,w = t.shape
                im[150:150+h,250:250+w][t.astype(bool)] = colour
                g = SimpleNamespace(image=im)
                self.assertIsNotNone(self.v.lab(g)[0])

    def test_only_card_backs_are_targets(self):
        board = read_image(ASSETS/'log_card.png')
        self.assertIsNotNone(self.v.cards(board))
        self.assertIsNone(self.v.garden(board))
        self.assertIsNone(self.v.cards(np.full_like(board,30)))

    def test_real_star_skull_and_backs_are_distinguished(self):
        for name, expected in [('star','star'),('skull','skull'),('backs',None)]:
            frame=read_image(Path(__file__).parent/'fixtures'/f'log_{name}.png')
            for scale in (.75,1.,1.25,1.5):
                with self.subTest(face=name,scale=scale):
                    rgb=cv2.resize(frame,None,fx=scale,fy=scale)
                    self.assertEqual(self.v.log_result(rgb),expected)
                    self.assertIsNotNone(self.v.cards(rgb))

    def test_board_modal_prevents_background_garden_recognition(self):
        im = self.v.example.copy()
        title = read_image(ASSETS/'log_card.png')[18:44,190:483]
        im[60:86,200:493] = title
        self.assertIsNone(self.v.garden(im))


def garden(empty=True, ready=False, water=b'0', plants=b'0', enough=True, maximum=False):
    return SimpleNamespace(water_empty=empty, ready=ready, water_key=water,
                           plants_key=plants, plants_at_least_20=enough,
                           water_max=maximum,point=lambda x,y:(x,y))


class FakeDesktop:
    def __init__(self):
        self.clicks=[]
    def check(self): pass
    def emergency(self): pass
    def capture(self): return 'frame'
    def click(self, point): self.clicks.append(point)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.d = FakeDesktop()
        self.messages=[]
        self.bot = Bot(self.d, SimpleNamespace(cards=lambda frame:None,
                                             log_open=lambda frame:False,
                                             log_result=lambda frame:None,
                                             sprinkler=lambda g:((62,185),.95),
                                             log_target=lambda g:((60,143),.95)),
                       threading.Event(), self.messages.append)
        self.bot.wait = lambda *a,**k:None

    def test_hidden_harvest_button_waits_for_animation_without_clicking(self):
        expected=garden()
        self.bot.vision.garden=unittest.mock.Mock(side_effect=[None,None,expected])
        self.assertIs(self.bot.garden(), expected)
        self.assertEqual(self.d.clicks,[])
        self.assertEqual(self.bot.vision.garden.call_count,3)
        self.assertIn('animation',self.messages[0])

    def test_real_harvest_animation_is_retried(self):
        v=Vision()
        frame=read_image(Path(__file__).parent/'fixtures'/'harvest_animation.png')
        self.bot.vision=v
        self.bot.capture=unittest.mock.Mock(side_effect=[frame,v.example])
        self.assertIsNotNone(self.bot.garden())
        self.assertEqual(self.bot.capture.call_count,2)
        self.assertEqual(self.d.clicks,[])

    def test_toolbar_only_after_log_waits_for_garden_sprites(self):
        v=Vision()
        frame=read_image(Path(__file__).parent/'fixtures'/'garden_loading.png')
        self.bot.vision=v
        self.bot.capture=unittest.mock.Mock(side_effect=[frame,v.example])
        self.assertIsNotNone(self.bot.garden())
        self.assertEqual(self.bot.capture.call_count,2)
        self.assertEqual(self.d.clicks,[])

    def test_missing_garden_times_out_without_clicking(self):
        self.bot.vision.garden=lambda frame:None
        with patch('bot.time.monotonic', side_effect=[0.,0.,11.]):
            self.bot.capture=lambda:'frame'
            with self.assertRaisesRegex(RuntimeError,'after 10 seconds'):
                self.bot.garden()
        self.assertEqual(self.d.clicks,[])

    def test_stop_during_animation_wait_prevents_further_capture(self):
        self.bot.vision.garden=lambda frame:None
        self.bot.wait=lambda seconds:self.bot.stop.set()
        with self.assertRaises(Stopped):
            self.bot.garden()
        self.assertEqual(self.d.clicks,[])

    def test_no_water_finishes_with_harvest(self):
        self.bot.garden=lambda:garden()
        self.bot.harvest_and_water()
        self.assertEqual(self.d.clicks,[(658,15)])

    def test_plant_threshold_is_checked_before_harvest(self):
        states = iter([garden(empty=False,maximum=True),
                       garden(empty=False,enough=False,maximum=True),
                       garden(empty=False,enough=False,maximum=False)])
        self.bot.garden=lambda:next(states)
        self.bot.harvest_and_water()
        self.assertEqual(self.d.clicks,[(658,15),(62,185)])

    def test_max_sprinkler_refills_low_count_without_waiting_or_harvesting(self):
        states=iter([garden(empty=False,maximum=True,enough=False),
                     garden(empty=False,maximum=False,enough=False)])
        self.bot.garden=lambda:next(states)
        waits=[]
        self.bot.wait=lambda seconds:waits.append(seconds)
        self.bot.harvest_and_water()
        self.assertEqual(self.d.clicks,[(62,185)])
        self.assertEqual(waits,[2.])

    def test_sprinkler_rechecks_threshold_after_each_harvest(self):
        states = iter([garden(empty=False,maximum=True),
                       garden(empty=False,enough=False,maximum=True),garden(empty=False,maximum=True),
                       garden(empty=False,maximum=True),garden(empty=False,enough=False,maximum=True),
                       garden(empty=False,enough=False,maximum=False)])
        self.bot.garden=lambda:next(states)
        self.bot.harvest_and_water()
        self.assertEqual(self.d.clicks,[(658,15),(62,185),(658,15),(62,185)])

    def test_preserved_sprinkler_charges_do_not_end_the_phase(self):
        same=garden(empty=False,water=b'Max',maximum=True,enough=False)
        states=iter([same]*11+[garden(empty=False,water=b'23',enough=False)])
        self.bot.garden=lambda:next(states)
        self.bot.harvest_and_water()
        self.assertEqual(self.d.clicks,[(62,185)]*6)
        self.assertIn('Sprinkler counter unchanged — keeping sprinkler priority',self.messages)

    def test_ready_log_is_deferred_only_while_sprinkler_is_max(self):
        states=iter([garden(empty=False,ready=True,maximum=True,enough=False),
                     garden(empty=False,ready=True,enough=False),garden(enough=False)])
        calls=[]
        self.bot.harvest_and_water=lambda:(calls.append('water') or next(states))
        self.bot.play_log=lambda g:calls.append('log')
        self.bot.garden=lambda:garden()
        self.bot.vision.lab=lambda g:(None,.1)
        self.bot.run()
        self.assertEqual(calls,['water','water','log','water'])
        self.assertIn('Log deferred — sprinkler still Max',self.messages)

    def test_low_count_nonmax_allows_log_even_with_remaining_charges(self):
        g=garden(empty=False,water=b'23',enough=False)
        self.bot.garden=lambda:g
        self.assertIs(self.bot.harvest_and_water(),g)
        self.assertEqual(self.d.clicks,[])

    def test_unrecognized_sprinkler_prevents_guessed_clicks_and_harvest(self):
        self.bot.vision.sprinkler=lambda g:(None,.3)
        self.bot.garden=lambda:garden(empty=False,enough=False,maximum=True)
        with self.assertRaisesRegex(RuntimeError,'not confidently recognized'):
            self.bot.harvest_and_water()
        self.assertEqual(self.d.clicks,[])

    def test_sprinkler_uses_detected_point_and_current_window_transform(self):
        self.bot.vision.sprinkler=lambda g:((70,190),.99)
        g=garden()
        g.point=lambda x,y:(2*x+100,2*y+50)
        self.bot.garden=lambda:garden()
        self.bot.use_sprinkler(g)
        self.assertEqual(self.d.clicks,[(240,430)])

    def test_log_then_water_then_lab_then_water_then_finish(self):
        phases = iter([garden(ready=True),garden(),garden()])
        calls=[]
        self.bot.harvest_and_water=lambda:(calls.append('water') or next(phases))
        self.bot.play_log=lambda g:calls.append('log')
        self.bot.garden=lambda:garden()
        candidates=iter([((300,200),.9),(None,.1),(None,.1),(None,.1)])
        self.bot.vision.lab=lambda g:next(candidates)
        self.bot.run()
        self.assertEqual(calls,['water','log','water','water'])
        self.assertEqual(self.d.clicks,[(300,200)])
        self.assertIn('Done',self.messages[-1])

    def test_ready_is_rechecked_after_each_log(self):
        phases=iter([garden(ready=True),garden(ready=True),garden()])
        logs=[]
        self.bot.harvest_and_water=lambda:next(phases)
        self.bot.play_log=lambda g:logs.append('log')
        self.bot.garden=lambda:garden()
        self.bot.vision.lab=lambda g:(None,.1)
        self.bot.run()
        self.assertEqual(logs,['log','log'])

    def test_log_closure_never_clicks_stale_card(self):
        frames=iter(['board','board','garden'])
        self.bot.capture=lambda:next(frames)
        self.bot.vision.cards=lambda f:(80,120) if f=='board' else None
        self.bot.vision.garden=lambda f:garden() if f=='garden' else None
        self.bot.play_log(garden(ready=True))
        self.assertEqual(self.d.clicks,[(60,143),(80,120)])

    def test_open_log_resumes_without_clicking_the_green_log_again(self):
        frames=iter(['board','board','garden'])
        self.bot.capture=lambda:next(frames)
        self.bot.vision.cards=lambda f:(80,120) if f=='board' else None
        self.bot.vision.garden=lambda f:garden() if f=='garden' else None
        self.bot.play_log()
        self.assertEqual(self.d.clicks,[(80,120)])

    def test_log_rechecks_backs_after_temporary_animation(self):
        frames=iter(['board','animation','board','garden'])
        self.bot.capture=lambda:next(frames)
        self.bot.vision.cards=lambda f:(80,120) if f=='board' else None
        self.bot.vision.garden=lambda f:garden() if f=='garden' else None
        self.bot.play_log()
        self.assertEqual(self.d.clicks,[(80,120)])

    def test_gray_skull_stops_even_when_other_backs_remain(self):
        frames=iter(['board','skull','board','garden'])
        self.bot.capture=lambda:next(frames)
        self.bot.vision.cards=lambda f:(80,120)
        self.bot.vision.log_result=lambda f:'skull' if f=='skull' else None
        self.bot.vision.garden=lambda f:garden() if f=='garden' else None
        self.bot.play_log()
        self.assertEqual(self.d.clicks,[])

    def test_green_star_waits_then_clicks_next_back(self):
        frames=iter(['board','star','star','board','garden'])
        self.bot.capture=lambda:next(frames)
        self.bot.vision.cards=lambda f:(80,120)
        self.bot.vision.log_result=lambda f:'star' if f=='star' else None
        self.bot.vision.garden=lambda f:garden() if f=='garden' else None
        self.bot.play_log()
        self.assertEqual(self.d.clicks,[(80,120)])

    def test_stop_prevents_mouse_click(self):
        self.bot.stop.set()
        with self.assertRaises(Stopped):
            self.bot.click((10,10),'click',0)
        self.assertEqual(self.d.clicks,[])

    def test_waits_between_harvests_and_cards(self):
        delays=[]
        self.bot.wait=lambda seconds,**kw:delays.append(seconds)
        self.bot.garden=lambda:garden()
        self.bot.harvest_and_water()
        self.assertEqual(delays,[2.])
        frames=iter(['board','board','garden'])
        self.bot.capture=lambda:next(frames)
        self.bot.vision.cards=lambda f:(80,120) if f=='board' else None
        self.bot.vision.garden=lambda f:garden() if f=='garden' else None
        delays.clear()
        self.bot.play_log(garden(ready=True))
        self.assertEqual(delays,[1.,1.])


if __name__=='__main__':
    unittest.main()
