"""CPU geometry/ambiguity checks; no model inference or production writes."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from src.content_factory import visual_opening_crop as crop
from src.content_factory import visual_opening_frame as opening


def contract():
    return dict(schema=opening.SCHEMA, policy=opening.POLICY,
                opening_camera_beat=dict(start=0, cut=False, framing='face_close', actors={'actor': {}}),
                opening_visible_actors=['actor'])


def candidate(angle, *, shift=(0, 0), score=.91):
    points = np.asarray([[125., 140.], [175., 140.], [150., 170.], [130., 190.], [170., 190.]])
    points += shift
    return dict(angle=angle, score=score, face_size=110., center=[150.+shift[0], 165.+shift[1]],
                landmarks=points.tolist(), landmark_geometry_valid=True)


@pytest.mark.parametrize('angle', [-90, -60, -30, 0, 30, 60, 90, 180])
def test_detection_rotations_inverse_to_original_image(angle):
    affine, inverse, size = crop.rotation(736, 1312, angle)
    points = np.asarray([[0., 0.], [735., 1311.], [400., 550.]])
    back = crop.points_transform(crop.points_transform(points, affine), inverse)
    assert np.allclose(back, points, atol=1e-9)
    assert min(size) > 0


def test_consensus_requires_independent_angles_and_ordered_landmarks():
    a, b = candidate(30), candidate(60, shift=(1., -1.))
    result = crop.consensus([a, b])
    assert result['status'] == 'unique_face_consensus'
    assert result['consensus']['supporting_angles'] == [30, 60]
    b['angle'] = 30
    assert crop.consensus([a, b])['status'] == 'unresolved'
    b['angle'] = 60
    b['landmarks'] = list(reversed(b['landmarks']))
    assert crop.consensus([a, b])['status'] == 'unresolved'


def test_multiple_real_face_consensuses_do_not_choose_largest_vote():
    observations = [candidate(30), candidate(60), candidate(90),
                    candidate(30, shift=(300., 400.)), candidate(60, shift=(300., 400.))]
    assert crop.consensus(observations)['status'] == 'unresolved'


def test_five_point_geometry_rejects_unordered_or_implausible_face():
    good = candidate(30)['landmarks']
    assert crop.landmark_geometry(good, [100, 100, 100, 130])
    bad = deepcopy(good)
    bad[2] = [150, 110]  # Nose above both eyes.
    assert not crop.landmark_geometry(bad, [100, 100, 100, 130])
    assert not crop.landmark_geometry(list(reversed(good)), [100, 100, 100, 130])


def test_reclining_head_crop_contains_landmark_oriented_margin_without_rotation():
    # Synthetic head and shoulders, rotated as a pose rather than a shot ID.
    eye_mouth = np.asarray(candidate(0)['landmarks']) - [150, 165]
    theta = np.deg2rad(55)
    rotate = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    landmarks = eye_mouth @ rotate.T + [450, 550]
    quad = (np.asarray([[100, 100], [200, 100], [200, 230], [100, 230]]) - [150, 165]) @ rotate.T + [450, 550]
    box, design = crop.head_shoulders_box(quad, landmarks, 110., [736, 1312])
    points = np.asarray(design['required_region_points'])
    assert np.all(points[:, 0] >= box['x']) and np.all(points[:, 0] <= box['x']+box['width'])
    assert np.all(points[:, 1] >= box['y']) and np.all(points[:, 1] <= box['y']+box['height'])
    assert abs(box['width']/box['height'] - 736/1312) < .003
    assert design['body_down_axis'][0] < 0  # Keep reclining neck/shoulders leftward.


def test_source_without_head_shoulder_margin_is_explicitly_unresolved():
    landmarks = np.asarray(candidate(0)['landmarks']) - [130, 120]
    quad = np.asarray([[0, 0], [100, 0], [100, 130], [0, 130]])
    with pytest.raises(ValueError, match='insufficient_source'):
        crop.head_shoulders_box(quad, landmarks, 110., [736, 1312])


def test_contract_scope_and_official_model_pin_are_enforced_before_inference(tmp_path):
    multiple = contract()
    multiple['opening_camera_beat']['actors']['extra'] = {}
    with pytest.raises(ValueError, match='single_subject'):
        crop.validate_contract(multiple)
    source = tmp_path/'source.png'
    Image.new('RGB', (96, 128), 'gray').save(source)
    fake_model = tmp_path/'wrong.onnx'
    fake_model.write_bytes(b'not official model')
    with pytest.raises(ValueError, match='official_yunet_model_SHA'):
        crop.detect(source, contract(), fake_model)


def test_unresolved_detection_never_creates_crop(tmp_path):
    detection = tmp_path/'DETECTION.json'
    detection.write_text(json.dumps(dict(status='unresolved', method=crop.METHOD)), encoding='utf-8')
    with pytest.raises(ValueError, match='known_unique'):
        crop.crop(detection, tmp_path/'result')
    assert not (tmp_path/'result').exists()
