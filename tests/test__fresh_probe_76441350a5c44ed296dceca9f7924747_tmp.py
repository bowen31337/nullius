from pathlib import Path

_seen = {}


def test_first(lake_root, test_database_url):
    (lake_root / 'staging' / 'marker.txt').write_text('first')
    _seen['lake'] = str(lake_root)
    _seen['db'] = test_database_url


def test_second(lake_root, test_database_url):
    assert _seen, 'test_first must run first, in this process'
    assert not (lake_root / 'staging' / 'marker.txt').exists()
    assert str(lake_root) != _seen['lake']
    assert test_database_url != _seen['db']
