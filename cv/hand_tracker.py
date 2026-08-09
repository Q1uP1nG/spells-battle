import os
import urllib.request

from config import HAND_MODEL_PATH, HAND_MODEL_URL


def ensure_hand_model():
    if os.path.exists(HAND_MODEL_PATH):
        return HAND_MODEL_PATH

    print("Downloading MediaPipe hand landmarker model...")
    urllib.request.urlretrieve(HAND_MODEL_URL, HAND_MODEL_PATH)
    return HAND_MODEL_PATH


def get_hand_landmark_list(results):
    if results is None:
        return []
    if hasattr(results, "hand_landmarks") and results.hand_landmarks:
        return results.hand_landmarks
    return []
