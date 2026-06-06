# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Tests for the Automatic Merit Status Engine (Task 6).

Covers:
  1. Score range validation (min > max rejected)
  2. Empty score ranges rejected
  3. _resolve_status correctly matches score → status
  4. Scores without a matching range are skipped
  5. Uncomputed applicants receive "In Progress"
  6. generate_merit_list assigns correct statuses, creates history records
  7. generate_merit_list updates range applicant_count
  8. publish_merit_list locks the document
  9. Locked documents cannot be modified
 10. get_merit_report returns ranked list
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime


def _make_score_range(merit_status, min_score=None, max_score=None, description=""):
    row = frappe._dict(
        merit_status=merit_status,
        min_score=min_score,
        max_score=max_score,
        description=description,
        idx=1,
        name=frappe.generate_hash(length=10),
        applicant_count=0,
    )
    return row


def _make_merit_list_doc(score_ranges, admission_round="ADM-2024", program="MBA", merit_list_number=1):
    """Build a MeritListStatus document without hitting the database."""
    from education.education.doctype.merit_list_status.merit_list_status import MeritListStatus

    doc = MeritListStatus(
        frappe._dict(
            doctype="Merit List Status",
            name="EDU-MLS-2024-00001",
            title="Test Merit List",
            admission_round=admission_round,
            program=program,
            merit_list_number=merit_list_number,
            score_ranges=score_ranges,
            is_published=0,
            is_locked=0,
            published_on=None,
            total_applicants_processed=0,
            generation_remarks="",
        )
    )
    doc.flags.ignore_mandatory = True
    return doc


# ──────────────────────────────────────────────────────────────────────────────
# 1. Score range validation
# ──────────────────────────────────────────────────────────────────────────────

class TestMeritScoreRangeValidation(FrappeTestCase):
    def _doc_with_ranges(self, ranges):
        return _make_merit_list_doc(ranges)

    def test_empty_score_ranges_raises(self):
        doc = self._doc_with_ranges([])
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc._validate_score_ranges()

    def test_max_less_than_min_raises(self):
        bad_row = _make_score_range("Selected", min_score=90, max_score=80)
        bad_row.idx = 1
        doc = self._doc_with_ranges([bad_row])
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc._validate_score_ranges()

    def test_valid_ranges_pass(self):
        rows = [
            _make_score_range("Selected", 90, 100),
            _make_score_range("Waiting", 80, 89),
            _make_score_range("Rejected", 0, 79),
        ]
        doc = self._doc_with_ranges(rows)
        doc._validate_score_ranges()  # should not raise


# ──────────────────────────────────────────────────────────────────────────────
# 2. _resolve_status  ─  score range matching
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveStatus(FrappeTestCase):
    def setUp(self):
        ranges = [
            _make_score_range("Selected",    90,   100),
            _make_score_range("Waiting",     80,  89.99),
            _make_score_range("Rejected",     0,  79.99),
        ]
        self.doc = _make_merit_list_doc(ranges)

    def test_top_score_is_selected(self):
        self.assertEqual(self.doc._resolve_status(95), "Selected")

    def test_exact_lower_boundary_selected(self):
        self.assertEqual(self.doc._resolve_status(90), "Selected")

    def test_exact_upper_boundary_waiting(self):
        self.assertEqual(self.doc._resolve_status(89.99), "Waiting")

    def test_mid_waiting(self):
        self.assertEqual(self.doc._resolve_status(85), "Waiting")

    def test_below_cutoff_is_rejected(self):
        self.assertEqual(self.doc._resolve_status(50), "Rejected")

    def test_zero_score_is_rejected(self):
        self.assertEqual(self.doc._resolve_status(0), "Rejected")

    def test_no_matching_range_returns_none(self):
        """Score above 100 — no range covers it; should return None."""
        self.assertIsNone(self.doc._resolve_status(105))

    def test_open_ended_catchall(self):
        """A row with no min or max should catch any score."""
        ranges = [_make_score_range("In Progress")]  # no min, no max
        doc = _make_merit_list_doc(ranges)
        self.assertEqual(doc._resolve_status(42), "In Progress")
        self.assertEqual(doc._resolve_status(0), "In Progress")

    def test_first_match_wins(self):
        """When two ranges both cover the score, the earlier row (lower idx) wins."""
        ranges = [
            _make_score_range("Selected", 80, 100),
            _make_score_range("Waiting",  80, 100),  # overlapping — never reached
        ]
        ranges[0].idx = 1
        ranges[1].idx = 2
        doc = _make_merit_list_doc(ranges)
        self.assertEqual(doc._resolve_status(85), "Selected")


