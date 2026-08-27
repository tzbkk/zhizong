def test_version():
    import re

    import zhizong

    assert re.fullmatch(r"\d+\.\d+\.\d+([.-].+)?", zhizong.__version__)
