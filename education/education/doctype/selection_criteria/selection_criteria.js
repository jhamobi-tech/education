// Copyright (c) 2024, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Selection Criteria", {
	refresh(frm) {
		frm.trigger("render_weightage_indicator");
		frm.add_custom_button(__("Validate Weightages"), () => frm.trigger("validate_weightages"));
	},

	// Recompute indicator whenever weightage table changes
	weightage_configuration_add(frm)    { frm.trigger("render_weightage_indicator"); },
	weightage_configuration_remove(frm) { frm.trigger("render_weightage_indicator"); },

	validate_weightages(frm) {
		const total = _sum_active_weightages(frm);
		if (Math.abs(total - 100) > 0.01) {
			frappe.msgprint({
				title: __("Weightage Error"),
				message: __("Total active weightage is {0}%. It must equal 100%.", [total.toFixed(2)]),
				indicator: "red",
			});
		} else {
			frappe.show_alert({ message: __("Weightages sum to 100% ✓"), indicator: "green" });
		}
	},

	render_weightage_indicator(frm) {
		const total = _sum_active_weightages(frm);
		frm.set_value("total_weightage", total);
		const color   = Math.abs(total - 100) < 0.01 ? "green" : "orange";
		const label   = __("Total Active Weightage: {0}%", [total.toFixed(2)]);
		frm.dashboard.set_headline_alert(
			`<span class="indicator ${color}">${label}</span>`
		);
	},
});

// ── Selection Weightage Item child table ─────────────────────────────────────
frappe.ui.form.on("Selection Weightage Item", {
	weightage(frm) { frm.trigger("render_weightage_indicator"); },
	is_active(frm)  { frm.trigger("render_weightage_indicator"); },

	exam_name(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.exam_name) return;
		const defined = (frm.doc.entrance_exams || []).map(e => e.exam_name);
		if (!defined.includes(row.exam_name)) {
			frappe.show_alert({
				message: __("Exam '{0}' is not listed in Entrance Exams.", [row.exam_name]),
				indicator: "orange",
			});
		}
	},
});

function _sum_active_weightages(frm) {
	return (frm.doc.weightage_configuration || []).reduce(
		(sum, row) => sum + (row.is_active ? flt(row.weightage) : 0), 0
	);
}
