
def circle_hits_rect(pos, radius, rect):
    x1, y1, x2, y2 = rect
    cx = min(max(pos[0], x1), x2)
    cy = min(max(pos[1], y1), y2)
    return (pos[0] - cx) ** 2 + (pos[1] - cy) ** 2 <= radius**2
