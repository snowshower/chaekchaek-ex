from copy import deepcopy

import pytest
from flask import render_template

from app.queries import book
from conftest import Participant, rows


@pytest.mark.parametrize('bid,old_version', [
    ('little-prince', 'little-prince-v2'),
    ('old-man-and-sea', 'old-man-and-sea-v1'),
    ('metamorphosis', 'metamorphosis-v1'),
])
def test_illustration_version_preserves_content_and_has_static_image(app, bid, old_version):
    with app.app_context():
        current = book(bid)
        previous = book(bid, old_version)
        for key in previous:
            if key not in ('version', 'effective_at'):
                assert current[key] == previous[key]
        assert current['illustration']['src'] == f'images/books/{bid}.png'
    participant = Participant(app, bid)
    html = participant.client.get(f'/books/{bid}').get_data(as_text=True)
    assert f'src="/static/images/books/{bid}.png"' in html
    assert 'loading="lazy"' in html and 'decoding="async"' in html
    assert html.index('class="situation"') < html.index('class="scene-illustration"') < html.index('class="excerpt-section"')
    figure = html.split('<figure class="scene-illustration">', 1)[1].split('</figure>', 1)[0]
    assert 'excerpt-block' not in figure and 'data-' not in figure
    count = len(rows(app, 'events'))
    image = participant.client.get(f'/static/images/books/{bid}.png')
    assert image.status_code == 200 and image.mimetype == 'image/png'
    assert len(rows(app, 'events')) == count


@pytest.mark.parametrize('illustration', [None, {}, {'src': ''}])
def test_missing_illustration_has_no_placeholder(app, illustration):
    with app.test_request_context():
        data = deepcopy(book('little-prince'))
        data['illustration'] = illustration
        html = render_template('book.html', book=data, bootstrap={})
        assert 'class="scene-illustration"' not in html
        data.pop('illustration')
        assert 'class="scene-illustration"' not in render_template('book.html', book=data, bootstrap={})