"""提交校验测试：错误必须带索引与字段，且一次收集全部。"""

from app.validation import validate_submission


def make_payload(points, name="K-2026-0911"):
    return {"name": name, "points": points}


def make_point(time, temperature):
    return {"time": time, "temperature": temperature}


VALID_POINTS = [
    make_point("2026-09-11T08:00:00Z", 620.0),
    make_point("2026-09-11T10:00:00Z", 640.0),
]


def fields(errors):
    return {(e.index, e.field) for e in errors}


class TestName:
    def test_valid_payload_passes(self):
        normalized, errors = validate_submission(make_payload(VALID_POINTS))
        assert errors == []
        assert normalized.name == "K-2026-0911"
        assert len(normalized.points) == 2

    def test_blank_name_rejected(self):
        _, errors = validate_submission(make_payload(VALID_POINTS, name="  "))
        assert (None, "name") in fields(errors)

    def test_name_trimmed(self):
        normalized, errors = validate_submission(
            make_payload(VALID_POINTS, name="  K-1  ")
        )
        assert errors == []
        assert normalized.name == "K-1"


class TestPointCount:
    def test_too_few_points(self):
        _, errors = validate_submission(make_payload(VALID_POINTS[:1]))
        assert (None, "points") in fields(errors)

    def test_too_many_points(self):
        points = [
            make_point(f"2026-09-11T08:{i % 60:02d}:{i % 60:02d}Z", 620.0)
            for i in range(201)
        ]
        # 时刻会重复，但数量错误必须先于一切被报出
        _, errors = validate_submission(make_payload(points))
        assert (None, "points") in fields(errors)

    def test_points_must_be_list(self):
        _, errors = validate_submission({"name": "K", "points": "not-a-list"})
        assert (None, "points") in fields(errors)


class TestPointFields:
    def test_point_must_be_object(self):
        _, errors = validate_submission(make_payload(["oops", VALID_POINTS[1]]))
        assert (0, "point") in fields(errors)

    def test_temperature_must_be_number(self):
        points = [VALID_POINTS[0], make_point("2026-09-11T10:00:00Z", "abc")]
        _, errors = validate_submission(make_payload(points))
        assert (1, "temperature") in fields(errors)

    def test_temperature_bool_rejected(self):
        points = [VALID_POINTS[0], make_point("2026-09-11T10:00:00Z", True)]
        _, errors = validate_submission(make_payload(points))
        assert (1, "temperature") in fields(errors)

    def test_temperature_range(self):
        for bad in (-0.1, 1400.1, -50, 2000):
            points = [VALID_POINTS[0], make_point("2026-09-11T10:00:00Z", bad)]
            _, errors = validate_submission(make_payload(points))
            assert (1, "temperature") in fields(errors), bad

    def test_temperature_bounds_inclusive(self):
        points = [
            make_point("2026-09-11T08:00:00Z", 0),
            make_point("2026-09-11T10:00:00Z", 1400),
        ]
        _, errors = validate_submission(make_payload(points))
        assert errors == []

    def test_time_must_be_iso8601(self):
        points = [VALID_POINTS[0], make_point("not-a-time", 640.0)]
        _, errors = validate_submission(make_payload(points))
        assert (1, "time") in fields(errors)

    def test_time_requires_time_of_day(self):
        points = [VALID_POINTS[0], make_point("2026-09-12", 640.0)]
        _, errors = validate_submission(make_payload(points))
        assert (1, "time") in fields(errors)


class TestCrossPointRules:
    def test_equal_timestamps_rejected_at_second_point(self):
        points = [
            make_point("2026-09-11T08:00:00Z", 620.0),
            make_point("2026-09-11T08:00:00Z", 640.0),
        ]
        _, errors = validate_submission(make_payload(points))
        assert (1, "time") in fields(errors)

    def test_decreasing_timestamps_rejected_at_later_point(self):
        points = [
            make_point("2026-09-11T08:00:00Z", 620.0),
            make_point("2026-09-11T09:00:00Z", 640.0),
            make_point("2026-09-11T08:30:00Z", 630.0),
        ]
        _, errors = validate_submission(make_payload(points))
        assert (2, "time") in fields(errors)

    def test_same_instant_different_offsets_rejected(self):
        points = [
            make_point("2026-09-11T08:00:00+00:00", 620.0),
            make_point("2026-09-11T09:00:00+01:00", 640.0),
        ]
        _, errors = validate_submission(make_payload(points))
        assert (1, "time") in fields(errors)

    def test_naive_time_treated_as_utc(self):
        points = [
            make_point("2026-09-11T08:00:00", 620.0),
            make_point("2026-09-11T08:00:00Z", 640.0),
        ]
        _, errors = validate_submission(make_payload(points))
        assert (1, "time") in fields(errors)

    def test_span_over_twelve_hours_rejected(self):
        points = [
            make_point("2026-09-11T00:00:00Z", 620.0),
            make_point("2026-09-11T12:00:01Z", 640.0),
        ]
        _, errors = validate_submission(make_payload(points))
        assert (None, "points") in fields(errors)

    def test_span_exactly_twelve_hours_allowed(self):
        points = [
            make_point("2026-09-11T00:00:00Z", 620.0),
            make_point("2026-09-11T12:00:00Z", 640.0),
        ]
        _, errors = validate_submission(make_payload(points))
        assert errors == []


class TestErrorCollection:
    def test_all_errors_collected_at_once(self):
        points = [
            make_point("2026-09-11T08:00:00Z", 620.0),
            make_point("2026-09-11T09:00:00Z", 1500.0),
            make_point("bad-time", 640.0),
        ]
        normalized, errors = validate_submission(make_payload(points))
        assert normalized is None
        assert (1, "temperature") in fields(errors)
        assert (2, "time") in fields(errors)
