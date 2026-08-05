// A3 Retail — shared desk helpers, namespaced to avoid collisions with core.
frappe.provide("a3_retail");

Object.assign(a3_retail, {
	/** Currency formatting used across the custom pages. */
	money(value) {
		return format_currency(flt(value), frappe.defaults.get_default("currency") || "INR");
	},

	/** Status colour used by list indicators and the control tower. */
	status_colour(status) {
		const map = {
			Open: "orange", Draft: "grey", "Under Diagnosis": "blue",
			"Estimate Pending": "yellow", "Estimate Sent": "yellow",
			"Estimate Approved": "blue", "Estimate Rejected": "red",
			"Awaiting Parts": "orange", "In Progress": "blue", "On Hold": "grey",
			"Repair Completed": "purple", "QC Failed": "red", "QC Passed": "green",
			"Not Repairable": "red", "Ready for Delivery": "green",
			Delivered: "green", Closed: "grey", Cancelled: "red",
		};
		return map[status] || "grey";
	},

	/** Compress an image File to <= max_kb before upload (reception desk, exchange). */
	async compress_image(file, max_kb = 300, max_dim = 1280) {
		const bitmap = await createImageBitmap(file);
		const scale = Math.min(1, max_dim / Math.max(bitmap.width, bitmap.height));
		const canvas = document.createElement("canvas");
		canvas.width = Math.round(bitmap.width * scale);
		canvas.height = Math.round(bitmap.height * scale);
		canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);

		let quality = 0.85;
		let data = canvas.toDataURL("image/jpeg", quality);
		while (data.length / 1.37 / 1024 > max_kb && quality > 0.3) {
			quality -= 0.1;
			data = canvas.toDataURL("image/jpeg", quality);
		}
		return data;
	},

	/**
	 * Keyboard-wedge barcode scanners type fast and finish with Enter.
	 * Anything typed faster than `threshold` ms/char is treated as a scan.
	 */
	bind_scanner(input, on_scan, threshold = 40) {
		let buffer = "";
		let last = 0;
		input.addEventListener("keydown", (e) => {
			const now = Date.now();
			if (e.key === "Enter") {
				const scanned = buffer.length > 3 && now - last < threshold * 4;
				if (scanned || input.value) on_scan(input.value || buffer);
				buffer = "";
				e.preventDefault();
				return;
			}
			if (e.key.length === 1) {
				buffer = now - last > 500 ? e.key : buffer + e.key;
				last = now;
			}
		});
	},
});
