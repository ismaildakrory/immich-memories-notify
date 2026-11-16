import random
from collections import Counter

from notify.immich import PickPolicy, is_screenshot_like


def test_is_screenshot_like():
    assert is_screenshot_like({"originalFileName": "Screenshot_20240101.jpg", "type": "IMAGE"})
    assert is_screenshot_like({"originalPath": "/phone/DCIM/Screenshots/x.jpg", "type": "IMAGE"})
    assert is_screenshot_like({"originalFileName": "file_0000.png", "originalMimeType": "image/png", "type": "IMAGE"})
    assert not is_screenshot_like({"originalFileName": "IMG_1.jpg", "originalMimeType": "image/jpeg", "type": "IMAGE"})
    assert not is_screenshot_like({"originalFileName": "clip.png", "originalMimeType": "image/png", "type": "VIDEO"})


def test_policy_allowed_and_toggle():
    shot = {"id": "s", "originalFileName": "Screenshot.png", "originalMimeType": "image/png", "type": "IMAGE"}
    gen = {"id": "g", "originalFileName": "memnotify-collage-1.jpg"}
    photo = {"id": "p", "originalFileName": "IMG.jpg", "originalMimeType": "image/jpeg", "type": "IMAGE"}
    assert [PickPolicy().allowed(a) for a in (shot, gen, photo)] == [False, False, True]
    assert [PickPolicy(skip_screenshots=False).allowed(a) for a in (shot, gen, photo)] == [True, False, True]


def test_policy_weights_unseen_and_favourites():
    random.seed(5)
    policy = PickPolicy(seen_ids={"seen"})
    assets = [{"id": "seen"}, {"id": "new"}, {"id": "fav", "isFavorite": True}]
    assert policy.weight(assets[0]) == 1 and policy.weight(assets[1]) == 4 and policy.weight(assets[2]) == 12
    picks = Counter(policy.choose(assets)["id"] for _ in range(3000))
    assert picks["fav"] > picks["new"] > picks["seen"] > 50  # ordered, but nothing starved
    assert policy.choose([]) is None


def test_policy_ordered_is_distinct_and_bounded():
    policy = PickPolicy()
    assets = [{"id": str(i)} for i in range(10)]
    out = policy.ordered(assets, 4)
    assert len(out) == 4 and len({a["id"] for a in out}) == 4
    assert len(policy.ordered(assets[:2], 5)) == 2
