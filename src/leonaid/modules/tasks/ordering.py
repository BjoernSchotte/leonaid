"""Small integer gaps for task ordering."""

POSITION_STEP = 1024


def position_between(previous: int | None, following: int | None) -> int | None:
    if previous is None:
        return POSITION_STEP if following is None else following - POSITION_STEP
    if following is None:
        return previous + POSITION_STEP
    if previous >= following:
        raise ValueError("positions must be ordered")
    return previous + (following - previous) // 2 if following - previous > 1 else None


if __name__ == "__main__":
    assert position_between(None, None) == POSITION_STEP
    assert position_between(None, 2048) == 1024
    assert position_between(1024, None) == 2048
    assert position_between(1024, 2048) == 1536
    assert position_between(1024, 1025) is None
