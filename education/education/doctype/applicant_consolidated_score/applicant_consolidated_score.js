// Copyright (c) 2024, Frappe Technologies and contributors
// For license information, please see license.txt

const EXAM_MAX_SCORES = {
	CAT: 100, XAT: 100, MAT: 100,
	NMAT: 600, SNAP: 150, CMAT: 400, GMAT: 800, GRE: 340,
};

const SCORE_FIELDS = ["cet_score", "gd_score", "pi_score", "extempore_score"];

frappe.ui.form.on("Applicant Consolidated Score", {
	refresh(frm) {
		frm.add_custom_button(__("Compute Score"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Please save the form before computing."));
				return;
			}
			frappe.call({
				method: "education.education.doctype.applicant_consolidated_score.applicant_consolidated_score_api.compute_score",
				args: { docname: frm.doc.name },
				freeze: true,
				freeze_message: __("Computing consolidated score..."),
				callback(r) {
					if (r.message) {
						frm.reload_doc();
						frappe.show_alert({
							message: __("Consolidated Score: {0}", [r.message.consolidated_score]),
							indicator: "green",
						});
					}
				},
			});
		}, __("Actions"));
	},

	student_applicant(frm) {
		if (!frm.doc.student_applicant) return;
		frappe.db.get_value("Student Applicant", frm.doc.student_applicant, ["program", "academic_year"])
			.then(r => {
				if (r.message) {
					frm.set_value("program", r.message.program);
					frm.set_value("academic_year", r.message.academic_year);
				}
			});
	},

	...Object.fromEntries(
		SCORE_FIELDS.map(f => [f, (frm) => update_score_preview(frm)])
	),
});

frappe.ui.form.on("Applicant External Exam Score", {
	exam_name(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.exam_name && EXAM_MAX_SCORES[row.exam_name] && !row.maximum_score) {
			frappe.model.set_value(cdt, cdn, "maximum_score", EXAM_MAX_SCORES[row.exam_name]);
		}
	},

	actual_score(frm) { update_score_preview(frm); },
	maximum_score(frm) { update_score_preview(frm); },
	external_exam_scores_remove(frm) { update_score_preview(frm); },
});

function update_score_preview(frm) {
	if (!frm.doc.student_applicant) return;

	const external_exam_scores = (frm.doc.external_exam_scores || []).map(r => ({
		exam_name: r.exam_name,
		actual_score: r.actual_score || 0,
		maximum_score: r.maximum_score || 0,
	}));

	frappe.call({
		method: "education.education.doctype.applicant_consolidated_score.applicant_consolidated_score_api.get_score_preview",
		args: {
			student_applicant: frm.doc.student_applicant,
			external_exam_scores: JSON.stringify(external_exam_scores),
			cet_score: frm.doc.cet_score || 0,
			gd_score: frm.doc.gd_score || 0,
			pi_score: frm.doc.pi_score || 0,
			extempore_score: frm.doc.extempore_score || 0,
			weightage_config: frm.doc.weightage_config || null,
		},
		callback(r) {
			if (!r.message) return;
			const d = r.message;
			frm.set_value("best_external_exam_score", d.best_external_exam_score);
			frm.set_value("best_external_exam_name", d.best_external_exam_name);

			// Show preview in a dashboard section without saving
			const rows = (d.components || [])
				.map(c => `<tr>
					<td>${c.component}</td>
					<td>${c.score.toFixed(2)}</td>
					<td>${c.weightage}</td>
					<td><b>${c.weighted_score.toFixed(4)}</b></td>
				</tr>`)
				.join("");

			frm.dashboard.reset();
			frm.dashboard.add_section(
				`<div class="score-preview">
					<h5>${__("Score Preview (unsaved)")}</h5>
					<table class="table table-bordered table-sm">
						<thead><tr>
							<th>${__("Component")}</th>
							<th>${__("Score /100")}</th>
							<th>${__("Weightage")}</th>
							<th>${__("Weighted Score")}</th>
						</tr></thead>
						<tbody>${rows}</tbody>
					</table>
					<p><b>${__("Estimated Consolidated Score")}: ${d.consolidated_score.toFixed(2)}</b></p>
				</div>`,
				__("Live Score Preview")
			);
			frm.dashboard.show();
		},
	});
}
