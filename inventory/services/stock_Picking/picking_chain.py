def chain_for(picking):
    """Every picking in the same transfer chain, in step order (pick -> pack -> ship)."""
    # 1. walk back to the first step
    head, seen = picking, {picking.pk}
    while True:
        prev = head.previous_pickings().exclude(pk__in=seen).first()
        if prev is None:
            break
        seen.add(prev.pk)
        head = prev

    # 2. walk forward from there
    chain = [head]
    while True:
        nxt = chain[-1].next_pickings().exclude(pk__in=[p.pk for p in chain]).first()
        if nxt is None:
            break
        chain.append(nxt)
    return chain


def chain_context(picking):
    chain = chain_for(picking)
    idx = next((i for i, p in enumerate(chain) if p.pk == picking.pk), 0)
    return {
        "chain": chain,
        "step_number": idx + 1,
        "step_total": len(chain),
        "prev_picking": chain[idx - 1] if idx > 0 else None,
        "next_picking": chain[idx + 1] if idx < len(chain) - 1 else None,
    }