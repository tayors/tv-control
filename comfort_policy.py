"""Local, explicit comfort feedback. No brightness curve or inferred preferences."""
import copy
import math


LIGHT_RADIUS = math.log(2)


def light_distance(first, second):
    return abs(math.log1p(first / 10) - math.log1p(second / 10))


def remembered_point(memory, lux, context):
    candidates = []
    for point in memory.get('points', []):
        try:
            valid = (point['context'] == context and type(point['brightness']) is int
                     and 5 <= point['brightness'] <= 85 and type(point['lux']) in (int, float)
                     and math.isfinite(point['lux']) and point['lux'] >= 0)
            if valid:
                distance = light_distance(lux, point['lux'])
                if distance <= LIGHT_RADIUS:
                    candidates.append((distance, -point.get('time', 0), point))
        except (KeyError, TypeError, ValueError):
            continue
    return min(candidates, key=lambda item: item[:2])[2] if candidates else None


def plan_feedback(memory, sample, kind, now, revision):
    """Plan one nudge or confirmation; the caller validates samples and verifies writes."""
    updated = copy.deepcopy(memory)
    updated.setdefault('points', [])
    current = sample['backlight']
    context = [sample['picture_mode'], sample['hdr_setting']]
    lux = sample['lux']
    if kind == 'comfortable':
        previous = remembered_point(updated, lux, context)
        if previous is not None:
            updated['points'].remove(previous)
        updated['points'].append({'context': context, 'lux': lux, 'brightness': current, 'time': now})
        updated['points'] = updated['points'][-50:]
        updated.pop('pending', None)
        target = current
        message = 'Remembered. I’ll reuse this brightness in similar room light.'
    elif kind in ('too-bright', 'too-dark'):
        target = max(5, min(85, current + (-3 if kind == 'too-bright' else 3)))
        if target == current:
            raise ValueError('This picture is at the adjustment limit. You can use the TV’s picture controls or mark it Comfortable.')
        updated['pending'] = {'context': context, 'lux': lux, 'brightness': target, 'time': now}
        direction = 'dimmer' if kind == 'too-bright' else 'brighter'
        message = f'Made the picture a little {direction}. Choose Comfortable when it feels right.'
    else:
        raise ValueError('Choose too-bright, too-dark, or comfortable.')
    updated['revision'] = revision
    return updated, target, message
