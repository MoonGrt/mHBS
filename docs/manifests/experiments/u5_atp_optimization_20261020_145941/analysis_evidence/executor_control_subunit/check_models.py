#!/usr/bin/env python3
"""Check allocator next-state and target coordinates; does not execute RTL."""
import argparse
import json
import random
from pathlib import Path


def check():
    rng = random.Random(0x2076)
    results = []
    for p in (1, 2, 3, 4, 6, 8, 12, 24):
        active = set()
        prepared_tag = 0
        prepared_available = True
        coverage = dict(simultaneous=0, full_retire=0, release_lower=0, setup=0, stall=0)
        for _ in range(100000):
            free = set(range(p)) - active
            assert prepared_available == bool(free)
            assert prepared_tag == (min(free) if free else 0)
            setup = rng.randrange(251) == 0
            oldactive = set(active)
            completed = rng.choice(tuple(active)) if active and rng.randrange(3) == 0 else None
            ready = bool(rng.getrandbits(1))
            issue = prepared_tag if prepared_available and ready and rng.randrange(5) != 0 else None
            if issue is not None:
                assert issue not in oldactive
            # Independent set-based ownership specification. New retirement
            # does not become available to this cycle's already prepared issue.
            if completed is not None:
                active.remove(completed)
            if issue is not None:
                active.add(issue)
            # Implementation next-state equation, compared at the next beat.
            next_free_mask = ((1 << p) - 1) ^ sum(1 << j for j in oldactive)
            if completed is not None:
                next_free_mask |= 1 << completed
            if issue is not None:
                next_free_mask &= ~(1 << issue)
            prepared_available = bool(next_free_mask)
            prepared_tag = next((j for j in range(p) if (next_free_mask >> j) & 1), 0)
            if setup:
                active = set()
                prepared_tag = 0
                prepared_available = True
                coverage['setup'] += 1
            if completed is not None and issue is not None:
                coverage['simultaneous'] += 1
            if not free and completed is not None:
                coverage['full_retire'] += 1
            if completed is not None and completed < min(free, default=p):
                coverage['release_lower'] += 1
            if free and not ready:
                coverage['stall'] += 1
        results.append(dict(pipeline=p, cycles=100000, **{'pass': True}, coverage=coverage))

    coordinates = [0, 1, 2, 3, 1023, 1024, 32767, 32768, 65535, 65536,
                   1048575, 1048576, 2097151]
    coordinates += [rng.randrange(1 << 21) for _ in range(10000)]
    pair_count = 0
    for node, target in zip(coordinates, coordinates[::-1]):
        for initial_level in (0, 2):
            n, t = node, target >> initial_level
            flag = (n >> 1) == (target >> 3) if initial_level == 2 else (n >> 1) == (target >> 1)
            for _ in range(initial_level, 21):
                assert flag == ((n >> 1) == (t >> 1))
                next_flag = (n >> 2) == (t >> 2)
                n >>= 1
                t >>= 1
                flag = next_flag
                pair_count += 1
    return dict(scope='Independent ownership/coordinate model; complements but does not replace RTL regression',
                allocator=results, parent_coordinate_checks=pair_count, **{'pass': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(result='PASS', allocator_cycles=800000,
                          parent_coordinate_checks=result['parent_coordinate_checks'])))
