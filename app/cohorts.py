def non_seed(alias):
    """Internal SQL predicate: exclude the actor, never the target review owner."""
    return f'NOT EXISTS (SELECT 1 FROM seed_participants seed WHERE seed.visitor_id={alias}.visitor_id)'
