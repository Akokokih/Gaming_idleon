import pyautogui
import cv2
import numpy as np
from PIL import Image
import win32gui
import win32con
import win32api
import time

# Fonction pour récupérer la fenêtre à capturer
def get_window_coordinates(window_name):
    hwnd = win32gui.FindWindow(None, window_name)
    if hwnd:
        rect = win32gui.GetWindowRect(hwnd)
        return rect
    else:
        raise Exception(f"Fenêtre '{window_name}' non trouvée")

# Capture d'écran d'une zone spécifique (celle de la fenêtre)
def capture_window(window_name):
    try:
        x1, y1, x2, y2 = get_window_coordinates(window_name)
        screenshot = pyautogui.screenshot(region=(x1, y1, x2-x1, y2-y1))
        screenshot.save("window_capture.png")
        return screenshot
    except Exception as e:
        print(e)

# Fonction pour détecter un élément dans l'image
def detect_element_in_window(element_image_path, window_screenshot_path):
    # Charger l'image de l'élément et celle de la capture d'écran
    template = cv2.imread(element_image_path, cv2.IMREAD_GRAYSCALE)
    screenshot = cv2.imread(window_screenshot_path, cv2.IMREAD_GRAYSCALE)

    # Dimensions du modèle (élément à détecter)
    template_height, template_width = template.shape[:2]

    # Recherche de correspondance de modèle (template matching)
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)

    # Seuil de détection (par exemple 0.8 pour une bonne correspondance)
    threshold = 0.9
    locations = np.where(result >= threshold)

    #print("Locations :", type(locations), locations, locations[0])

    if len(locations[0]) > 0:
        # Prendre la première occurrence trouvée
        y, x = locations[0][0], locations[1][0]

        # Calculer le centre de l'élément détecté
        center_x = x + template_width // 2
        center_y = y + template_height // 2

        return (center_x, center_y)
    else:
        return None

# Fonction pour cliquer à un endroit spécifique dans la fenêtre
def click_in_window(window_name, position):
    x1, y1, _, _ = get_window_coordinates(window_name)
    print(position)
    print(type(position))
    if type(position) == None:
        capture_window(window_name)
    x, y = position
    absolute_x = x1 + x
    absolute_y = y1 + y
    pyautogui.click(absolute_x, absolute_y)


# Fonction principale qui combine les étapes
def main(window_name):
    # 1. Capturer la fenêtre
    capture_window(window_name)

    check_water, check_log, check_plant = False, False, False

    while not (check_water and check_log and check_plant):
        while not(check_water):
            capture_window(window_name)
            # 2. Détecter l'élément water
            position = detect_element_in_window(water_status, "window_capture.png")
            print(position)
            if not position:
                try:
                    print(f"Water not empty, click on water {position}")
                    print("Arrosoir")
                    position = detect_element_in_window(grow, "window_capture.png")

                    # 3. Si l'élément est trouvé, on clique dessus
                    click_in_window(window_name, position)
                    time.sleep(2)
                except:
                    time.sleep(2)
                # 4. Harvest_ALL
                try:
                    position = detect_element_in_window(harvest, "window_capture.png")
                    click_in_window(window_name, position)
                    time.sleep(4)
                except:
                    print("Not found harvest_all")

            else:
                print("Water empty.")
                check_water = True

        while not(check_log):
            # 2. Détecter l'élément log
            position_log = detect_element_in_window(log_status, "window_capture.png")

            if position_log:
                print("Log full")
                print("Log")
                position_log = detect_element_in_window(log, "window_capture.png")
                # 3. Si l'élément est trouvé, on clique dessus

                click_in_window(window_name, position_log)
                time.sleep(4)

                # card
                print("Card game")
                time.sleep(3)
                game_card = True
                while game_card:
                    try:
                        time.sleep(3)
                        capture_window(window_name)
                        position_card = detect_element_in_window(log_card, "window_capture.png")
                        # 3. Si l'élément est trouvé, on clique dessus
                        click_in_window(window_name, position_card)
                    except:
                        game_card = False

                check_water = False
                check_log = True
            else:
                print(f"Log not full {position_log}")
                check_log = True
                check_water = False

# Exécution du programme
if __name__ == "__main__":
    window_name = "Legends Of Idleon"
    water_status = "Sources\\images_status\\water_status.png"  # L'image de l'élément à détecter
    grow = "Sources\\images_status\\grow.png"
    harvest = "Sources\\images_status\\harvest.png"
    log_status = "Sources\\images_status\\log_status.png"
    log = "Sources\\images_status\\log.png"
    log_card = "Sources\\images_status\\log_card.png"
    main(window_name)