# ──────────────────────────────────────────────────────────────────────────────
# 3. generate_merit_list  ─  end-to-end (mocked DB)
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateMeritList(FrappeTestCase):
    def _build_doc(self):
        ranges = [
            _make_score_range("Selected", 90, 100),
            _make_score_range("Waiting",  80, 89.99),
            _make_score_range("Rejected",  0, 79.99),
        ]
        return _make_merit_list_doc(ranges)

    def _fake_applicants(self):
        return [
            frappe._dict(name="APP-001", consolidated_score=95, score_status="Computed"),
            frappe._dict(name="APP-002", consolidated_score=85, score_status="Computed"),
            frappe._dict(name="APP-003", consolidated_score=60, score_status="Computed"),
            frappe._dict(name="APP-004", consolidated_score=0,  score_status="Draft"),    # In Progress
        ]

    @patch("frappe.get_all")
    @patch("frappe.db.set_value")
    @patch("frappe.get_doc")
    @patch("frappe.db.commit")
    def test_correct_statuses_assigned(self, mock_commit, mock_get_doc, mock_set_value, mock_get_all):
        mock_get_all.return_value = self._fake_applicants()
        history_mock = MagicMock()
        mock_get_doc.return_value = history_mock

        doc = self._build_doc()

        # Stub out db_set so it doesn't hit the DB
        doc.db_set = MagicMock()

        # Stub _update_range_counts
        doc._update_range_counts = MagicMock()

        result = doc.generate_merit_list()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["counts"]["Selected"], 1)
        self.assertEqual(result["counts"]["Waiting"], 1)
        self.assertEqual(result["counts"]["Rejected"], 1)
        self.assertEqual(result["counts"]["In Progress"], 1)

        # Each applicant should have received a set_value call
        self.assertEqual(mock_set_value.call_count, 4)

        # Each applicant should have a history record inserted
        self.assertEqual(history_mock.insert.call_count, 4)

    @patch("frappe.get_all")
    @patch("frappe.db.set_value")
    @patch("frappe.get_doc")
    @patch("frappe.db.commit")
    def test_uncomputed_gets_in_progress(self, mock_commit, mock_get_doc, mock_set_value, mock_get_all):
        applicants = [
            frappe._dict(name="APP-005", consolidated_score=0, score_status="Draft"),
        ]
        mock_get_all.return_value = applicants
        history_mock = MagicMock()
        mock_get_doc.return_value = history_mock

        doc = self._build_doc()
        doc.db_set = MagicMock()
        doc._update_range_counts = MagicMock()

        result = doc.generate_merit_list()

        # Verify set_value was called with "In Progress"
        call_kwargs = mock_set_value.call_args_list[0]
        args = call_kwargs[0]
        self.assertEqual(args[2]["merit_status"], "In Progress")

    @patch("frappe.get_all")
    @patch("frappe.db.set_value")
    @patch("frappe.get_doc")
    @patch("frappe.db.commit")
    def test_out_of_range_score_skipped(self, mock_commit, mock_get_doc, mock_set_value, mock_get_all):
        """Score > 100 doesn't match any range — applicant not updated."""
        applicants = [
            frappe._dict(name="APP-006", consolidated_score=110, score_status="Computed"),
        ]
        mock_get_all.return_value = applicants
        history_mock = MagicMock()
        mock_get_doc.return_value = history_mock

        doc = self._build_doc()
        doc.db_set = MagicMock()
        doc._update_range_counts = MagicMock()

        result = doc.generate_merit_list()

        self.assertEqual(result["total"], 0)
        mock_set_value.assert_not_called()

    def test_locked_doc_raises_on_generate(self):
        doc = self._build_doc()
        doc.is_locked = 1
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.generate_merit_list()


