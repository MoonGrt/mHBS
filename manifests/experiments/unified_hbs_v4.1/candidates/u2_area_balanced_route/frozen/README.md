# Frozen INIT evidence

The synthesis snapshot contains the earlier freeze checker. For reproduction, replace
`experiments/v4.1/freeze_images.tcl` in the extracted snapshot with the archived
`flow.tcl` before invoking it. Vivado `list_property` on hierarchical cells triggered
isolation transformations; this checker reads an explicit property list instead.
No synthesis, placement or routing is rerun during INIT substitution.

`hardware.txt.gz`, when present, is lossless gzip of the serialized cell/configuration,
connectivity, placement and route proof. SHA-256 values in `evidence.tsv` refer to the
uncompressed bytes. All seven DCPs must have the same hardware hash and resources.
