from atomic_io import atomic_write, distinct_output
from PIL import Image
import io
"""
Mask Bridge - Inference Engine (Feb 2026)
Powered by RF-DETR (Roboflow Unified Segmentation)
"""
import os
import logging
import threading
import numpy as np
import cv2
import onnxruntime as ort
import sys
import unicodedata
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)

# Stable warning codes returned by process_image(). The plugin translates them
# (MaskBridgeDashboard.lua, EngineResult.warningText); keep both in step.
WARNING_UNKNOWN_CLASSES = "unknown_classes"            # details in "ignored_classes"
WARNING_NO_DETECTION = "no_detection"                  # empty mask written
WARNING_FINE_DETAIL_UNAVAILABLE = "fine_detail_unavailable"


# ---------------------------------------------------------------------------
# ONNX Runtime configuration
#
# Both helpers below are deliberate, measured choices that look like mistakes
# at a glance ("why is the Neural Engine off?", "why not use every core?").
# The reasoning lives in the docstrings so neither gets "fixed" by reflex.
# ---------------------------------------------------------------------------

def _intra_op_threads() -> int:
    """Performance-core count, not total core count.

    ORT sizes its intra-op pool from the total core count, so on Apple Silicon
    it also schedules onto the efficiency cores. A run finishes when its SLOWEST
    slice finishes, so the fast cores end up waiting on the slow ones. Measured
    on an M2 Pro (8P + 4E): 250 ms/image with the default 12 threads against
    218 ms pinned to the 8 performance cores.

    Windows uses a bounded budget for concurrent Lightroom exports. Intel Mac
    retains the previous logical CPU count. Neither is ORT's automatic mode.
    """
    if sys.platform == 'win32':
        # Leave room for Lightroom and three concurrent requests. On the
        # audited 4C/8T Windows host, four threads cut batch time by 15-26%.
        # The override is for measured deployments, bounded to available CPUs.
        cpus = os.process_cpu_count() or os.cpu_count() or 4
        try:
            requested = int(os.environ.get('MASKBRIDGE_ORT_THREADS', '4'))
        except ValueError:
            requested = 4
        return max(1, min(cpus, requested))
    if sys.platform == 'darwin':
        try:
            import ctypes
            import ctypes.util
            # find_library() is the clean path but has been known to come back
            # empty inside a frozen bundle; the absolute names are stable on
            # macOS, so try them rather than silently losing the pinning.
            candidates = [ctypes.util.find_library('c'), 'libSystem.dylib', '/usr/lib/libc.dylib']
            libc = None
            for name in candidates:
                if not name:
                    continue
                try:
                    libc = ctypes.CDLL(name)
                    break
                except OSError:
                    continue
            if libc is not None:
                value = ctypes.c_int32(0)
                size = ctypes.c_size_t(ctypes.sizeof(value))
                rc = libc.sysctlbyname(b"hw.perflevel0.logicalcpu",
                                       ctypes.byref(value), ctypes.byref(size), None, 0)
                if rc == 0 and value.value > 0:
                    return value.value
        except Exception:
            pass  # Intel Mac, or a sysctl that moved: fall through
    # Preserve the existing fallback on Intel macOS and other platforms.
    return os.cpu_count() or 4


def _providers() -> List[str]:
    """CPU only, deliberately: CoreML is a net loss on RF-DETR.

    RF-DETR's deformable cross-attention emits rank-6 tensors
    ({1,200,16,1,2,2}) and the CoreML API caps at rank 5, so the whole decoder
    — the expensive half of a DETR — is refused. The partitioner leaves 112
    nodes on CoreML against 227 on CPU, shredded into islands whose every
    boundary costs a tensor copy. Measured on an M2 Pro: 384 ms/image against
    218 ms CPU-only, and 8.8s against 0.5s to build the session.

    That rank limit is a CoreML API constraint rather than a hardware one, so
    no Apple Silicon generation changes the verdict. Note the gain is on engine
    startup and single-image latency (Preview): under the Dashboard's 3 parallel
    workers the two configurations measured level, because one image's CoreML
    work overlaps another's CPU work.

    MASKBRIDGE_ORT_PROVIDERS=coreml re-enables it, so untested hardware can be
    checked in the field without shipping a new binary.
    """
    if os.environ.get('MASKBRIDGE_ORT_PROVIDERS', '').strip().lower() == 'coreml':
        wanted = ['CoreMLExecutionProvider', 'CPUExecutionProvider']
        available = ort.get_available_providers()
        return [p for p in wanted if p in available] or ['CPUExecutionProvider']
    return ['CPUExecutionProvider']


def _session_options() -> ort.SessionOptions:
    """Session options shared by every model we load (RF-DETR and BiRefNet)."""
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.intra_op_num_threads = _intra_op_threads()
    return opts


# Singleton instance
_engine_instance: Optional['MaskBridgeEngine'] = None

def get_engine(model_dir: str) -> 'MaskBridgeEngine':
    """Get or create singleton engine instance."""
    global _engine_instance
    if _engine_instance is None or _engine_instance.model_dir != model_dir or not _engine_instance._models_loaded:
        _engine_instance = MaskBridgeEngine(model_dir)
        _engine_instance.load_models()
    return _engine_instance

# COCO class names (80 classes) - RF-DETR supports standard COCO
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]

# COCO 91-class to 80-class index mapping
# The 91-class format has index 0 = "background" (unlabeled)
# Categories 1-90 map to the 80 actual classes (some indices are skipped in original COCO)
COCO_91_TO_80 = {
    1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10,
    13: 11, 14: 12, 15: 13, 16: 14, 17: 15, 18: 16, 19: 17, 20: 18, 21: 19,
    22: 20, 23: 21, 24: 22, 25: 23, 27: 24, 28: 25, 31: 26, 32: 27, 33: 28,
    34: 29, 35: 30, 36: 31, 37: 32, 38: 33, 39: 34, 40: 35, 41: 36, 42: 37,
    43: 38, 44: 39, 46: 40, 47: 41, 48: 42, 49: 43, 50: 44, 51: 45, 52: 46,
    53: 47, 54: 48, 55: 49, 56: 50, 57: 51, 58: 52, 59: 53, 60: 54, 61: 55,
    62: 56, 63: 57, 64: 58, 65: 59, 67: 60, 71: 61, 72: 62, 73: 63, 74: 64,
    75: 65, 76: 66, 77: 67, 78: 68, 79: 69, 80: 70, 81: 71, 82: 72, 84: 73,
    85: 74, 86: 75, 87: 76, 88: 77, 89: 78, 90: 79
}

