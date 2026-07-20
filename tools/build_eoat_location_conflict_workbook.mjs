import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { SpreadsheetFile, Workbook } = require("@oai/artifact-tool");

const [planPath, outputPath, previewDir] = process.argv.slice(2);
if (!planPath || !outputPath || !previewDir) throw new Error("plan, output, and preview paths are required");
const plan = JSON.parse(await fs.readFile(planPath, "utf8"));
const conflicts = plan.observations.filter((row) => row.state === "CONFLICTING");
const conflictIds = new Set(conflicts.map((row) => row.observation_uuid));
const assertions = plan.assertions.filter((row) => conflictIds.has(row.observation_uuid));

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Review Summary");
summary.getRange("A1:F1").merge();
summary.getRange("A1").values = [["EOAT Atlas — Current Location Conflict Review"]];
summary.getRange("A1:F1").format = { fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 16 }, rowHeight: 30 };
summary.getRange("A3:B9").values = [
  ["Purpose", "Supervisor verification of unresolved current physical-location evidence"],
  ["Source workbook", plan.workbook],
  ["Workbook SHA-256", plan.workbook_sha256],
  ["Required schema", plan.required_schema_revision],
  ["Conflicting EOATs", conflicts.length],
  ["Competing assertions", assertions.length],
  ["Rule", "Do not infer installation from compatibility or machine context"],
];
summary.getRange("A3:A9").format = { fill: "#D9EAF7", font: { bold: true, color: "#17365D" } };
summary.getRange("A11:F11").values = [["Workflow", "1. Inspect evidence", "2. Physically verify", "3. Select disposition", "4. Record evidence", "5. Sign and date"]];
summary.getRange("A11:F11").format = { fill: "#2F75B5", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
summary.getRange("A13:F16").values = [
  ["Allowed disposition", "INSTALLED", "STORED", "UNKNOWN", "INACTIVE", "KEEP CONFLICTING"],
  ["Required if installed", "Verified machine number", "", "", "", ""],
  ["Required if stored", "", "Verified cabinet/location or 'unspecified'", "", "", ""],
  ["Prohibited", "Invented timestamps", "Invented cabinet names", "Compatibility as location", "Silent identity merge", "Insertion-order resolution"],
];
summary.getRange("A13:F13").format = { fill: "#E2F0D9", font: { bold: true, color: "#375623" } };
summary.getRange("A16:F16").format = { fill: "#FCE4D6", font: { bold: true, color: "#9C0006" }, wrapText: true };
summary.freezePanes.freezeRows(1);
summary.getRange("A1:F16").format.wrapText = true;
summary.getRange("A1:F16").format.autofitRows();
summary.getRange("A1:F16").format.autofitColumns();
summary.getRange("A1:A16").format.columnWidth = 24;
summary.getRange("B1:F16").format.columnWidth = 25;

const review = workbook.worksheets.add("Supervisor Review");
const reviewHeaders = [
  "EOAT Identifier", "Conflict Group", "Observation Date", "Workbook Rows", "Current Evidence Summary",
  "Supervisor Disposition", "Verified Machine", "Verified Storage Location", "Verification Method",
  "Verification Evidence / Notes", "Supervisor Name", "Sign-off Date", "Second Reviewer", "Second Review Date",
];
review.getRange(`A1:N${conflicts.length + 1}`).values = [reviewHeaders, ...conflicts.map((row) => [
  row.eoat_identifier, row.conflict_group_uuid, row.observed_on, row.source_row_number,
  row.original_source_wording, "KEEP CONFLICTING", "", "", "", "", "", "", "", "",
])];
review.getRange("A1:N1").format = { fill: "#17365D", font: { bold: true, color: "#FFFFFF" }, wrapText: true, rowHeight: 36 };
review.getRange(`F2:N${conflicts.length + 1}`).format = { fill: "#FFF2CC" };
review.getRange(`A2:E${conflicts.length + 1}`).format = { fill: "#F2F2F2" };
review.getRange(`A1:N${conflicts.length + 1}`).format.wrapText = true;
review.getRange(`A1:N${conflicts.length + 1}`).format.autofitRows();
review.getRange(`A2:N${conflicts.length + 1}`).format.rowHeight = 88;
for (const column of ["A", "C", "D", "F", "G", "H", "I", "K", "L", "M", "N"]) review.getRange(`${column}:${column}`).format.columnWidth = 18;
review.getRange("B:B").format.columnWidth = 38;
review.getRange("E:E").format.columnWidth = 58;
review.getRange("J:J").format.columnWidth = 48;
review.freezePanes.freezeRows(1);

const evidence = workbook.worksheets.add("Competing Evidence");
const evidenceHeaders = ["EOAT Identifier", "Conflict Group", "Assertion UUID", "Asserted State", "Machine", "Observed Date", "Sheet", "Row", "Original Source Wording"];
const conflictByObservation = Object.fromEntries(conflicts.map((row) => [row.observation_uuid, row.conflict_group_uuid]));
evidence.getRange(`A1:I${assertions.length + 1}`).values = [evidenceHeaders, ...assertions.map((row) => [
  row.eoat_identifier, conflictByObservation[row.observation_uuid], row.assertion_uuid, row.state,
  row.machine_number || "", row.observed_on, row.source_worksheet, row.source_row_number, row.original_source_wording,
])];
evidence.getRange("A1:I1").format = { fill: "#5B9BD5", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
evidence.getRange(`A1:I${assertions.length + 1}`).format.wrapText = true;
evidence.getRange(`A1:I${assertions.length + 1}`).format.autofitRows();
evidence.getRange(`A2:I${assertions.length + 1}`).format.rowHeight = 54;
for (const column of ["A", "D", "E", "F", "G", "H"]) evidence.getRange(`${column}:${column}`).format.columnWidth = 18;
evidence.getRange("B:C").format.columnWidth = 38;
evidence.getRange("I:I").format.columnWidth = 62;
evidence.freezePanes.freezeRows(1);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, fileName] of [["Review Summary", "summary.png"], ["Supervisor Review", "supervisor-review.png"]]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(JSON.stringify({ outputPath, conflicts: conflicts.length, assertions: assertions.length }));
