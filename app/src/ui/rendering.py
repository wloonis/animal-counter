"""
Rendering module for the pig counting application.

This module handles visualization of tracking and counting results.
"""

import cv2
import numpy as np
import datetime
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
    
    def __init__(self, draw_box=False):
        """
        Initialize the rendering object.
        
        Args:
            draw_box (bool, optional): Whether to draw tracking. Defaults to False.
        """
        self.draw_tracking = draw_box
        self.centroid_tracking = True
        self.box_tracking = True
        self.buttons = {}
        
        self.btn_learning_on, self.btn_learning_on_inv_alpha, self.btn_learning_on_size = self.load_button("/app/img/learning_on.png")
        self.btn_learning_off, self.btn_learning_off_inv_alpha, self.btn_learning_off_size = self.load_button("/app/img/learning_off.png")
        self.btn_auto_on, self.btn_auto_on_inv_alpha, self.btn_auto_on_size = self.load_button("/app/img/auto_on.png")
        self.btn_auto_off, self.btn_auto_off_inv_alpha, self.btn_auto_off_size = self.load_button("/app/img/auto_off.png")
        self.btn_reset, self.btn_reset_inv_alpha, self.btn_reset_size = self.load_button("/app/img/reset.png")
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
    
    def plot_one_box(self, x, img, color=None, label=None, line_thickness=None):
        """
        Plot one bounding box on the image.
        
        Args:
            x (list): Bounding box coordinates [x1, y1, x2, y2].
            img (numpy.ndarray): Image to plot on.
            color (list, optional): Color for the bounding box. Defaults to random.
            label (str, optional): Label for the bounding box. Defaults to None.
            line_thickness (int, optional): Thickness of the bounding box line. Defaults to 1.
        """
        tl = line_thickness or 1
        color = color or [np.random.randint(0, 255) for _ in range(3)]
        c1, c2 = (int(x[0]), int(x[1])), (int(x[2]), int(x[3]))
        cv2.rectangle(img, c1, c2, color, thickness=tl, lineType=cv2.LINE_AA)
        if label:
            tf = max(tl - 1, 1)
            t_size = cv2.getTextSize(label, 0, fontScale=tl / 3, thickness=tf)[0]
            c2 = c1[0] + t_size[0], c1[1] - t_size[1] - 3
            cv2.rectangle(img, c1, c2, color, -1, cv2.LINE_AA)
            cv2.putText(
                img,
                label,
                (c1[0], c1[1] - 2),
                0,
                tl / 3,
                [225, 255, 255],
                thickness=tf,
                lineType=cv2.LINE_AA,
            )
    
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
        # 🎮 BOUTON PLAY/PAUSE/STOP (SPRITE UNIQUE)
        # =========================
        x = margin_x
        y = margin_y

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
            h_btn, w_btn = btn.shape[:2]

            scale = base_width / w_btn
            new_w = int(w_btn * scale)
            new_h = int(h_btn * scale)

            btn_resized = cv2.resize(btn, (new_w, new_h))
            inv_resized = cv2.resize(inv, (new_w, new_h))

            # garder le canal alpha
            if len(inv_resized.shape) == 2:
                inv_resized = inv_resized[:, :, None]

            self.overlay_alpha(img, btn_resized, inv_resized, x, y)

            # découpage zones (3 boutons dans le sprite)
            third = new_w // 3

            self.buttons["play"] = (x, y, x + third, y + new_h)
            self.buttons["pause"] = (x + third, y, x + 2 * third, y + new_h)
            self.buttons["stop"] = (x + 2 * third, y, x + new_w, y + new_h)

        # =========================
        # BOUTON LEARNING
        # =========================
        x_learning = w - base_width // 3 - margin_x

        if shared_state.learning_mode:
            btn = self.btn_learning_on
            inv = self.btn_learning_on_inv_alpha
        else:
            btn = self.btn_learning_off
            inv = self.btn_learning_off_inv_alpha

        if btn is not None:
            h_btn, w_btn = btn.shape[:2]

            scale = (base_width // 3) / w_btn
            new_w = int(w_btn * scale)
            new_h = int(h_btn * scale)

            btn_resized = cv2.resize(btn, (new_w, new_h))
            inv_resized = cv2.resize(inv, (new_w, new_h))

            if len(inv_resized.shape) == 2:
                inv_resized = inv_resized[:, :, None]

            self.overlay_alpha(img, btn_resized, inv_resized, x_learning, y)

            self.buttons["learning"] = (x_learning, y, x_learning + new_w, y + new_h)

        # =========================
        # BOUTON AUTO
        # =========================
        x_auto = w - base_width // 3 * 3 - margin_x

        if shared_state.auto_mode:
            btn = self.btn_auto_on
            inv = self.btn_auto_on_inv_alpha
        else:
            btn = self.btn_auto_off
            inv = self.btn_auto_off_inv_alpha

        if btn is not None:
            h_btn, w_btn = btn.shape[:2]

            scale = (base_width // 3) / w_btn
            new_w = int(w_btn * scale)
            new_h = int(h_btn * scale)

            btn_resized = cv2.resize(btn, (new_w, new_h))
            inv_resized = cv2.resize(inv, (new_w, new_h))

            if len(inv_resized.shape) == 2:
                inv_resized = inv_resized[:, :, None]

            self.overlay_alpha(img, btn_resized, inv_resized, x_auto, y)

            self.buttons["auto"] = (x_auto, y, x_auto + new_w, y + new_h)

        return img

    def handle_click(self, x, y, shared_state):

        for name, (x1, y1, x2, y2) in self.buttons.items():

            if x1 <= x <= x2 and y1 <= y <= y2:

                if name == "learning":
                    shared_state.learning_mode = not shared_state.learning_mode

                    if not shared_state.learning_mode:
                        shared_state.status = 0

                elif name == "auto":

                    shared_state.auto_mode = not shared_state.auto_mode

                    if shared_state.auto_mode:
                        shared_state.status = 3
                        shared_state.delay_reinit = datetime.datetime.now()
                    else:
                        shared_state.status = 0


                elif name == "play":

                    if shared_state.status != 1:
                        shared_state.status = 1
                        shared_state.delay_reinit = datetime.datetime.now()

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
        x = img_width // 2
        text_position = (x + 20, 100)
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 3.0
        font_color = (125, 0, 0)
        font_thickness = 2
        text = str(counter_to_right)
        
        # Display recording message in Learning Mode (only for CAMERA input)
        if input_type == "CAMERA" and shared_state:
            
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
                if shared_state.status == 1:
                    cv2.putText(img, "Recording...", (50, 100), font, 0.5, (0, 0, 255), 1)
                elif shared_state.status == 2:
                    cv2.putText(img, "Paused...", (50, 100), font, 0.5, (0, 255, 255), 1)
        
        return img
