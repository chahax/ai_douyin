"""CPU face/landmark driven first-frame composition, without video trimming.

YuNet is used only as a detector. Ambiguity produces evidence, not a crop.
Coordinates are derived by inverse affine transforms, never by shot-specific
pixel constants. The original image orientation and all original files remain.
"""
from pathlib import Path
import hashlib
import json
import math

import cv2
import numpy as np
from PIL import Image, __version__ as PILLOW_VERSION
from . import visual_opening_frame as opening

METHOD = 'opencv_yunet_rotation_consensus/v1'
MODEL_SHA = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
ANGLES = (-90, -60, -30, 0, 30, 60, 90, 180)
SCORE_THRESHOLD = .85
MIN_ANGLES = 2
RESAMPLER = 'PIL.Image.Resampling.LANCZOS'


def binding(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def checked(value):
    if binding(value['path']) != value:
        raise ValueError('bound_crop_input_changed')
    return Path(value['path'])


def freeze(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('existing_crop_evidence_changed')
    else:
        with path.open('x', encoding='utf-8') as output:
            output.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return binding(path)


def validate_contract(contract):
    beat = contract.get('opening_camera_beat', {})
    if (contract.get('schema') != opening.SCHEMA or contract.get('policy') != opening.POLICY
            or beat.get('framing') != 'face_close' or beat.get('start') != 0
            or beat.get('cut') is not False or len(beat.get('actors', {})) != 1
            or contract.get('opening_visible_actors') != sorted(beat['actors'])):
        raise ValueError('single_subject_first_camera_beat_face_close_required')


def rotation(width, height, angle):
    """Return an expanded-canvas source->detector transform and its inverse."""
    transform = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.)
    cosine, sine = abs(transform[0, 0]), abs(transform[0, 1])
    target = (math.ceil(width * cosine + height * sine),
              math.ceil(height * cosine + width * sine))
    transform[0, 2] += (target[0] - width) / 2
    transform[1, 2] += (target[1] - height) / 2
    return transform, cv2.invertAffineTransform(transform), target


def points_transform(points, affine):
    points = np.asarray(points, dtype=float)
    return np.column_stack((points, np.ones(len(points)))) @ np.asarray(affine).T


def landmark_geometry(points, box):
    """Five-point ordering and proportions in the upright detector canvas."""
    p = np.asarray(points, dtype=float)
    x, y, width, height = map(float, box)
    if p.shape != (5, 2) or not np.isfinite(p).all() or min(width, height) <= 0:
        return False
    if np.any(p[:, 0] < x - .15 * width) or np.any(p[:, 0] > x + 1.15 * width):
        return False
    if np.any(p[:, 1] < y - .15 * height) or np.any(p[:, 1] > y + 1.15 * height):
        return False
    eyes, mouth = p[1] - p[0], p[4] - p[3]
    eye_distance, mouth_distance = np.linalg.norm(eyes), np.linalg.norm(mouth)
    eye_mid, mouth_mid = (p[0] + p[1]) / 2, (p[3] + p[4]) / 2
    parallel = np.dot(eyes, mouth) / max(eye_distance * mouth_distance, 1e-9)
    return bool(.18 <= eye_distance / width <= .8 and .12 <= mouth_distance / width <= .8
                and parallel > .5 and eyes[0] > 0
                and .01 * height < p[2, 1] - eye_mid[1] < .6 * height
                and .01 * height < mouth_mid[1] - p[2, 1] < .6 * height
                and .15 * height < mouth_mid[1] - eye_mid[1] < .8 * height)


def compatible(a, b):
    """A face must agree in center, scale and ordered source-space landmarks."""
    sa, sb = a['face_size'], b['face_size']
    scale = min(sa, sb)
    center_distance = np.linalg.norm(np.asarray(a['center']) - np.asarray(b['center']))
    landmark_error = np.sqrt(np.mean(np.sum((np.asarray(a['landmarks']) - b['landmarks']) ** 2, axis=1)))
    return bool(max(sa, sb) / min(sa, sb) <= 1.6 and center_distance <= .3 * scale
                and landmark_error <= .22 * scale)


def consensus(candidates, minimum_angles=MIN_ANGLES):
    """Complete-link grouping avoids a chain of false boxes joining faces."""
    clusters = []
    for index in sorted(range(len(candidates)), key=lambda i: (-candidates[i]['score'], i)):
        candidate = candidates[index]
        if not candidate['landmark_geometry_valid']:
            continue
        choices = [group for group in clusters if all(compatible(candidate, candidates[j]) for j in group)]
        if choices:
            choices[0].append(index)
        else:
            clusters.append([index])
    summaries = []
    for group in clusters:
        angles = sorted({candidates[i]['angle'] for i in group})
        summaries.append(dict(candidate_indices=sorted(group), supporting_angles=angles,
                              distinct_angles=len(angles),
                              minimum_confidence=min(candidates[i]['score'] for i in group)))
    qualified = [group for group in summaries if group['distinct_angles'] >= minimum_angles]
    if len(qualified) != 1:
        return dict(status='unresolved', reason='zero_or_multiple_landmark_consistent_faces', clusters=summaries)
    winner = qualified[0]
    # A second high-confidence isolated face is meaningful ambiguity too.
    rivals = [group for group in summaries if group != winner and group['minimum_confidence'] >= .95]
    if rivals:
        return dict(status='unresolved', reason='another_high_confidence_face', clusters=summaries)
    return dict(status='unique_face_consensus', clusters=summaries,
                consensus=dict(winner, minimum_distinct_angles=minimum_angles))


def head_shoulders_box(face_quad, landmarks, face_size, size):
    """Contain face, hair margin and landmark-oriented shoulder/neck estimates.

The image is never rotated. A portrait box minimally encloses these oriented
regions, so reclining actors keep their diagonal neck/shoulder direction.
"""
    width, height = size
    p = np.asarray(landmarks, dtype=float)
    eye_mid, mouth_mid = (p[0] + p[1]) / 2, (p[3] + p[4]) / 2
    across = p[1] - p[0]
    across /= np.linalg.norm(across)
    down = np.array([-across[1], across[0]])
    if np.dot(down, mouth_mid - eye_mid) < 0:
        down = -down
    center = np.mean(np.asarray(face_quad), axis=0)
    points = []
    for point in np.asarray(face_quad):
        for x in (-1, 1):
            for y in (-1, 1):
                points.append(point + .24 * face_size * (x * across + y * down))
    for along, shoulder_half in ((1.05, 1.3), (1.65, .9)):
        shoulder_center = center + down * face_size * along
        points.extend(shoulder_center + side * across * shoulder_half * face_size for side in (-1, 1))
    points = np.asarray(points)
    lower, upper = points.min(axis=0), points.max(axis=0)
    if np.any(lower < 0) or upper[0] > width or upper[1] > height:
        raise ValueError('insufficient_source_head_shoulder_margin')
    extent = upper - lower
    ratio = width / height
    crop_width = max(extent[0], extent[1] * ratio)
    crop_height = crop_width / ratio
    if crop_width > width or crop_height > height:
        raise ValueError('source_cannot_contain_target_aspect_head_shoulders')
    mid = (lower + upper) / 2
    crop_width, crop_height = math.ceil(crop_width), math.ceil(crop_height)
    x = max(0, min(width - crop_width, math.floor(mid[0] - crop_width / 2)))
    y = max(0, min(height - crop_height, math.floor(mid[1] - crop_height / 2)))
    box = dict(x=x, y=y, width=crop_width, height=crop_height)
    return box, dict(eye_midpoint=eye_mid.tolist(), mouth_midpoint=mouth_mid.tolist(),
                     body_down_axis=down.tolist(), shoulder_axis=across.tolist(),
                     required_region_points=points.tolist(),
                     rule='face quadrilateral + 0.24 face-size hair margin; neck/shoulders along eye-to-mouth direction; minimum enclosing original-aspect rectangle',
                     shoulder_bounds_are_estimates=True)


def detect(source, contract, model, *, contract_binding=None):
    validate_contract(contract)
    source_binding, model_binding = binding(source), binding(model)
    if model_binding['sha256'] != MODEL_SHA:
        raise ValueError('official_yunet_model_SHA_required')
    with Image.open(source) as image:
        rgb = np.asarray(image.convert('RGB'))
    height, width = rgb.shape[:2]
    cv2.setNumThreads(2)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    detector = cv2.FaceDetectorYN.create(str(model), '', (width, height), SCORE_THRESHOLD, .3, 5000, 0, 0)
    candidates, transforms = [], []
    for angle in ANGLES:
        affine, inverse, target = rotation(width, height, angle)
        frame = cv2.warpAffine(bgr, affine, target, borderValue=(127, 127, 127))
        detector.setInputSize(target)
        _, faces = detector.detect(frame)
        transforms.append(dict(angle=angle, source_to_detector=affine.tolist(),
                               detector_to_source=inverse.tolist(), detector_size=list(target)))
        for face in ([] if faces is None else faces):
            x, y, w, h = map(float, face[:4])
            landmarks_detector = face[4:14].reshape(5, 2).astype(float)
            quad = points_transform([[x, y], [x+w, y], [x+w, y+h], [x, y+h]], inverse)
            landmarks = points_transform(landmarks_detector, inverse)
            lo, hi = quad.min(axis=0), quad.max(axis=0)
            geometry = landmark_geometry(landmarks_detector, [x, y, w, h])
            in_source = bool(np.all(landmarks >= 0) and np.all(landmarks[:, 0] < width)
                             and np.all(landmarks[:, 1] < height))
            candidates.append(dict(angle=angle, score=float(face[-1]),
                bbox_detector=[x, y, w, h], quadrilateral=quad.tolist(),
                bbox=dict(x=float(lo[0]), y=float(lo[1]), width=float(hi[0]-lo[0]), height=float(hi[1]-lo[1])),
                center=quad.mean(axis=0).tolist(), face_size=math.sqrt(w*h),
                landmarks=landmarks.tolist(), landmark_geometry_valid=geometry and in_source))
    result = dict(schema='story_opening_face_detection/v1', method=METHOD, detector='opencv_yunet',
        bbox_source='algorithm_auto_multirotation_consensus', source=source_binding,
        opening_contract_sha256=opening.digest(contract), opening_contract=contract,
        model=model_binding, code=binding(__file__), opencv_version=cv2.__version__,
        score_threshold=SCORE_THRESHOLD, source_size=[width, height],
        transforms=transforms, candidates=candidates, cpu_detector_inferences=len(ANGLES),
        new_generative_model_calls=0, source_orientation_preserved=True)
    if contract_binding is not None:
        result['contract_binding'] = contract_binding
    grouping = consensus(candidates)
    result.update(grouping)
    if grouping['status'] == 'unique_face_consensus':
        group = [candidates[i] for i in grouping['consensus']['candidate_indices']]
        landmarks = np.median([item['landmarks'] for item in group], axis=0)
        chosen = max(group, key=lambda item: item['score'])
        quad = np.asarray(chosen['quadrilateral'])
        lo, hi = quad.min(axis=0), quad.max(axis=0)
        result.update(confidence=min(item['score'] for item in group),
            landmarks=landmarks.tolist(), landmark_geometry_valid=True,
            face_box=dict(x=float(lo[0]), y=float(lo[1]), width=float(hi[0]-lo[0]), height=float(hi[1]-lo[1])))
        try:
            box, design = head_shoulders_box(quad, landmarks, float(np.median([item['face_size'] for item in group])), [width, height])
        except ValueError as error:
            result.update(status='unresolved', reason=str(error))
        else:
            result.update(box=box, head_shoulders_design=design,
                warnings=['Shoulder/neck bounds are landmark-derived estimates, not a semantic body segmentation.',
                          'Crop is resized; this does not create original high-resolution detail.'],
                actual_scale=dict(x=width/box['width'], y=height/box['height']))
    checked(source_binding)
    checked(model_binding)
    return result


def crop(detection_file, out, *, output_name='OPENING_CROPPED.png'):
    """Explicit second action, after the caller accepts the detection evidence."""
    detection_binding = binding(detection_file)
    d = json.loads(Path(detection_file).read_text(encoding='utf-8'))
    if d.get('status') != 'unique_face_consensus' or d.get('method') != METHOD:
        raise ValueError('known_unique_yunet_detection_required')
    validate_contract(d['opening_contract'])
    if d['opening_contract_sha256'] != opening.digest(d['opening_contract']):
        raise ValueError('opening_crop_contract_changed')
    checked(d['source'])
    checked(d['model'])
    checked(d['code'])
    if d['model']['sha256'] != MODEL_SHA:
        raise ValueError('official_yunet_model_SHA_required')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    image_path = out / output_name
    if image_path == Path(d['source']['path']).resolve() or image_path.exists():
        raise ValueError('new_crop_output_required_source_preserved')
    b = d['box']
    with Image.open(d['source']['path']) as source:
        width, height = source.size
        if (any(type(b[k]) is not int for k in ('x', 'y', 'width', 'height'))
                or min(b['x'], b['y']) < 0 or min(b['width'], b['height']) <= 0
                or b['x']+b['width'] > width or b['y']+b['height'] > height):
            raise ValueError('integer_crop_inside_source_required')
        result = source.convert('RGB').crop((b['x'], b['y'], b['x']+b['width'], b['y']+b['height']))
        result.resize((width, height), Image.Resampling.LANCZOS).save(image_path)
    receipt = dict(schema='story_opening_crop/v1', parent_image=d['source'], image=binding(image_path),
        box=b, target_size=[width, height], resampler=RESAMPLER, pillow_version=PILLOW_VERSION,
        detection=detection_binding, opening_contract_sha256=d['opening_contract_sha256'],
        actual_scale=d['actual_scale'], source_orientation_preserved=True,
        original_resolution_claim=False, new_generative_model_calls=0)
    freeze(out / 'CROP_RESULT.json', receipt)
    return receipt
