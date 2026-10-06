"""First-touch values only; no URL or referrer retention."""
SOURCES = ('slack', 'everytime', 'dc', 'arca', 'threads', 'instagram', 'direct')


def normalize_source(value):
    value = (value or '').strip().lower()
    return value if value in SOURCES else 'direct'


def source_funnel(events, qualified):
    """Partition the existing per-book-qualified union sets."""
    visitors, _, extras, _ = qualified['all']
    by_visitor = {e['visitor_id']: e.get('acquisition_source', 'direct') for e in events}
    result = []
    for source in SOURCES:
        members = {v for v, s in by_visitor.items() if s == source}
        viewed = visitors & members
        metrics = []
        for name in ('light_participation', 'text_participation', 'community_direct', 'others_exposure'):
            numerator = len(extras[name] & members)
            metrics.append({'metric_name': name, 'numerator': numerator,
                            'denominator': len(viewed), 'ratio': numerator / len(viewed) if viewed else None})
        result.append({'source': source, 'landing': len({e['visitor_id'] for e in events
                       if e['event_type'] == 'landing_view'} & members),
                       'book_view': len(viewed), 'metrics': metrics})
    return result
