# SPDX-License-Identifier: GPL-3.0-or-later
# animal-counter — pig counter on Jetson Orin Nano (OC-SORT + anti-ID-switch guards).
# Copyright (C) 2026  LOONIS Wennaël
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Rendering module for the pig counting application.

This module handles visualization of tracking and counting results.
"""

import cv2
import numpy as np
import datetime
import time
import logging 
from settings import Settings


# Load settings
settings = Settings()

# Configure logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

class Rendering:
    """
    Rendering class to manage visualization of tracking and counting results.
    
    Attributes:
        draw_box (bool): Whether to draw bounding boxes.
    """
    
    def __init__(self, draw_box=False, offset_counting_line=0):
        """
        Initialize the rendering object.
        
        Args:
            draw_box (bool, optional): Whether to draw tracking. Defaults to False.
        """
        self.draw_tracking = draw_box
        self.centroid_tracking = True
        self.box_tracking = True
        self.buttons = {}
        self.offset_counting_line=offset_counting_line
        
        self.btn_learning_on, self.btn_learning_on_inv_alpha, self.btn_learning_on_size = self.load_button("/app/img/learning_on.png")
        self.btn_learning_off, self.btn_learning_off_inv_alpha, self.btn_learning_off_size = self.load_button("/app/img/learning_off.png")
        self.btn_auto_on, self.btn_auto_on_inv_alpha, self.btn_auto_on_size = self.load_button("/app/img/auto_on.png")
        self.btn_auto_off, self.btn_auto_off_inv_alpha, self.btn_auto_off_size = self.load_button("/app/img/auto_off.png")
        self.btn_reset, self.btn_reset_inv_alpha, self.btn_reset_size = self.load_button("/app/img/reset.png")
        self.btn_arret, self.btn_arret_inv_alpha, self.btn_arret_size = self.load_button("/app/img/shutdown.png")
        self.play_0, self.play_0_inv, self.play_0_size = self.load_button("/app/img/0.png")
        self.play_1, self.play_1_inv, self.play_1_size = self.load_button("/app/img/1.png")
        self.play_2, self.play_2_inv, self.play_2_size = self.load_button("/app/img/2.png")
        
    def overlay_alpha(self, frame, overlay_premult, inv_alpha, x, y):
        h, w = overlay_premult.shape[:2]

        # sécurité ROI
        if y + h > frame.shape[0] or x + w > frame.shape[1]:
            return

        roi = frame[y:y+h, x:x+w]
        roi_float = roi.astype(np.float32)

        roi[:] = (overlay_premult + roi_float * inv_alpha).astype(np.uint8)
            
    def load_button(self, path):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)

        if img is None or img.shape[2] != 4:
            return None, None, None

        b, g, r, a = cv2.split(img)
        overlay = cv2.merge((b, g, r)).astype(np.float32)

        alpha = (a.astype(np.float32) / 255.0)[:, :, None]
        inv_alpha = 1.0 - alpha

        overlay_premult = overlay * alpha

        return overlay_premult, inv_alpha, overlay.shape[:2]
    
    def _draw_button(self, img, btn, inv, x, y, target_width=None, button_name=None, is_sprite=False, target_height=None):
        """Helper method to draw a button with consistent scaling and overlay.

        By default sizes by ``target_width`` (aspect ratio preserved). If
        ``target_height`` is given, sizes by height instead — so buttons with
        different aspect ratios (e.g. the wide shutdown button vs the taller
        reset/auto buttons) can share the same rendered height.
        Returns ``(new_w, new_h)``, or ``(0, 0)`` if the asset failed to load.
        """
        if btn is not None:
            h_btn, w_btn = btn.shape[:2]
            if target_height is not None:
                scale = target_height / h_btn
            else:
                scale = target_width / w_btn
            new_w = int(w_btn * scale)
            new_h = int(h_btn * scale)

            btn_resized = cv2.resize(btn, (new_w, new_h))
            inv_resized = cv2.resize(inv, (new_w, new_h))

            if len(inv_resized.shape) == 2:
                inv_resized = inv_resized[:, :, None]

            self.overlay_alpha(img, btn_resized, inv_resized, x, y)

            if is_sprite:
                # Special handling for play/pause/stop sprite (3 buttons in one)
                third = new_w // 3
                self.buttons["play"] = (x, y, x + third, y + new_h)
                self.buttons["pause"] = (x + third, y, x + 2 * third, y + new_h)
                self.buttons["stop"] = (x + 2 * third, y, x + new_w, y + new_h)
            elif button_name:
                self.buttons[button_name] = (x, y, x + new_w, y + new_h)
            return new_w, new_h
        return 0, 0
    
    def draw_ui(self, img, shared_state, input_type):
        if input_type != "CAMERA":
            return img

        h, w = img.shape[:2]
        self.buttons = {}
        btn = None
        
        # ===== CONFIG =====
        margin_x = int(0.03 * w)
        margin_y = int(0.05 * h)
        base_width = int(0.25 * w)  # largeur du sprite (important)

        # =========================
        # 🛑 BOUTON ARRÊT (BL-62) — permanent, tous états, coin haut-gauche
        # =========================
        # Bouton d'extinction standalone à (x=20, y=20), dessiné AVANT le sprite
        # pour que le sprite (décalé à droite) ne chevauche pas l'Arrêt.
        # Dimensionné par HAUTEUR (button_height) pour aligner avec les autres
        # boutons (reset/auto), dont l'image source est plus carrée — sinon le
        # bouton shutdown (image large 141×31) rendrait plus court à largeur égale.
        button_height = base_width // 9  # = hauteur rendue de reset (base_width//3 largeur, ratio ~3)
        arret_w, _ = self._draw_button(img, self.btn_arret, self.btn_arret_inv_alpha, 20, 20, button_name="arret", target_height=button_height)

        # =========================
        # 🎮 BOUTON PLAY/PAUSE/STOP (SPRITE UNIQUE)
        # =========================
        # Sprite décalé à droite de l'Arrêt: x = 20 + largeur_arret_réelle + gap(30)
        x = 20 + arret_w + 30
        y = 20

        if shared_state.status == 0:
            btn = self.play_0
            inv = self.play_0_inv
        elif shared_state.status == 1:
            btn = self.play_1
            inv = self.play_1_inv
        elif shared_state.status == 2:
            btn = self.play_2
            inv = self.play_2_inv

        if btn is not None:
            self._draw_button(img, btn, inv, x, y, base_width, is_sprite=True)

        # =========================
        # BOUTON LEARNING
        # =========================
        x_learning = w - base_width // 3 - margin_x

        if shared_state.learning_mode:
            self._draw_button(img, self.btn_learning_on, self.btn_learning_on_inv_alpha, x_learning, y, base_width // 3, button_name="learning")
        else:
            self._draw_button(img, self.btn_learning_off, self.btn_learning_off_inv_alpha, x_learning, y, base_width // 3, button_name="learning")

        # =========================
        # BOUTON AUTO
        # =========================
        x_auto = w - base_width // 3 * 2 - margin_x * 2

        if shared_state.status == 3:
            self._draw_button(img, self.btn_auto_on, self.btn_auto_on_inv_alpha, x_auto, y, base_width // 3, button_name="auto")
            # Position du bouton reset (à côté et avant le bouton auto)
            x_reset = w - base_width // 3 * 3 - margin_x * 3
            self._draw_button(img, self.btn_reset, self.btn_reset_inv_alpha, x_reset, y, base_width // 3, button_name="reset")
        else:
            self._draw_button(img, self.btn_auto_off, self.btn_auto_off_inv_alpha, x_auto, y, base_width // 3, button_name="auto")

        # =========================
        # MESSAGE D'ARRÊT (BL-62) — affiché pendant la finalisation/poweroff
        # =========================
        if shared_state.arret_requested:
            msg = "Le compteur va s'arrêter..."
            text_size = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
            text_x = (w - text_size[0]) // 2
            text_y = h // 2
            cv2.putText(img, msg, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        return img


    def handle_click(self, x, y, shared_state):

        for name, (x1, y1, x2, y2) in self.buttons.items():

            if x1 <= x <= x2 and y1 <= y <= y2:

                if name == "arret":
                    # BL-62: demande d'arrêt propre + poweroff (logique lourde dans DisplayThread)
                    shared_state.arret_requested = True

                elif name == "learning":
                    shared_state.learning_mode = not shared_state.learning_mode
                    shared_state.learning_start_time = time.time()
                    shared_state.image_counter = 0

                    if not shared_state.learning_mode:
                        shared_state.status = 3
                        shared_state.auto_mode = True

                elif name == "auto":

                    shared_state.auto_mode = not shared_state.auto_mode

                    if shared_state.auto_mode:
                        shared_state.status = 3
                        shared_state.delay_reinit = time.monotonic()
                    else:
                        shared_state.status = 0

                elif name == "reset":

                    if shared_state.auto_mode:
                        shared_state.counter_to_right = 0
                        shared_state.reset = True
                        shared_state.delay_reinit = time.monotonic()

                elif name == "play":

                    if shared_state.status != 1:
                        shared_state.status = 1
                        shared_state.delay_reinit = time.monotonic()

                elif name == "pause":

                    if shared_state.status != 0:
                        shared_state.status = 2
    
                elif name == "stop":
                    shared_state.status = 0
                
    def display_counter(self, img, counter_to_right, shared_state=None, input_type="CAMERA"):
        """
        Display the counter on the image.
        
        Args:
            img (numpy.ndarray): Image to display on.
            counter_to_right (int): Count of objects moving to the right.
            shared_state (SharedSt+ate, optional): Shared state object. Defaults to None.
            input_type (str, optional): Input type (CAMERA or FILE). Defaults to "CAMERA".
            
        Returns:
            numpy.ndarray: Image with counter displayed.
        """
        img_height, img_width = img.shape[:2]
        x = int((img_width / 2) + (img_width * self.offset_counting_line / 100))
        text_position = (x - 140, 100)
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 3.0
        font_color = (125, 0, 0)
        font_thickness = 2
        text = str(counter_to_right)
        
        # Display recording message in Learning Mode (only for CAMERA input)
        if shared_state:
            
            if  shared_state.learning_mode:
                cv2.putText(img, "Recording images in progress...", (img_width // 2 - 200, img_height // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                
                # Display image counter
                cv2.putText(img, f"Images: {shared_state.image_counter}", (img_width // 2 - 100, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

            elif shared_state.status > 0:
                # Display pig counter (normal behavior)
                cv2.putText(img, text, text_position, font, font_scale, font_color, font_thickness)
        
                line_color = (0, 255, 255)
                line_thickness = 1
                cv2.line(img, (x, 0), (x, img_height), line_color, line_thickness)
        
                # Display status (only for CAMERA input and not in Learning Mode)
                # Aligned to the BL-58 box-label render settings (draw_label_font_scale /
                # draw_label_thickness) so the status text matches the new, larger/bolder
                # box labels instead of the old tiny 0.5/1 that now looks inconsistent.
                status_font_scale = getattr(shared_state, "draw_label_font_scale", 0.6)
                status_thickness = getattr(shared_state, "draw_label_thickness", 2)
                if shared_state.status == 1:
                    cv2.putText(img, "Recording...", (50, 100), font, status_font_scale, (0, 0, 255), status_thickness)
                elif shared_state.status == 2:
                    cv2.putText(img, "Paused...", (50, 100), font, status_font_scale, (0, 255, 255), status_thickness)
        
        return img