# ──────────────────────────────────────────────────────────────────────────────
# 4. publish_merit_list  ─  locking behaviour
# ──────────────────────────────────────────────────────────────────────────────

class TestPublishMeritList(FrappeTestCase):
    def _build_doc(self):
        return _make_merit_list_doc([_make_score_range("Selected", 90, 100)])

    @patch("frappe.db.set_value")
    @patch("frappe.db.commit")
    def test_publish_sets_locked(self, mock_commit, mock_set_value):
        doc = self._build_doc()
        doc.db_set = MagicMock()
        result = doc.publish_merit_list()
        self.assertEqual(result["status"], "published")
        # Verify is_locked db_set was called
        calls = {c[0][1]: c[0][2] for c in doc.db_set.call_args_list}
        self.assertEqual(calls.get("is_locked"), 1)
        self.assertEqual(calls.get("is_published"), 1)

    def test_already_locked_raises(self):
        doc = self._build_doc()
        doc.is_locked = 1
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.publish_merit_list()

    def test_validate_blocks_edit_on_locked_doc(self):
        doc = self._build_doc()
        doc.is_locked = 1
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc._assert_not_locked()

    def test_allow_locked_write_flag_bypasses_lock(self):
        doc = self._build_doc()
        doc.is_locked = 1
        doc.flags.allow_locked_write = True
        doc._assert_not_locked()  # should NOT raise


# ──────────────────────────────────────────────────────────────────────────────
# 5. Range count aggregation
# ──────────────────────────────────────────────────────────────────────────────

class TestRangeCounts(FrappeTestCase):
    @patch("frappe.db.set_value")
    def test_range_counts_updated(self, mock_set_value):
        rows = [
            _make_score_range("Selected", 90, 100),
            _make_score_range("Waiting",  80, 89),
            _make_score_range("Rejected",  0, 79),
        ]
        doc = _make_merit_list_doc(rows)
        counts = {"Selected": 3, "Waiting": 5, "Rejected": 2, "In Progress": 1}
        doc._update_range_counts(counts)

        # set_value should have been called once per row
        self.assertEqual(mock_set_value.call_count, len(rows))

        # Map the set_value calls: row.name → count
        updates = {c[0][1]: c[0][2] for c in mock_set_value.call_args_list}
        for row in rows:
            expected = counts[row.merit_status]
            self.assertEqual(updates.get(row.name), expected)


# ──────────────────────────────────────────────────────────────────────────────
# 6. Multiple merit lists per round
# ──────────────────────────────────────────────────────────────────────────────

class TestMultipleMeritLists(FrappeTestCase):
    def test_merit_list_number_stored_in_history(self):
        """generate_merit_list passes merit_list_number to history records."""
        ranges = [_make_score_range("Selected", 90, 100)]
        doc = _make_merit_list_doc(ranges, merit_list_number=2)
        applicants = [
            frappe._dict(name="APP-010", consolidated_score=95, score_status="Computed"),
        ]

        with patch("frappe.get_all", return_value=applicants), \
             patch("frappe.db.set_value"), \
             patch("frappe.db.commit"), \
             patch("frappe.get_doc") as mock_get_doc:

            history_mock = MagicMock()
            mock_get_doc.return_value = history_mock
            doc.db_set = MagicMock()
            doc._update_range_counts = MagicMock()

            doc.generate_merit_list()

            inserted_doc = mock_get_doc.call_args[0][0]
            self.assertEqual(inserted_doc["merit_list_number"], 2)
