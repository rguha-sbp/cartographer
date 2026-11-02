Parity goldens: curated diagrams and the `.drawio` they must render to, so refactors prove the output is unchanged.
Regenerate a pair by running `tf_layout.layout` then `gen_drawio.render(..., page_id="golden", page_name="golden")` on the curated JSON.
