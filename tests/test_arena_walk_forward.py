from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arena import parameters, walk_forward


def _bar(index: int) -> dict:
    """Minimal bar dict with close_time sorted by index."""
    t = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(hours=4 * index)
    return {"close_time": t.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _bars(count: int) -> list[dict]:
    return [_bar(i) for i in range(count)]


WARMUP = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD  # 35
TRAIN = parameters.WF_TRAIN_BARS  # 500
EMBARGO = parameters.WF_EMBARGO_BARS  # 6
TEST = parameters.WF_TEST_BARS  # 120
STEP = parameters.WF_STEP_BARS  # 120
MIN_TOTAL = parameters.WF_MIN_TOTAL_BARS  # 626


class TestInsufficientData:
    def test_empty_bars_returns_insufficient(self) -> None:
        result = walk_forward.generate_splits([])
        assert result.status == "insufficient_data"
        assert result.splits == []
        assert result.available_bars == 0

    def test_only_warmup_bars_insufficient(self) -> None:
        result = walk_forward.generate_splits(_bars(WARMUP))
        assert result.status == "insufficient_data"
        assert result.available_bars == 0

    def test_one_bar_short_of_minimum(self) -> None:
        total_needed = WARMUP + MIN_TOTAL
        result = walk_forward.generate_splits(_bars(total_needed - 1))
        assert result.status == "insufficient_data"
        assert result.splits == []
        assert result.available_bars == MIN_TOTAL - 1

    def test_message_describes_shortfall(self) -> None:
        result = walk_forward.generate_splits(_bars(10))
        assert "warmup" in result.message
        assert str(MIN_TOTAL) in result.message


class TestSingleSplit:
    def setup_method(self) -> None:
        # Exactly enough for one split, not enough for two
        self.bars = _bars(WARMUP + MIN_TOTAL)
        self.result = walk_forward.generate_splits(self.bars)

    def test_status_ok(self) -> None:
        assert self.result.status == "ok"

    def test_exactly_one_split(self) -> None:
        assert len(self.result.splits) == 1

    def test_split_num_zero(self) -> None:
        assert self.result.splits[0].split_num == 0

    def test_split_name_contains_wf_version(self) -> None:
        assert parameters.WF_VERSION in self.result.splits[0].split_name

    def test_split_name_contains_s00(self) -> None:
        assert "_s00" in self.result.splits[0].split_name

    def test_train_end_before_test_start(self) -> None:
        s = self.result.splits[0]
        assert s.train_end < s.test_start

    def test_train_start_before_train_end(self) -> None:
        s = self.result.splits[0]
        assert s.train_start < s.train_end

    def test_test_start_before_test_end(self) -> None:
        s = self.result.splits[0]
        assert s.test_start < s.test_end

    def test_train_bar_count(self) -> None:
        s = self.result.splits[0]
        assert s.train_bar_count == TRAIN

    def test_test_bar_count(self) -> None:
        s = self.result.splits[0]
        assert s.test_bar_count == TEST

    def test_embargo_bars_stored(self) -> None:
        assert self.result.splits[0].embargo_bars == EMBARGO

    def test_split_ids_are_unique(self) -> None:
        ids = {s.split_id for s in self.result.splits}
        assert len(ids) == len(self.result.splits)

    def test_available_bars(self) -> None:
        assert self.result.available_bars == MIN_TOTAL


class TestMultipleSplits:
    def setup_method(self) -> None:
        # Enough for 3 splits: WARMUP + TRAIN + EMBARGO + 3*TEST
        total = WARMUP + TRAIN + EMBARGO + 3 * STEP
        self.bars = _bars(total)
        self.result = walk_forward.generate_splits(self.bars)

    def test_three_splits_generated(self) -> None:
        assert len(self.result.splits) == 3

    def test_split_names_are_unique(self) -> None:
        names = [s.split_name for s in self.result.splits]
        assert len(names) == len(set(names))

    def test_split_nums_sequential(self) -> None:
        nums = [s.split_num for s in self.result.splits]
        assert nums == list(range(3))

    def test_train_windows_expand(self) -> None:
        # Expanding anchor: each split's train_bar_count is larger than the previous
        counts = [s.train_bar_count for s in self.result.splits]
        assert counts[0] < counts[1] < counts[2]

    def test_test_windows_non_overlapping(self) -> None:
        # Each test window starts after the previous test window ends
        splits = self.result.splits
        for i in range(1, len(splits)):
            assert splits[i].test_start > splits[i - 1].test_end

    def test_train_always_starts_at_same_bar(self) -> None:
        # Expanding anchor: all splits share the same train_start
        starts = [s.train_start for s in self.result.splits]
        assert len(set(starts)) == 1

    def test_no_leakage_train_does_not_overlap_test(self) -> None:
        for s in self.result.splits:
            # embargo_bars > 0 so there must be a gap
            assert s.train_end < s.test_start


class TestNoEmbargo:
    def test_zero_embargo_train_end_still_before_test_start(self) -> None:
        bars = _bars(WARMUP + TRAIN + TEST)
        result = walk_forward.generate_splits(bars, embargo_bars=0)
        assert result.status == "ok"
        s = result.splits[0]
        # Different bars so close_times differ even without embargo
        assert s.train_end < s.test_start


class TestResultDict:
    def test_as_dict_contains_expected_keys(self) -> None:
        bars = _bars(WARMUP + MIN_TOTAL)
        result = walk_forward.generate_splits(bars)
        d = result.as_dict()
        assert "status" in d
        assert "split_count" in d
        assert "splits" in d
        assert "available_bars" in d
        assert "min_required_bars" in d

    def test_split_as_dict_contains_timestamps(self) -> None:
        bars = _bars(WARMUP + MIN_TOTAL)
        result = walk_forward.generate_splits(bars)
        d = result.splits[0].as_dict()
        assert "train_start" in d
        assert "train_end" in d
        assert "test_start" in d
        assert "test_end" in d

    def test_split_as_row_contains_notes(self) -> None:
        bars = _bars(WARMUP + MIN_TOTAL)
        result = walk_forward.generate_splits(bars)
        row = result.splits[0].as_row()
        assert "notes" in row
        import json

        notes = json.loads(row["notes"])
        assert "wf_version" in notes
        assert notes["split_num"] == 0

    def test_insufficient_as_dict_has_zero_splits(self) -> None:
        result = walk_forward.generate_splits([])
        d = result.as_dict()
        assert d["status"] == "insufficient_data"
        assert d["split_count"] == 0
        assert d["splits"] == []


class TestVersionsStoredInSplit:
    def test_default_versions_from_parameters(self) -> None:
        bars = _bars(WARMUP + MIN_TOTAL)
        result = walk_forward.generate_splits(bars)
        s = result.splits[0]
        assert s.strategy_version == parameters.STRATEGY_VERSION
        assert s.params_version == parameters.PARAMS_VERSION
        assert s.risk_model_version == parameters.RISK_MODEL_VERSION

    def test_custom_versions_stored(self) -> None:
        bars = _bars(WARMUP + MIN_TOTAL)
        result = walk_forward.generate_splits(
            bars,
            strategy_version="custom-v99",
            params_version="params-v99",
            risk_model_version="risk-v99",
        )
        s = result.splits[0]
        assert s.strategy_version == "custom-v99"
        assert s.params_version == "params-v99"
        assert s.risk_model_version == "risk-v99"