# Prompt to COCO class mapping (class indices from COCO_CLASSES)
# Supports both English and French keywords
PROMPT_TO_CLASSES = {
    # Humans
    "person": [0], "human": [0], "people": [0], "humain": [0], "humains": [0], "personne": [0],
    
    # Vehicles
    "car": [2], "cars": [2], "automobile": [2], "voiture": [2], "voitures": [2],
    "vehicle": [2, 3, 5, 6, 7], "véhicule": [2, 3, 5, 6, 7], "vehicule": [2, 3, 5, 6, 7],
    "truck": [7], "camion": [7],
    "bus": [5],
    "motorcycle": [3], "moto": [3], "motorbike": [3],
    "bicycle": [1], "bike": [1], "vélo": [1], "velo": [1],
    "train": [6],
    "airplane": [4], "plane": [4], "avion": [4],
    "boat": [8], "bateau": [8],
    
    # Animals
    "animal": [14, 15, 16, 17, 18, 19, 20, 21, 22, 23], "animaux": [14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
    "bird": [14], "oiseau": [14],
    "cat": [15], "chat": [15],
    "dog": [16], "chien": [16],
    "horse": [17], "cheval": [17],
    "sheep": [18], "mouton": [18],
    "cow": [19], "vache": [19],
    "elephant": [20], "éléphant": [20],
    "bear": [21], "ours": [21],
    "zebra": [22], "zèbre": [22], "zebre": [22],
    "giraffe": [23], "girafe": [23],
    
    # Furniture
    "furniture": [13, 56, 57, 59, 60, 61], "meuble": [13, 56, 57, 59, 60, 61], "meubles": [13, 56, 57, 59, 60, 61],
    "bench": [13], "banc": [13],
    "chair": [56], "chaise": [56],
    "couch": [57], "sofa": [57], "canapé": [57], "canape": [57],
    "bed": [59], "lit": [59],
    "table": [60], "dining table": [60],
    "toilet": [61], "toilette": [61], "toilettes": [61],
    
    # Electronics
    "electronics": [62, 63, 64, 65, 66, 67], "électronique": [62, 63, 64, 65, 66, 67],
    "tv": [62], "television": [62], "télé": [62], "tele": [62],
    "laptop": [63], "ordinateur": [63],
    "mouse": [64], "souris": [64],
    "remote": [65], "télécommande": [65], "telecommande": [65],
    "keyboard": [66], "clavier": [66],
    "phone": [67], "cell phone": [67], "téléphone": [67], "telephone": [67],
    
    # Accessories
    "backpack": [24], "sac à dos": [24], "sac a dos": [24],
    "umbrella": [25], "parapluie": [25],
    "handbag": [26], "sac à main": [26], "sac a main": [26],
    "tie": [27], "cravate": [27],
    "suitcase": [28], "valise": [28],
    
    # Sports
    "sports": [29, 30, 31, 32, 33, 34, 35, 36, 37, 38],
    "ball": [32], "ballon": [32], "sports ball": [32],
    "kite": [33], "cerf-volant": [33],  # Added for testing
    "skateboard": [36],
    "surfboard": [37],
    
    # Food & Kitchen
    "bottle": [39], "bouteille": [39],
    "cup": [41], "tasse": [41],
    "bowl": [45], "bol": [45],
    
    # Plants
    "plant": [58], "potted plant": [58], "plante": [58],
    "vegetation": [58], "végétation": [58],
    
    # Traffic
    "traffic light": [9], "feu": [9],
    "stop sign": [11], "panneau stop": [11],

    # ------------------------------------------------------------------
    # Full 1:1 coverage — every remaining COCO class is addressable by its
    # exact name, plus the EN synonyms promised in DETECTION_CLASSES_*.md
    # and FR equivalents (same convention as above).
    # ------------------------------------------------------------------
    # Street objects
    "fire hydrant": [10], "bouche d'incendie": [10], "borne incendie": [10],
    "parking meter": [12], "parcmètre": [12], "parcmetre": [12],

    # Sports & leisure
    "frisbee": [29],
    "skis": [30], "ski": [30],
    "snowboard": [31],
    "baseball bat": [34], "batte de baseball": [34], "batte": [34],
    "baseball glove": [35], "gant de baseball": [35],
    "tennis racket": [38], "raquette de tennis": [38], "raquette": [38],

    # Food & kitchen
    "wine glass": [40], "glass": [40], "verre à vin": [40], "verre a vin": [40], "verre": [40],
    "mug": [41],
    "fork": [42], "fourchette": [42],
    "knife": [43], "couteau": [43],
    "spoon": [44], "cuillère": [44], "cuillere": [44],
    "banana": [46], "banane": [46],
    "apple": [47], "pomme": [47],
    "sandwich": [48],
    "orange": [49],
    "broccoli": [50], "brocoli": [50],
    "carrot": [51], "carotte": [51],
    "hot dog": [52], "hot-dog": [52],
    "pizza": [53],
    "donut": [54], "beignet": [54],
    "cake": [55], "gâteau": [55], "gateau": [55],

    # Appliances
    "microwave": [68], "micro-ondes": [68], "micro ondes": [68],
    "oven": [69], "four": [69],
    "toaster": [70], "grille-pain": [70],
    "sink": [71], "évier": [71], "evier": [71], "lavabo": [71],
    "refrigerator": [72], "fridge": [72], "réfrigérateur": [72], "refrigerateur": [72], "frigo": [72],

    # Household objects
    "book": [73], "livre": [73],
    "clock": [74], "horloge": [74], "pendule": [74],
    "vase": [75],
    "scissors": [76], "ciseaux": [76],
    "teddy bear": [77], "plush": [77], "ours en peluche": [77], "peluche": [77],
    "hair drier": [78], "hair dryer": [78], "sèche-cheveux": [78], "seche-cheveux": [78],
    "toothbrush": [79], "brosse à dents": [79], "brosse a dents": [79],

    # Doc synonyms for already-mapped classes
    "computer": [63],
    "luggage": [28],
    "purse": [26],
}


class MaskBridgeEngine:
    """Unified Inference Engine for Mask Bridge (v2026).
    
    Components:
      - RF-DETR (Unified Segmentation) -> Single Pass Detection + Masking
    """
    
    # RF-DETR Medium uses 432x432
    INPUT_SIZE = 432
    
    # BiRefNet_lite refinement runs at 1024×1024 (its native training size).
    BIREFNET_SIZE = 1024

    # Working resolution for the class gate (see _gate_alpha).
    #
    # The gate is a dilated, heavily blurred binary mask — a deliberately
    # low-frequency shape — so computing it on the full frame buys nothing and
    # costs a lot: both the dilate and the blur use a kernel that is itself a
    # fraction of the long edge, so the cost grows with the square of the export
    # size. Measured on a 4096 px export: 753 ms, i.e. 17% of a whole Fine detail
    # image, against 17 ms at this working size, for a mask that differs by at
    # most 5/255 on 0.1% of its pixels.
    #
    # The practical effect is that Fine detail now costs the same whatever the
    # export resolution, which is what users already assume: BiRefNet itself
    # always runs at BIREFNET_SIZE regardless. Frames at or below this size are
    # not resized at all and keep their exact previous result.
    GATE_WORK_SIZE = 1024

    # Fine-detail region of interest. OFF by default — see the verdict below.
    #
    # The idea: BiRefNet always sees exactly BIREFNET_SIZE² pixels, so feeding it
    # the whole frame spends most of that budget on background. A subject filling
    # 30% of a 6000 px frame reaches the model at roughly 300 px, and no amount of
    # post-processing puts the hair back. Cropping to what RF-DETR already found
    # BEFORE the resize should buy strand-level detail.
    #
    # Verdict on a real 10-image set at the 4096 px export size actually used:
    #   - 8 of 10 images came out byte identical. The 70%-coverage fallback below
    #     catches every portrait, every crowd scene — i.e. exactly the pictures
    #     people reach for Fine detail on.
    #   - Of the 2 that changed, the car was visibly cleaner (wheel arch, mirror).
    #   - The dog was the problem: cropping resolves the individual grass blades
    #     crossing in front of the fur, which is more literal but leaves a busy,
    #     saw-toothed silhouette. As a Lightroom local-adjustment mask that reads
    #     as worse than the smooth boundary it replaces, and that is the call the
    #     product owner made after looking at both.
    # Every number pointed the other way (boundary-on-real-edge +8..12%, alpha
    # stretched 2.7x instead of 4.0x, and colour analysis showing it trades dark
    # grass pixels for mid-tone strand pixels). Measurements are not the customer's
    # eye: reach is small, one of two cases is a regression to that eye, so it
    # stays off and Fine detail behaves exactly as in 1.0. Flip to True to
    # re-evaluate on real client photos before considering it for 1.1.
    BIREFNET_ROI_ENABLED = False

    # Margin chosen by measurement, not by feel: hair routinely extends past the
    # coarse RF-DETR box, and too tight a crop clips it to alpha 0. A sweep over
    # 0.20/0.35/0.50/0.70 on subjects covering 20-45% of the frame showed 0.20
    # and 0.35 still regressing (-5.0% and -1.0% strand IoU at 35%), while 0.50
    # never lost anywhere and still gained +17% on a 20% subject. Larger margins
    # only give the density back.
    BIREFNET_ROI_MARGIN = 0.50           # context kept around the box, per side
    BIREFNET_MAX_ROIS = 3                # cost ceiling: one inference per ROI
    BIREFNET_ROI_KEEP_FRAC = 0.10        # ignore blobs under 10% of the largest
    BIREFNET_ROI_FULL_FRAME_FRAC = 0.70  # above this coverage, cropping buys nothing
    _IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    _IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, model_dir: str):
        self.model_dir = model_dir
        self.session: Optional[ort.InferenceSession] = None
        self._models_loaded = False
        # Optional fine-detail refinement model, loaded lazily on first use.
        # The lock serializes load/run/unload so the idle-unload (see
        # maybe_unload_birefnet) can never release a session mid-inference.
        self.birefnet_session: Optional[ort.InferenceSession] = None
        self._birefnet_fp16 = False
        self._birefnet_lock = threading.Lock()
        self._birefnet_last_used = 0.0
        
    def load_models(self):
        """Load RF-DETR ONNX model."""
        if self._models_loaded:
            return
            
        model_path = os.path.join(self.model_dir, "rfdetr_seg_medium.onnx")

        # CPU-only and performance-core-pinned by measurement, not by omission
        # (see _providers / _intra_op_threads).
        providers = _providers()
        logger.info("ONNX providers: %s | intra-op threads: %d",
                    ", ".join(providers), _intra_op_threads())

        if os.path.exists(model_path):
            try:
                self.session = ort.InferenceSession(model_path,
                                                    sess_options=_session_options(),
                                                    providers=providers)
                logger.info("RF-DETR loaded (Unified Segmentation)")
                self._models_loaded = True
                self._warmup()
            except Exception as e:
                err_str = str(e)
                logger.error(f"Error loading RF-DETR: {err_str}")
                if "INVALID_PROTOBUF" in err_str or "Protobuf parsing failed" in err_str or "Error parsing message" in err_str:
                    logger.error("ONNX model corrupted (likely LFS pointer or incomplete download).")
                    raise ValueError("Model is corrupted. Please reinstall Mask Bridge.")
                raise e
        else:
            logger.error("RF-DETR model missing!")
            raise ValueError("RF-DETR model missing! Please reinstall Mask Bridge.")

    def _warmup(self):
        """Run one dummy inference so EP compilation (CoreML) happens at load time.

        Without this, the first real image pays the provider compilation cost,
        which shows up as an unexplained multi-second outlier in batch timings.
        Failure is non-fatal: the first real inference will simply be slower.
        """
        try:
            import time
            start = time.time()
            blob = np.zeros((1, 3, self.INPUT_SIZE, self.INPUT_SIZE), dtype=np.float32)
            input_name = self.session.get_inputs()[0].name
            self.session.run(None, {input_name: blob})
            logger.info(f"Warm-up inference done in {time.time() - start:.2f}s")
        except Exception as e:
            logger.warning(f"Warm-up inference failed (non-fatal): {e}")

    @staticmethod
    def _guided_filter(guide, src, radius=8, eps=1e-4):
        """Edge-aware guided filter (He et al., 2010) built on box filters only.

        Refines the soft mask ``src`` so its boundaries follow the structures of the
        grayscale ``guide`` image. Uses cv2.boxFilter to avoid the opencv-contrib
        (ximgproc) dependency.
        """
        guide = guide.astype(np.float32)
        src = src.astype(np.float32)
        d = 2 * radius + 1
        ksize = (d, d)
        mean_I = cv2.boxFilter(guide, cv2.CV_32F, ksize)
        mean_p = cv2.boxFilter(src, cv2.CV_32F, ksize)
        corr_I = cv2.boxFilter(guide * guide, cv2.CV_32F, ksize)
        corr_Ip = cv2.boxFilter(guide * src, cv2.CV_32F, ksize)
        var_I = corr_I - mean_I * mean_I
        cov_Ip = corr_Ip - mean_I * mean_p
        a = cov_Ip / (var_I + eps)
        b = mean_p - a * mean_I
        mean_a = cv2.boxFilter(a, cv2.CV_32F, ksize)
        mean_b = cv2.boxFilter(b, cv2.CV_32F, ksize)
        return mean_a * guide + mean_b

    def _load_birefnet_locked(self) -> bool:
        """Lazily load the optional BiRefNet_lite refinement model.

        Caller must hold ``_birefnet_lock`` (load, inference and idle-unload are
        serialized on it). Returns True when the model is available.
        Missing/broken model is a soft failure: the caller keeps the standard
        RF-DETR mask path (hard mask, or guided filter when edge_refine was
        requested) so the feature degrades gracefully instead of crashing.
        """
        if self.birefnet_session is not None:
            return True
        model_path = os.path.join(self.model_dir, "birefnet_lite_fp16.onnx")
        if not os.path.exists(model_path):
            logger.warning("BiRefNet model missing — using guided-filter refinement")
            return False
        try:
            # BiRefNet's deform-conv substitution (GatherND/ScatterND) isn't
            # CoreML-friendly; CPU is what we validated (~5s @1024). Keep it CPU-only
            # for determinism and to avoid a CoreML compile fallback stall.
            # Same session options as RF-DETR: this used to be built with none at
            # all, so it ran without graph optimization and without core pinning.
            self.birefnet_session = ort.InferenceSession(
                model_path, sess_options=_session_options(),
                providers=['CPUExecutionProvider'])
            self._birefnet_fp16 = 'float16' in self.birefnet_session.get_inputs()[0].type
            self._warmup_birefnet()
            logger.info("BiRefNet loaded (fine-detail refinement)")
            return True
        except Exception as e:
            logger.error(f"Error loading BiRefNet: {e}")
            return False

    def _warmup_birefnet(self):
        """Run one dummy inference on BiRefNet so memory allocation happens at load time."""
        if self.birefnet_session is None:
            return
        try:
            import time
            start = time.time()
            blob = np.zeros((1, 3, self.BIREFNET_SIZE, self.BIREFNET_SIZE),
                            dtype=np.float16 if self._birefnet_fp16 else np.float32)
            input_name = self.birefnet_session.get_inputs()[0].name
            self.birefnet_session.run(None, {input_name: blob})
            logger.info(f"BiRefNet warm-up done in {time.time() - start:.2f}s")
        except Exception as e:
            logger.warning(f"BiRefNet warm-up failed (non-fatal): {e}")

    def _birefnet_alpha(self, image_bgr: np.ndarray) -> np.ndarray:
        """Run BiRefNet on one BGR image or crop -> alpha in [0,1] at its own size."""
        h, w = image_bgr.shape[:2]
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        x = cv2.resize(rgb, (self.BIREFNET_SIZE, self.BIREFNET_SIZE),
                       interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        x = (x - self._IMAGENET_MEAN) / self._IMAGENET_STD
        blob = x.transpose(2, 0, 1)[None]
        blob = blob.astype(np.float16 if self._birefnet_fp16 else np.float32)
        name = self.birefnet_session.get_inputs()[0].name
        out = self.birefnet_session.run(None, {name: blob})[0]
        alpha = out[0, 0].astype(np.float32)
        return cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LINEAR)

    @classmethod
    def plan_birefnet_rois(cls, coarse: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Boxes to run fine matting on. Empty list means "use the full frame".

        Each connected blob of the coarse mask becomes one padded box. Returning
        [] is the safe answer and is used whenever cropping cannot pay off: no
        detection, the subject scattered over more blobs than BIREFNET_MAX_ROIS,
        or boxes that already cover most of the frame.
        """
        h, w = coarse.shape[:2]
        binary = (coarse > 0.5).astype(np.uint8)
        num, _labels, stats, _c = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num <= 1:
            return []

        areas = stats[1:, cv2.CC_STAT_AREA]
        floor = cls.BIREFNET_ROI_KEEP_FRAC * float(areas.max())
        keep = [i + 1 for i, a in enumerate(areas) if a >= floor]
        if not keep or len(keep) > cls.BIREFNET_MAX_ROIS:
            return []

        boxes = []
        for i in keep:
            bx, by = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
            bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
            mx, my = int(bw * cls.BIREFNET_ROI_MARGIN), int(bh * cls.BIREFNET_ROI_MARGIN)
            x0, y0 = max(0, bx - mx), max(0, by - my)
            x1, y1 = min(w, bx + bw + mx), min(h, by + bh + my)
            if x1 > x0 and y1 > y0:
                boxes.append((x0, y0, x1, y1))
        if not boxes:
            return []

        covered = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
        if covered >= cls.BIREFNET_ROI_FULL_FRAME_FRAC * float(w * h):
            # One full-frame inference is cheaper and equivalent here.
            return []
        return boxes

    def _birefnet_alpha_roi(self, image_bgr: np.ndarray, coarse: np.ndarray) -> np.ndarray:
        """Fine alpha for the whole frame, matted per detection region.

        Pixels outside the regions stay at 0 — which is what the class gate would
        have zeroed anyway, so the downstream contract is unchanged.
        """
        h, w = image_bgr.shape[:2]
        # The switch lives here, at the decision, rather than inside the planner:
        # plan_birefnet_rois stays a pure function its tests can exercise either way.
        boxes = self.plan_birefnet_rois(coarse) if self.BIREFNET_ROI_ENABLED else []
        if not boxes:
            logger.info("BiRefNet: full-frame pass")
            return self._birefnet_alpha(image_bgr)

        full_budget = self.BIREFNET_SIZE / float(max(w, h))
        alpha = np.zeros((h, w), dtype=np.float32)
        for n, (x0, y0, x1, y1) in enumerate(boxes, 1):
            roi_budget = self.BIREFNET_SIZE / float(max(x1 - x0, y1 - y0))
            logger.info(f"BiRefNet ROI {n}/{len(boxes)}: {x1 - x0}x{y1 - y0} px "
                        f"({roi_budget / full_budget:.1f}x the full-frame detail budget)")
            patch_alpha = self._birefnet_alpha(image_bgr[y0:y1, x0:x1])
            alpha[y0:y1, x0:x1] = np.maximum(alpha[y0:y1, x0:x1], patch_alpha)
        return alpha

    def maybe_unload_birefnet(self, idle_seconds: float = 3600.0) -> bool:
        """Release the BiRefNet session after ``idle_seconds`` without use.

        The fine-detail model holds a few hundred MB of RAM but is only needed
        while the user actively works with the Fine detail mode; the server
        watchdog calls this periodically. Reload is lazy and transparent.
        Returns True when a session was actually released.
        """
        import time
        with self._birefnet_lock:
            if (self.birefnet_session is not None
                    and time.time() - self._birefnet_last_used > idle_seconds):
                self.birefnet_session = None
                logger.info("BiRefNet unloaded after inactivity (RAM released; "
                            "will reload lazily on next Fine detail use)")
                return True
        return False

    @classmethod
    def _gate_alpha(cls, coarse: np.ndarray, fine: np.ndarray,
                    dilate_frac: float = 0.02) -> np.ndarray:
        """Keep BiRefNet's fine alpha only where RF-DETR detected the object.

        BiRefNet is class-agnostic (it segments the salient subject); gating by the
        dilated RF-DETR mask restricts the fine matting to the requested class and
        suppresses BiRefNet firing on other salient objects in the frame.

        The gate itself is built at GATE_WORK_SIZE and stretched back up: it is a
        blurred blob, so the full-resolution version was paying a lot for detail it
        immediately destroyed. ``dilate_frac`` stays relative to the long edge, so
        the gate covers the same proportion of the frame either way.
        """
        h, w = coarse.shape
        scale = min(1.0, cls.GATE_WORK_SIZE / float(max(h, w)))
        if scale < 1.0:
            gw, gh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            work = cv2.resize(coarse, (gw, gh), interpolation=cv2.INTER_AREA)
        else:
            gh, gw, work = h, w, coarse

        k = max(3, int(round(dilate_frac * max(gh, gw))) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        gate = cv2.dilate((work > 0.3).astype(np.uint8), kernel)
        gate = cv2.GaussianBlur(gate.astype(np.float32), (k, k), 0)
        gate = np.clip(gate, 0.0, 1.0)

        if scale < 1.0:
            gate = cv2.resize(gate, (w, h), interpolation=cv2.INTER_LINEAR)
            # Bilinear cannot overshoot, but the unit-range contract is relied on
            # downstream (the alpha is scaled straight to uint8) — keep it explicit.
            gate = np.clip(gate, 0.0, 1.0)
        return fine * gate

    @staticmethod
    def _birefnet_coverage_ok(coarse: np.ndarray, gated: np.ndarray,
                              min_ratio: float = 0.3) -> bool:
        """Sanity check for the BiRefNet path: did the fine alpha keep the object?

        BiRefNet segments the *salient* subject; when the requested class is not
        salient (a chair in a busy room, a car in the background), the gated alpha
        collapses to near-empty — silently worse than the coarse RF-DETR mask.
        Require the gated area to cover at least ``min_ratio`` of the coarse area,
        otherwise the caller falls back to the coarse mask.
        """
        coarse_area = int(np.count_nonzero(coarse > 0.5))
        if coarse_area == 0:
            return False
        gated_area = int(np.count_nonzero(gated > 0.5))
        return gated_area >= min_ratio * coarse_area

    @staticmethod
    def resolve_target_classes(prompts: List[str]) -> set:
        """Map user prompts to COCO class indices.

        Prompts are NFC-normalized (macOS UI text can arrive NFD-decomposed,
        which would never match the accented keys) and matched case- and
        whitespace-insensitively. Raises ValueError when nothing maps, so the
        caller surfaces an actionable message instead of producing no output.
        """
        target_classes = set()
        for prompt in prompts:
            key = unicodedata.normalize('NFC', str(prompt)).strip().lower()
            if key in PROMPT_TO_CLASSES:
                target_classes.update(PROMPT_TO_CLASSES[key])

        if not target_classes:
            cleaned = ", ".join(str(p).strip() for p in prompts if str(p).strip()) or "(empty)"
            raise ValueError(
                f"No detectable class in prompts: {cleaned}. "
                "Use class names from 'View all classes' (e.g. person, car, dog)."
            )
        return target_classes

    def _preprocess_rfdetr(self, image):
        rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        resized = rgb.resize((self.INPUT_SIZE, self.INPUT_SIZE), Image.Resampling.BICUBIC)
        values = np.asarray(resized, dtype=np.float32) / 255.0
        values = (values - self._IMAGENET_MEAN) / self._IMAGENET_STD
        return np.ascontiguousarray(values.transpose(2, 0, 1)[None], dtype=np.float32)

    def process_image(self, image_path: str, output_path: str, prompts: List[str],
                      invert: bool = False, threshold: float = 0.35, smoothing: int = 0,
                      exclude_classes: List[str] = None, edge_refine: bool = False,
                      birefnet_refine: bool = False):
        """Main Pipeline (RF-DETR).

        The product default is a clean hard binary mask (fast mode).

        When edge_refine is True (API/CLI opt-in; no longer exposed in the UI),
        the soft mask is aligned to the image contours with a guided filter and
        rendered with an anti-aliased border.

        When birefnet_refine is True (the "Fine detail" mode), the RF-DETR mask
        is replaced by a BiRefNet matting-grade alpha, gated to the detected class.
        Slower (~+5s/image) but resolves individual hair/fur strands. If the
        BiRefNet model is unavailable, or its alpha barely covers the detected
        object (non-salient subject), the standard mask path is used instead.
        """
        import time
        logger.info(f"Processing (RF-DETR): {os.path.basename(image_path)}")
        timings = {}
        t_start = time.time()

        if not self._models_loaded or self.session is None:
            logger.error("Model not loaded")
            raise RuntimeError("Model not loaded — try restarting the AI server")

        # Resolve target classes first: an unmappable prompt fails fast with an
        # actionable error, before any file wait or inference work.
        target_classes = self.resolve_target_classes(prompts)
        unknown_prompts = []
        for prompt in prompts:
            try:
                self.resolve_target_classes([prompt])
            except ValueError:
                unknown_prompts.append(str(prompt))

        # Path resolution (Unicode-aware)

        # A path is an identity, not display text. In particular two visually
        # identical NFC/NFD names may contain different photographs on NTFS.
        candidates = [image_path]
        
        final_path = None

        # Retry mechanism (wait up to 3 seconds for file to appear/unlock)
        for i in range(6):
            for cand in candidates:
                if os.path.exists(cand):
                    final_path = cand
                    break
            if final_path:
                break
            time.sleep(0.5)
            logger.debug(f"Waiting for file... {i+1}/6")

        if not final_path:
             raise ValueError(f"File not found: {candidates[0]}")

        # Decoding IS the completeness check: a half-written file does not decode.
        #
        # This used to be preceded by an unconditional "file stability" wait —
        # read size, sleep 0.2s, read size again — paid by every image whether or
        # not anything was still writing. Measured on an M2 Pro that fixed sleep
        # was ~34% of the per-image time on a 2048px export, i.e. a third of every
        # batch spent asleep. It was also the weaker check: a truncated file whose
        # size had settled passed it and then failed to decode regardless.
        # imdecode is Unicode-safe on all platforms, unlike cv2.imread.
        image = None
        for attempt in range(4):
            try:
                with open(final_path, "rb") as f:
                    file_bytes = np.asarray(bytearray(f.read()), dtype=np.uint8)
                image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            except OSError as e:
                logger.debug(f"Error reading file stream: {e}")
            if image is not None:
                break
            if attempt < 3:
                logger.debug(f"Not decodable yet, retrying ({attempt + 1}/3)")
                time.sleep(0.25 * (attempt + 1))

        if image is None:
            # Last resort: a different decode path, in case imdecode is the problem
            image = cv2.imread(final_path)
            if image is None:
                raise ValueError(f"Cannot read: {final_path}")
        
        distinct_output(output_path, image_path)
        img_h, img_w = image.shape[:2]
        timings['read'] = time.time() - t_start
        t_mark = time.time()

        # Contract of PierreMarieCurie/rf-detr-onnx, RF-DETR Seg Medium:
        # square RGB bicubic resize, ImageNet mean/std, float32 NCHW.
        input_size = self.INPUT_SIZE
        new_h = new_w = input_size
        blob = self._preprocess_rfdetr(image)

        # 2. Inference
        input_name = self.session.get_inputs()[0].name
        # RF-DETR usually takes just the image
        outputs = self.session.run(None, {input_name: blob})
        timings['infer'] = time.time() - t_mark
        t_mark = time.time()

        # Map outputs by name
        output_names = [o.name for o in self.session.get_outputs()]
        output_dict = {name: out for name, out in zip(output_names, outputs)}

        # Support both old (small) and new (medium) output naming conventions
        if 'dets' in output_dict:
            # Medium model: correct names
            boxes_tensor = output_dict['dets'][0]        # Shape (200, 4)
            logits_tensor = output_dict['labels'][0]     # Shape (200, 91) - RAW LOGITS
            masks_tensor = output_dict['masks'][0]       # Shape (200, 108, 108)
        else:
            # Small model: swapped names (misleading export)
            boxes_tensor = output_dict['pred_masks'][0]  # Shape (100, 4)
            logits_tensor = output_dict['pred_boxes'][0] # Shape (100, 91) - RAW LOGITS
            masks_tensor = output_dict['pred_logits'][0] # Shape (100, 96, 96)
        
        # Convert logits to probabilities using sigmoid
        def sigmoid(x):
            return 1.0 / (1.0 + np.exp(-np.clip(x, -80, 80)))
        
        scores_tensor = sigmoid(logits_tensor)  # Now in [0, 1] range

        # 3. Filter & Aggregate
        # Soft masks are combined at canvas resolution (INPUT_SIZE²) and
        # upsampled ONCE after the loop: a full-resolution resize per detection
        # was the dominant post-inference cost on many-object images.
        # max-then-resize vs resize-then-max only differ within bilinear
        # interpolation error at overlap borders.
        combined_canvas = np.zeros((input_size, input_size), dtype=np.float32)

        exclude_set = set()
        if exclude_classes:
            for excluded in exclude_classes:
                if excluded and excluded.strip():
                    exclude_set.update(COCO_CLASSES[index] for index in self.resolve_target_classes([excluded]))

        count = 0
        
        # Iterate detections (RF-DETR Medium outputs 200 queries)
        for i in range(len(scores_tensor)):
            # Get max score and class (scores are already sigmoid'ed)
            class_scores = scores_tensor[i]
            
            # Find best class (excluding index 0 which is background in 91-class format)
            # Skip index 0 (background)
            class_idx_91 = np.argmax(class_scores[1:]) + 1  # +1 because we skipped index 0
            score = float(class_scores[class_idx_91])
            
            # Convert from 91-class to 80-class index using lookup table
            class_idx = COCO_91_TO_80.get(class_idx_91, -1)
            
            if score < threshold:
                continue
            
            # Validate class index is in valid range
            if class_idx < 0 or class_idx >= len(COCO_CLASSES):
                continue
                
            if class_idx not in target_classes:
                continue
                
            class_name = COCO_CLASSES[class_idx]
            if class_name in exclude_set:
                continue
                
            # Valid detection!
            count += 1
            logger.debug(f"  Detection {count}: {class_name} (score: {score:.3f})")
            
            # Extract mask (model-native resolution: 108×108 for Medium)
            raw_mask = masks_tensor[i]

            # Apply sigmoid to mask values (they are logits)
            mask_sigmoid = 1.0 / (1.0 + np.exp(-np.clip(raw_mask, -80, 80)))

            # Resize the mask to input_size (model-native 108² -> 432²)
            mh, mw = mask_sigmoid.shape

            if mh != input_size:
                mask_canvas = cv2.resize(mask_sigmoid.astype(np.float32), (input_size, input_size))
            else:
                mask_canvas = mask_sigmoid.astype(np.float32)

            # Accumulate at canvas resolution; padding crop + full-resolution
            # upsample happen once after the loop.
            combined_canvas = np.maximum(combined_canvas, mask_canvas)

        logger.info(f"Found {count} objects")

        # Single upsample: crop the letterbox padding, resize to the original
        # image dimensions, then derive the binary mask. (a>0.5)|(b>0.5) is
        # exactly max(a,b)>0.5, so this matches the previous per-mask threshold.
        if count > 0:
            soft_crop = combined_canvas[:new_h, :new_w]
            combined_soft = cv2.resize(soft_crop, (img_w, img_h), interpolation=cv2.INTER_LINEAR)
        else:
            combined_soft = np.zeros((img_h, img_w), dtype=np.float32)
        combined_mask = (combined_soft > 0.5).astype(np.uint8) * 255
        timings['masks'] = time.time() - t_mark
        t_mark = time.time()

        # 4. Post-Process
        # Fine-detail refinement (optional): replace the coarse RF-DETR mask with a
        # BiRefNet matting-grade alpha, gated to the detected class. Supersedes the
        # guided filter. Soft-failure to the standard mask path if unavailable or
        # if the gated alpha barely covers the detection (see _birefnet_coverage_ok).
        use_birefnet = False
        if birefnet_refine and combined_soft.max() > 0.0:
            # Load + run under the lock so the idle-unload can't release the
            # session between the two.
            with self._birefnet_lock:
                if self.birefnet_session is not None or self._load_birefnet_locked():
                    use_birefnet = True
                    logger.info("BiRefNet fine-detail refinement")
                    # Matte the detected regions rather than the whole frame:
                    # BiRefNet's fixed 1024² budget is spent on the subject
                    # instead of the background (see BIREFNET_ROI_* above).
                    fine = self._birefnet_alpha_roi(image, combined_soft)
                    self._birefnet_last_used = time.time()
        if use_birefnet:
            gated = self._gate_alpha(combined_soft, fine)
            if self._birefnet_coverage_ok(combined_soft, gated):
                combined_mask = (np.clip(gated, 0.0, 1.0) * 255.0).astype(np.uint8)
                # A soft anti-aliased mask was produced -> take the soft downstream
                # path (feathered hole-fill) just like the guided-filter branch.
                use_refine = True
            else:
                # BiRefNet matted something else (its subject is saliency-driven);
                # shipping the near-empty gated alpha would silently be WORSE than
                # the coarse mask. Keep the standard mask instead.
                logger.warning("BiRefNet alpha barely covers the detected object "
                               "(non-salient subject?) — keeping the standard mask")
                use_birefnet = False
        # Edge refinement: align the mask border to image contours (guided filter)
        # and render a soft anti-aliased edge. Falls back to the legacy binary mask
        # when disabled or when nothing was detected.
        if not use_birefnet:
            use_refine = edge_refine and combined_soft.max() > 0.0
        if use_refine and not use_birefnet:
            guide = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            # Conservative radius/feather: a large radius bleeds the mask into the
            # background along contours (esp. backlit hair vs dark wood). ~0.005 of the
            # short edge keeps the contour-following benefit without the fringing.
            radius = max(4, int(round(min(img_h, img_w) * 0.005)))
            refined = self._guided_filter(guide, combined_soft, radius=radius, eps=1e-4)
            feather = 0.10
            lo, hi = 0.5 - feather, 0.5 + feather
            t = np.clip((refined - lo) / (hi - lo), 0.0, 1.0)
            combined_mask = (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8)

        if invert: combined_mask = 255 - combined_mask

        if smoothing > 0 and use_birefnet:
            # Blurring a matting-grade alpha would destroy the very hair/fur
            # strands the fine-detail mode just resolved.
            logger.debug("Smoothing skipped in fine-detail mode (preserves matting strands)")
        elif smoothing > 0:
            k = int(smoothing * 2) + 1
            combined_mask = cv2.GaussianBlur(combined_mask, (k, k), 0)
            if not use_refine:
                _, combined_mask = cv2.threshold(combined_mask, 127, 255, cv2.THRESH_BINARY)

        # No automatic hole filling: small holes and disconnected details can be real.

        timings['refine'] = time.time() - t_mark
        t_mark = time.time()

        # Unicode-safe write: use imencode + binary write instead of imwrite
        success, encoded = cv2.imencode('.png', combined_mask)
        if success:
            output_normalized = output_path
            distinct_output(output_normalized, image_path)
            atomic_write(output_normalized, encoded.tobytes())
            logger.info(f"Saved mask: {output_path}")
        else:
            raise ValueError(f"Failed to encode mask for: {output_path}")

        timings['encode'] = time.time() - t_mark
        # Per-stage breakdown so batch slowness can be attributed (read = file
        # wait + decode, refine = guided filter or BiRefNet pass).
        logger.info("Timing: " + " ".join(f"{k}={v:.2f}s" for k, v in timings.items())
                    + f" total={time.time() - t_start:.2f}s")
        if sys.stdout:
            sys.stdout.flush()
        # Warnings are stable codes (WARNING_* above), translated by the plugin:
        # English text from here showed up untranslated in a localized UI.
        warnings = []
        if unknown_prompts:
            logger.warning("Ignored unknown classes: " + ", ".join(unknown_prompts))
            warnings.append(WARNING_UNKNOWN_CLASSES)
        if not count:
            # The empty mask is still written: it is the right mask for a photo
            # without the subject, and File > Export keeps its rendition. The
            # caller counts it apart from the masks that contain something.
            logger.warning("No matching objects detected")
            warnings.append(WARNING_NO_DETECTION)
        if birefnet_refine and count and not use_birefnet:
            logger.warning("Fine detail unavailable or rejected; standard mask retained")
            warnings.append(WARNING_FINE_DETAIL_UNAVAILABLE)
        return {"detections": count, "mode_requested": "fine_detail" if birefnet_refine else "standard",
                "mode_applied": "fine_detail" if use_birefnet else ("edge_refine" if use_refine else "standard"),
                "warnings": warnings, "ignored_classes": unknown_prompts}

    def create_comparison_image(self, image_path: str, mask_path: str, output_path: str):
        """Create a side-by-side comparison: original (left) | masked result (right)."""
        distinct_output(output_path, image_path, mask_path)
        # Unicode-safe read for both image and mask
        image = None
        mask = None
        try:
            img_path = image_path
            with open(img_path, 'rb') as f:
                image = cv2.imdecode(np.asarray(bytearray(f.read()), dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            image = cv2.imread(image_path)

        try:
            msk_path = mask_path
            with open(msk_path, 'rb') as f:
                mask = cv2.imdecode(np.asarray(bytearray(f.read()), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        except Exception:
            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

        if image is None or mask is None:
            return

        # Resize mask to match image if needed
        if mask.shape[:2] != image.shape[:2]:
            mask = cv2.resize(mask, (image.shape[1], image.shape[0]))

        # Right side: highlight masked areas, dim the rest.
        # Use the mask as a continuous alpha (NOT a >127 threshold) so the soft,
        # contour-aware border from edge refinement stays visible in the preview —
        # thresholding here would collapse a feathered edge to the same hard
        # outline as the legacy mask, hiding the difference between the two modes.
        alpha = (mask.astype(np.float32) / 255.0)[..., None]
        right = (image.astype(np.float32) * (0.3 + 0.7 * alpha)).astype(np.uint8)

        # Side-by-side: original | masked
        combined = np.hstack([image, right])

        # Unicode-safe write
        success, encoded = cv2.imencode('.jpg', combined, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if success:
            out_path = output_path
            atomic_write(out_path, encoded.tobytes())
            logger.info(f"Saved comparison: {output_path}")
        sys.stdout.flush()

    @staticmethod
    def process_matte_to_alpha(input_path: str, output_path: str, invert: bool = False,
                               reference_path: str = None):
        """Convert a Lightroom matte render (black bg / white mask) to a grayscale PNG mask.

        Estimated binary silhouette using an adaptive threshold. This is not a
        lossless extraction of Lightroom's native soft mask or opacity.
        Two-pass mode: when reference_path is provided, computes abs(matte - reference)
        to isolate mask regions regardless of original pixel brightness.
        Output format matches RF-DETR masks: grayscale PNG (white=mask, black=background).
        """
        def _read_grayscale(path):
            img = None
            try:
                norm = path
                with open(norm, 'rb') as f:
                    img = cv2.imdecode(np.asarray(bytearray(f.read()), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            except Exception:
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            return img

        distinct_output(output_path, input_path, reference_path)
        img_gray = _read_grayscale(input_path)
        if img_gray is None:
            raise ValueError(f"Cannot read matte image: {input_path}")

        # Two-pass difference mode: compare matte render vs reference (globals-only)
        two_pass = False
        if reference_path:
            ref_gray = _read_grayscale(reference_path)
            if ref_gray is None:
                raise ValueError("Cannot read requested reference image")
            else:
                if ref_gray.shape != img_gray.shape:
                    ref_gray = cv2.resize(ref_gray, (img_gray.shape[1], img_gray.shape[0]))
                diff = np.abs(img_gray.astype(np.int16) - ref_gray.astype(np.int16)).astype(np.uint8)
                logger.debug(f"Two-pass difference: min={diff.min()}, max={diff.max()}, mean={diff.mean():.1f}")
                img_gray = diff
                two_pass = True

        # 2. Adaptive threshold using Otsu on non-black pixels only.
        if two_pass:
            # In difference mode, values are small but non-zero for masked pixels.
            # JPEG compression noise produces differences of ~1, so floor at 2.
            nonblack_pixels = img_gray[img_gray > 1]
            if len(nonblack_pixels) > 0:
                otsu_thresh, _ = cv2.threshold(nonblack_pixels, 0, 255,
                                               cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                thresh = max(int(otsu_thresh), 2)
            else:
                thresh = 2
            logger.debug(f"Difference threshold: {thresh} (Otsu on {len(nonblack_pixels)} non-black pixels)")
        else:
            # Single-pass mode: brightness clusters A(~0-30), B(~60-150), C(~180-255)
            nonblack_pixels = img_gray[img_gray > 10]
            if len(nonblack_pixels) > 0:
                otsu_thresh, _ = cv2.threshold(nonblack_pixels, 0, 255,
                                               cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                thresh = max(int(otsu_thresh), 128)
            else:
                thresh = 128
            logger.debug(f"Matte threshold: {thresh} (Otsu on {len(nonblack_pixels)} non-black pixels)")

        # 3. Apply adaptive threshold
        _, binary = cv2.threshold(img_gray, thresh, 255, cv2.THRESH_BINARY)

        # Keep every component and hole. Area-based deletion cannot distinguish
        # a small real subject from noise; cleanup must never be unconditional.

        if invert:
            binary = cv2.bitwise_not(binary)

        # Save as grayscale PNG (same format as RF-DETR masks)
        success, encoded = cv2.imencode('.png', binary)
        if success:
            out_path = output_path
            atomic_write(out_path, encoded.tobytes())
            logger.info(f"Saved grayscale matte mask: {output_path}")
        else:
            raise ValueError(f"Failed to encode matte mask: {output_path}")
        sys.stdout.flush()

    @staticmethod
    def merge_rgb_mask_to_rgba(rgb_path: str, mask_path: str, output_path: str):
        """Merge an RGB image and a grayscale mask into a 32-bit RGBA PNG.

        The mask acts as the alpha channel: white (255) = fully opaque,
        black (0) = fully transparent.

        Args:
            rgb_path: Path to the clean RGB source image (PNG or JPEG)
            mask_path: Path to the grayscale mask (white=keep, black=remove)
            output_path: Path for the output 32-bit RGBA PNG
        """
        def _read_image(path, flags=cv2.IMREAD_COLOR):
            img = None
            try:
                norm = path
                with open(norm, 'rb') as f:
                    img = cv2.imdecode(np.asarray(bytearray(f.read()), dtype=np.uint8), flags)
            except Exception:
                img = cv2.imread(path, flags)
            return img

        distinct_output(output_path, rgb_path, mask_path)
        rgb = _read_image(rgb_path, cv2.IMREAD_COLOR)
        if rgb is None:
            raise ValueError(f"Cannot read RGB image: {rgb_path}")

        mask = _read_image(mask_path, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"Cannot read mask image: {mask_path}")

        # Resize mask to match RGB if dimensions differ
        if mask.shape[:2] != rgb.shape[:2]:
            logger.debug(f"Resizing mask {mask.shape[:2]} → {rgb.shape[:2]}")
            mask = cv2.resize(mask, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

        # Preserve the computed alpha exactly; unconditional blur erases strands.

        # Split BGR channels and merge with mask as alpha
        b, g, r = cv2.split(rgb)
        rgba = cv2.merge([b, g, r, mask])

        # Carry the source RGB profile into the PNG. OpenCV alone discards it,
        # which changes how Adobe RGB/ProPhoto exports are displayed elsewhere.
        with Image.open(rgb_path) as source:
            profile = source.info.get("icc_profile")
        rgba_image = Image.fromarray(cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA))
        buffer = io.BytesIO()
        rgba_image.save(buffer, format="PNG", icc_profile=profile)
        atomic_write(output_path, buffer.getvalue())
        logger.info(f"Saved RGBA PNG: {output_path}")
        if sys.stdout:
            sys.stdout.flush()



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Mask Bridge Engine - RF-DETR Ready")
