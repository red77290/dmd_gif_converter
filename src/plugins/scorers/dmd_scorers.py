import numpy as np
from typing import Optional, Tuple
from src.engine.auto_action.interfaces import IScorer

class DMDVisibilityScore(IScorer):
    """Evaluates how clearly forms are visible on the DMD (DMD Visibility)."""
    @staticmethod
    def compute(dmd_frame: np.ndarray, subject_dmd_rect: Optional[Tuple[int, int, int, int]] = None) -> float:
        import cv2

        if dmd_frame is None or dmd_frame.size == 0:
            return 0.0

        gray_dmd = cv2.cvtColor(dmd_frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray_dmd, 10, 255, cv2.THRESH_BINARY)
        non_black_pixels = np.sum(thresh > 0)
        total_pixels = dmd_frame.shape[0] * dmd_frame.shape[1]
        non_black_ratio = non_black_pixels / total_pixels if total_pixels > 0 else 0.0

        sobelx = cv2.Sobel(gray_dmd, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray_dmd, cv2.CV_64F, 0, 1, ksize=3)
        gradient_magnitude = np.sqrt(sobelx**2 + sobely**2)
        mean_gradient = np.mean(gradient_magnitude)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour_length = sum(cv2.arcLength(c, True) for c in contours)
        frame_perimeter = 2 * (dmd_frame.shape[0] + dmd_frame.shape[1])
        contour_density = contour_length / frame_perimeter if frame_perimeter > 0 else 0.0

        coords = np.argwhere(thresh > 0)
        if coords.size > 0:
            y_min, x_min = coords.min(axis=0)
            y_max, x_max = coords.max(axis=0)
            occupied_width = x_max - x_min + 1
            occupied_height = y_max - y_min + 1
            h_occupation = occupied_width / dmd_frame.shape[1]
            v_occupation = occupied_height / dmd_frame.shape[0]
        else:
            h_occupation = 0.0
            v_occupation = 0.0

        w_non_black = 0.3
        w_contrast = 0.4
        w_contour_density = 0.2
        w_occupation = 0.1

        base_score = (
            w_non_black * non_black_ratio +
            w_contrast * (mean_gradient / 255.0) +
            w_contour_density * contour_density +
            w_occupation * ((h_occupation + v_occupation) / 2.0)
        )

        subject_visibility_bonus = 0.0
        if subject_dmd_rect is not None:
            sx, sy, sw, sh = subject_dmd_rect
            sub_h_ratio = sh / dmd_frame.shape[0] if dmd_frame.shape[0] > 0 else 0
            sub_w_ratio = sw / dmd_frame.shape[1] if dmd_frame.shape[1] > 0 else 0
            
            if 0.3 < sub_h_ratio < 0.9:
                subject_visibility_bonus += 0.2
            if 0.1 < sub_w_ratio < 0.6:
                subject_visibility_bonus += 0.1
                
            if sx >= 0 and sy >= 0 and sx+sw <= dmd_frame.shape[1] and sy+sh <= dmd_frame.shape[0]:
                sub_grad = gradient_magnitude[sy:sy+sh, sx:sx+sw]
                if sub_grad.size > 0:
                    sub_mean_grad = float(np.mean(sub_grad))
                    if sub_mean_grad > mean_gradient * 1.2:
                        subject_visibility_bonus += 0.1

        return min(1.0, float(base_score + subject_visibility_bonus))


class DMDReadabilityScore(IScorer):
    """Evaluates how understandable and legible the forms are (DMD Readability)."""
    @staticmethod
    def compute(dmd_frame: np.ndarray) -> float:
        import cv2

        if dmd_frame is None or dmd_frame.size == 0:
            return 0.0

        gray_dmd = cv2.cvtColor(dmd_frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Local Contrast (Standard Deviation)
        std_dev = float(np.std(gray_dmd))
        contrast_score = min(1.0, std_dev / 80.0) 
        
        # 2. Separation of shapes
        _, thresh = cv2.threshold(gray_dmd, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh, connectivity=8)
        
        if num_labels > 1:
            valid_shapes = sum(1 for stat in stats[1:] if stat[cv2.CC_STAT_AREA] > 5)
            if valid_shapes == 0:
                shape_score = 0.2
            elif valid_shapes < 5:
                shape_score = 1.0
            elif valid_shapes < 15:
                shape_score = 0.6
            else:
                shape_score = 0.3
        else:
            shape_score = 0.1
            
        readability_score = 0.6 * contrast_score + 0.4 * shape_score
        return min(1.0, readability_score)


class SceneChangeScore(IScorer):
    """Detects cuts and hard scene transitions."""
    @staticmethod
    def compute(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        import cv2
        try:
            if frame_a is None or frame_b is None:
                return 1.0

            small_a = cv2.resize(frame_a, (64, 32), interpolation=cv2.INTER_AREA)
            small_b = cv2.resize(frame_b, (64, 32), interpolation=cv2.INTER_AREA)

            hsv_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2HSV)
            hsv_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2HSV)

            scores = []
            for ch in (0, 2):   # H, V
                hist_a = cv2.calcHist([hsv_a], [ch], None, [32], [0, 256])
                hist_b = cv2.calcHist([hsv_b], [ch], None, [32], [0, 256])
                cv2.normalize(hist_a, hist_a)
                cv2.normalize(hist_b, hist_b)
                corr = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
                scores.append(float(corr))

            gray_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY)
            gray_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray_a, gray_b)
            mean_diff = float(np.mean(diff)) / 255.0
            struct_sim = max(0.0, 1.0 - mean_diff * 2.0)
            
            hist_sim = max(0.0, float(np.mean(scores)))

            return 0.5 * hist_sim + 0.5 * struct_sim
        except Exception:
            return 1.0
